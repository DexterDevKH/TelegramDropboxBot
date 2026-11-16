//! Dropbox Cloud Storage Client & Streaming Operations

use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::sync::Arc;
use tokio::sync::RwLock;

use chrono::{DateTime, Utc};
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use tracing::{error, info, warn};

use crate::config::AppConfig;
use crate::formatters::{extract_ipa_bundle_id, match_rotation_family, normalize_url};
use crate::privacy::{mask_filename, register_github_mask};

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxTokenResponse {
    pub access_token: String,
    pub token_type: Option<String>,
    pub expires_in: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxName {
    pub display_name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxAccountResponse {
    pub name: DropboxName,
    pub email: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = ".tag")]
pub enum DropboxMetadataEntry {
    #[serde(rename = "file")]
    File(DropboxFileEntry),
    #[serde(rename = "folder")]
    Folder { id: String, name: String },
    #[serde(other)]
    Other,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxFileEntry {
    pub id: String,
    pub name: String,
    pub path_lower: Option<String>,
    pub path_display: Option<String>,
    pub size: Option<u64>,
    pub server_modified: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxListFolderResponse {
    pub entries: Vec<DropboxMetadataEntry>,
    pub cursor: String,
    pub has_more: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxUploadSessionStartResponse {
    pub session_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct DropboxUploadSessionCursor {
    pub session_id: String,
    pub offset: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct DropboxCommitInfo {
    pub path: String,
    pub mode: String,
    pub autorename: bool,
    pub mute: bool,
    pub strict_conflict: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct DropboxUploadSessionFinishArg {
    pub cursor: DropboxUploadSessionCursor,
    pub commit: DropboxCommitInfo,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxSharedLinkResponse {
    pub url: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DropboxListSharedLinksResponse {
    pub links: Vec<DropboxSharedLinkResponse>,
}

pub struct DropboxService {
    config: AppConfig,
    client: reqwest::Client,
    access_token: Arc<RwLock<Option<String>>>,
    pub account_name: String,
    pub account_email: String,
}

impl DropboxService {
    pub fn new(config: AppConfig) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .unwrap_or_default();

        let initial_token = config.dropbox_access_token.clone();

        Self {
            config,
            client,
            access_token: Arc::new(RwLock::new(initial_token)),
            account_name: "Connected Cloud Account".to_string(),
            account_email: String::new(),
        }
    }

    pub async fn refresh_access_token(&self) -> Result<String, String> {
        let refresh_token = self
            .config
            .dropbox_refresh_token
            .as_deref()
            .ok_or_else(|| "Missing DROPBOX_REFRESH_TOKEN".to_string())?;
        let app_key = self
            .config
            .dropbox_app_key
            .as_deref()
            .ok_or_else(|| "Missing DROPBOX_APP_KEY".to_string())?;
        let app_secret = self
            .config
            .dropbox_app_secret
            .as_deref()
            .ok_or_else(|| "Missing DROPBOX_APP_SECRET".to_string())?;

        let url = "https://api.dropboxapi.com/oauth2/token";
        let params = [
            ("grant_type", "refresh_token"),
            ("refresh_token", refresh_token),
            ("client_id", app_key),
            ("client_secret", app_secret),
        ];

        let resp = self
            .client
            .post(url)
            .form(&params)
            .send()
            .await
            .map_err(|e| format!("Dropbox OAuth request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let err_text = resp.text().await.unwrap_or_default();
            return Err(format!(
                "Dropbox OAuth token refresh error ({}): {}",
                status, err_text
            ));
        }

        let token_data: DropboxTokenResponse = resp
            .json()
            .await
            .map_err(|e| format!("Failed to parse Dropbox token response: {}", e))?;

        let mut lock = self.access_token.write().await;
        *lock = Some(token_data.access_token.clone());
        Ok(token_data.access_token)
    }

    pub async fn get_valid_token(&self) -> Result<String, String> {
        {
            let lock = self.access_token.read().await;
            if let Some(tok) = lock.as_ref() {
                return Ok(tok.clone());
            }
        }
        self.refresh_access_token().await
    }

    pub async fn initialize(&mut self) -> Result<bool, String> {
        if !self.config.has_dropbox_credentials() {
            warn!("No Dropbox credentials provided in environment.");
            return Ok(false);
        }

        let token = match self.get_valid_token().await {
            Ok(tok) => tok,
            Err(e) => {
                if self.config.dropbox_refresh_token.is_some() {
                    self.refresh_access_token().await?
                } else {
                    return Err(e);
                }
            }
        };

        let url = "https://api.dropboxapi.com/2/users/get_current_account";
        let resp = self
            .client
            .post(url)
            .bearer_auth(&token)
            .send()
            .await
            .map_err(|e| format!("Account query failed: {}", e))?;

        if resp.status().is_success() {
            if let Ok(acc) = resp.json::<DropboxAccountResponse>().await {
                self.account_name = acc.name.display_name.clone();
                self.account_email = acc.email.clone();

                if self.config.is_github_actions {
                    register_github_mask(Some(&self.account_name));
                    register_github_mask(Some(&self.account_email));
                }

                if self.config.privacy_mode {
                    info!("Authenticated Dropbox Account: [PROTECTED/MASKED]");
                } else {
                    info!(
                        "Authenticated Dropbox Account: {} ({})",
                        self.account_name, self.account_email
                    );
                }
                return Ok(true);
            }
        }

        Ok(false)
    }

    pub async fn list_folder(&self, folder_path: &str) -> Result<Vec<DropboxFileEntry>, String> {
        let token = self.get_valid_token().await?;
        let norm_path = if folder_path == "/" {
            String::new()
        } else {
            folder_path.trim_end_matches('/').to_string()
        };

        let mut files = Vec::new();
        let url_list = "https://api.dropboxapi.com/2/files/list_folder";
        let body = serde_json::json!({
            "path": norm_path,
            "recursive": false,
            "include_media_info": false,
            "include_deleted": false,
            "include_has_explicit_shared_members": false,
        });

        let resp = self
            .client
            .post(url_list)
            .bearer_auth(&token)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("list_folder HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let err_txt = resp.text().await.unwrap_or_default();
            return Err(format!("list_folder failed ({}): {}", status, err_txt));
        }

        let mut list_res: DropboxListFolderResponse = resp
            .json()
            .await
            .map_err(|e| format!("list_folder JSON error: {}", e))?;

        for entry in list_res.entries {
            if let DropboxMetadataEntry::File(f) = entry {
                files.push(f);
            }
        }

        let url_continue = "https://api.dropboxapi.com/2/files/list_folder/continue";
        while list_res.has_more {
            let cont_body = serde_json::json!({ "cursor": list_res.cursor });
            let cont_resp = self
                .client
                .post(url_continue)
                .bearer_auth(&token)
                .json(&cont_body)
                .send()
                .await
                .map_err(|e| format!("list_folder/continue HTTP error: {}", e))?;

            if !cont_resp.status().is_success() {
                break;
            }

            list_res = cont_resp
                .json()
                .await
                .map_err(|e| format!("list_folder/continue JSON error: {}", e))?;

            for entry in list_res.entries {
                if let DropboxMetadataEntry::File(f) = entry {
                    files.push(f);
                }
            }
        }

        Ok(files)
    }

    pub async fn delete_file(&self, path: &str) -> Result<(), String> {
        let token = self.get_valid_token().await?;
        let url = "https://api.dropboxapi.com/2/files/delete_v2";
        let body = serde_json::json!({ "path": path });

        let resp = self
            .client
            .post(url)
            .bearer_auth(&token)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("delete_v2 HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let err_txt = resp.text().await.unwrap_or_default();
            return Err(format!("delete_v2 error: {}", err_txt));
        }

        Ok(())
    }

    /// Enforces file retention on target Dropbox directory:
    /// 1. If incoming_target is specified: replaces any file of the same app or tweak family.
    /// 2. Enforces general FIFO retention cap.
    pub async fn enforce_folder_retention(
        &self,
        folder_path: &str,
        max_files: usize,
        incoming_target: Option<&str>,
        exclude_path: Option<&str>,
    ) -> Vec<String> {
        let mut deleted_files = Vec::new();
        if folder_path.trim().trim_matches('/').is_empty() || max_files == 0 {
            return deleted_files;
        }

        let files = match self.list_folder(folder_path).await {
            Ok(f) => f,
            Err(e) => {
                warn!("Retention listing skipped for {}: {}", folder_path, e);
                return deleted_files;
            }
        };

        let normalized_target = incoming_target.and_then(match_rotation_family);
        let normalized_exclude = exclude_path.unwrap_or("").to_lowercase().trim().to_string();
        let exclude_name = Path::new(&normalized_exclude)
            .file_name()
            .and_then(|f| f.to_str())
            .unwrap_or("")
            .to_lowercase();

        let mut remaining_files: Vec<DropboxFileEntry> = Vec::new();

        for item in files {
            let item_path = item
                .path_lower
                .as_deref()
                .unwrap_or(&item.name)
                .to_lowercase();
            let is_excluded = if normalized_exclude.is_empty() {
                false
            } else {
                item_path == normalized_exclude
                    || item.name.to_lowercase() == exclude_name
                    || item_path.trim_start_matches('/')
                        == normalized_exclude.trim_start_matches('/')
            };

            if is_excluded {
                remaining_files.push(item);
                continue;
            }

            if let Some(target_family) = normalized_target {
                if match_rotation_family(&item.name) == Some(target_family) {
                    let target_del_path = item.path_lower.as_deref().unwrap_or(&item.name);
                    match self.delete_file(target_del_path).await {
                        Ok(_) => {
                            deleted_files.push(item.name.clone());
                            let log_file = mask_filename(&item.name, self.config.privacy_mode);
                            let log_folder = if self.config.privacy_mode {
                                "[PROTECTED_VAULT]"
                            } else {
                                folder_path
                            };
                            info!(
                                "Auto-Rotation: Replaced existing {} file '{}' in {}",
                                target_family, log_file, log_folder
                            );
                        }
                        Err(err) => {
                            let log_file = mask_filename(&item.name, self.config.privacy_mode);
                            error!("Failed to replace/prune '{}': {}", log_file, err);
                        }
                    }
                    continue;
                }
            }

            remaining_files.push(item);
        }

        // FIFO Retention Cap
        if remaining_files.len() > max_files {
            remaining_files.sort_by_key(|item| item.server_modified.unwrap_or_else(Utc::now));
            let overflow_count = remaining_files.len() - max_files;
            for old_file in remaining_files.iter().take(overflow_count) {
                let target_del_path = old_file.path_lower.as_deref().unwrap_or(&old_file.name);
                match self.delete_file(target_del_path).await {
                    Ok(_) => {
                        deleted_files.push(old_file.name.clone());
                        let log_file = mask_filename(&old_file.name, self.config.privacy_mode);
                        let log_folder = if self.config.privacy_mode {
                            "[PROTECTED_VAULT]"
                        } else {
                            folder_path
                        };
                        info!(
                            "Retention Policy: Pruned oldest file '{}' from {}",
                            log_file, log_folder
                        );
                    }
                    Err(err) => {
                        let log_file = mask_filename(&old_file.name, self.config.privacy_mode);
                        error!("Failed to prune '{}': {}", log_file, err);
                    }
                }
            }
        }

        deleted_files
    }

    /// Uploads file to Dropbox using streaming chunk sessions for maximum reliability.
    pub async fn upload_file_chunked<F>(
        &self,
        local_path: &Path,
        dest_path: &str,
        target_folder: &str,
        chunk_size_mb: usize,
        mut progress_cb: F,
    ) -> Result<(String, Vec<String>), String>
    where
        F: FnMut(u64, u64),
    {
        let token = self.get_valid_token().await?;
        let metadata = std::fs::metadata(local_path)
            .map_err(|e| format!("Failed to read file metadata for {:?}: {}", local_path, e))?;
        let file_size = metadata.len();
        let chunk_bytes = (chunk_size_mb * 1024 * 1024) as u64;

        let mut file = File::open(local_path)
            .map_err(|e| format!("Failed to open file {:?}: {}", local_path, e))?;

        if file_size <= chunk_bytes {
            // Single chunk upload: /2/files/upload
            let mut buffer = Vec::with_capacity(file_size as usize);
            file.read_to_end(&mut buffer)
                .map_err(|e| format!("Failed to read file: {}", e))?;

            let commit_arg = serde_json::json!({
                "path": dest_path,
                "mode": "overwrite",
                "autorename": false,
                "mute": false,
                "strict_conflict": false
            });

            let mut headers = HeaderMap::new();
            headers.insert(
                AUTHORIZATION,
                HeaderValue::from_str(&format!("Bearer {}", token)).unwrap(),
            );
            headers.insert(
                "Dropbox-API-Arg",
                HeaderValue::from_str(&serde_json::to_string(&commit_arg).unwrap()).unwrap(),
            );
            headers.insert(
                CONTENT_TYPE,
                HeaderValue::from_static("application/octet-stream"),
            );

            let resp = self
                .client
                .post("https://content.dropboxapi.com/2/files/upload")
                .headers(headers)
                .body(buffer)
                .send()
                .await
                .map_err(|e| format!("files/upload error: {}", e))?;

            if !resp.status().is_success() {
                let err_text = resp.text().await.unwrap_or_default();
                return Err(format!("files/upload failed: {}", err_text));
            }

            progress_cb(file_size, file_size);
        } else {
            // Streaming chunked upload session
            // 1. Session start
            let mut first_chunk = vec![0u8; chunk_bytes as usize];
            let bytes_read = file
                .read(&mut first_chunk)
                .map_err(|e| format!("Read first chunk error: {}", e))?;
            first_chunk.truncate(bytes_read);

            let start_arg = serde_json::json!({ "close": false });
            let mut start_headers = HeaderMap::new();
            start_headers.insert(
                AUTHORIZATION,
                HeaderValue::from_str(&format!("Bearer {}", token)).unwrap(),
            );
            start_headers.insert(
                "Dropbox-API-Arg",
                HeaderValue::from_str(&serde_json::to_string(&start_arg).unwrap()).unwrap(),
            );
            start_headers.insert(
                CONTENT_TYPE,
                HeaderValue::from_static("application/octet-stream"),
            );

            let start_resp = self
                .client
                .post("https://content.dropboxapi.com/2/files/upload_session/start")
                .headers(start_headers)
                .body(first_chunk)
                .send()
                .await
                .map_err(|e| format!("upload_session/start error: {}", e))?;

            if !start_resp.status().is_success() {
                let err_txt = start_resp.text().await.unwrap_or_default();
                return Err(format!("upload_session/start failed: {}", err_txt));
            }

            let start_data: DropboxUploadSessionStartResponse = start_resp
                .json()
                .await
                .map_err(|e| format!("start JSON parse error: {}", e))?;
            let session_id = start_data.session_id;

            let mut offset = bytes_read as u64;
            progress_cb(offset, file_size);

            // 2. Append chunks & Finish
            let mut chunk_buf = vec![0u8; chunk_bytes as usize];
            while offset < file_size {
                let remaining = file_size - offset;
                file.seek(SeekFrom::Start(offset))
                    .map_err(|e| format!("Seek error: {}", e))?;

                let to_read = (chunk_bytes as usize).min(remaining as usize);
                let current_read = file
                    .read(&mut chunk_buf[..to_read])
                    .map_err(|e| format!("Read chunk error: {}", e))?;
                let chunk_slice = chunk_buf[..current_read].to_vec();

                if remaining <= chunk_bytes {
                    // Finish session
                    let finish_arg = DropboxUploadSessionFinishArg {
                        cursor: DropboxUploadSessionCursor {
                            session_id: session_id.clone(),
                            offset,
                        },
                        commit: DropboxCommitInfo {
                            path: dest_path.to_string(),
                            mode: "overwrite".to_string(),
                            autorename: false,
                            mute: false,
                            strict_conflict: false,
                        },
                    };

                    let mut fin_headers = HeaderMap::new();
                    fin_headers.insert(
                        AUTHORIZATION,
                        HeaderValue::from_str(&format!("Bearer {}", token)).unwrap(),
                    );
                    fin_headers.insert(
                        "Dropbox-API-Arg",
                        HeaderValue::from_str(&serde_json::to_string(&finish_arg).unwrap())
                            .unwrap(),
                    );
                    fin_headers.insert(
                        CONTENT_TYPE,
                        HeaderValue::from_static("application/octet-stream"),
                    );

                    let fin_resp = self
                        .client
                        .post("https://content.dropboxapi.com/2/files/upload_session/finish")
                        .headers(fin_headers)
                        .body(chunk_slice)
                        .send()
                        .await
                        .map_err(|e| format!("upload_session/finish error: {}", e))?;

                    if !fin_resp.status().is_success() {
                        let err_txt = fin_resp.text().await.unwrap_or_default();
                        return Err(format!("upload_session/finish failed: {}", err_txt));
                    }

                    progress_cb(file_size, file_size);
                    break;
                } else {
                    // Append chunk
                    let append_arg = serde_json::json!({
                        "cursor": {
                            "session_id": session_id,
                            "offset": offset,
                        },
                        "close": false,
                    });

                    let mut app_headers = HeaderMap::new();
                    app_headers.insert(
                        AUTHORIZATION,
                        HeaderValue::from_str(&format!("Bearer {}", token)).unwrap(),
                    );
                    app_headers.insert(
                        "Dropbox-API-Arg",
                        HeaderValue::from_str(&serde_json::to_string(&append_arg).unwrap())
                            .unwrap(),
                    );
                    app_headers.insert(
                        CONTENT_TYPE,
                        HeaderValue::from_static("application/octet-stream"),
                    );

                    let app_resp = self
                        .client
                        .post("https://content.dropboxapi.com/2/files/upload_session/append_v2")
                        .headers(app_headers)
                        .body(chunk_slice)
                        .send()
                        .await
                        .map_err(|e| format!("upload_session/append_v2 error: {}", e))?;

                    if !app_resp.status().is_success() {
                        let err_txt = app_resp.text().await.unwrap_or_default();
                        return Err(format!("upload_session/append_v2 failed: {}", err_txt));
                    }

                    offset += current_read as u64;
                    progress_cb(offset, file_size);
                }
            }
        }

        let log_dest = if self.config.privacy_mode {
            let fname = Path::new(dest_path)
                .file_name()
                .and_then(|f| f.to_str())
                .unwrap_or("file");
            format!("[PROTECTED_VAULT]/{}", mask_filename(fname, true))
        } else {
            dest_path.to_string()
        };
        info!("Successfully committed file to Dropbox: {}", log_dest);

        // Enforce FIFO Retention & Family-Aware Auto-Rotation
        let mut pruned_files = Vec::new();
        if !target_folder.trim().trim_matches('/').is_empty() {
            let cap = self.config.get_max_files_for_folder(target_folder);

            let mut incoming_target = None;
            if local_path
                .to_string_lossy()
                .to_lowercase()
                .ends_with(".ipa")
            {
                incoming_target = extract_ipa_bundle_id(local_path);
            }
            if incoming_target.is_none() {
                let fname = Path::new(dest_path)
                    .file_name()
                    .and_then(|f| f.to_str())
                    .unwrap_or("");
                incoming_target = match_rotation_family(fname).map(|s| s.to_string());
            }

            pruned_files = self
                .enforce_folder_retention(
                    target_folder,
                    cap,
                    incoming_target.as_deref(),
                    Some(dest_path),
                )
                .await;
        }

        // Shared link generation
        let mut shared_url = String::new();
        let create_link_url =
            "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings";
        let link_body = serde_json::json!({ "path": dest_path });

        let link_resp = self
            .client
            .post(create_link_url)
            .bearer_auth(&token)
            .json(&link_body)
            .send()
            .await;

        if let Ok(resp) = link_resp {
            if resp.status().is_success() {
                if let Ok(link_data) = resp.json::<DropboxSharedLinkResponse>().await {
                    shared_url = link_data.url;
                }
            } else {
                // If shared link already exists, fetch it
                let list_link_url = "https://api.dropboxapi.com/2/sharing/list_shared_links";
                let list_body = serde_json::json!({ "path": dest_path, "direct_only": true });
                if let Ok(list_resp) = self
                    .client
                    .post(list_link_url)
                    .bearer_auth(&token)
                    .json(&list_body)
                    .send()
                    .await
                {
                    if let Ok(list_data) = list_resp.json::<DropboxListSharedLinksResponse>().await
                    {
                        if let Some(first_link) = list_data.links.first() {
                            shared_url = first_link.url.clone();
                        }
                    }
                }
            }
        }

        Ok((normalize_url(&shared_url), pruned_files))
    }

    /// Interactive terminal utility to generate permanent Dropbox OAuth 2.0 refresh tokens.
    pub async fn generate_refresh_token_interactive() -> Result<String, String> {
        println!("====================================================================");
        println!("⚡ DROPBOX OAUTH 2.0 PERMANENT REFRESH TOKEN GENERATOR");
        println!("====================================================================");
        println!("Generates permanent offline refresh tokens for GitHub Actions CI\n");

        print!("🔑 Enter Dropbox App Key: ");
        io::stdout().flush().map_err(|e| e.to_string())?;
        let mut app_key = String::new();
        io::stdin()
            .read_line(&mut app_key)
            .map_err(|e| e.to_string())?;
        let app_key = app_key.trim();

        print!("🔒 Enter Dropbox App Secret: ");
        io::stdout().flush().map_err(|e| e.to_string())?;
        let mut app_secret = String::new();
        io::stdin()
            .read_line(&mut app_secret)
            .map_err(|e| e.to_string())?;
        let app_secret = app_secret.trim();

        if app_key.is_empty() || app_secret.is_empty() {
            return Err("Both App Key and App Secret are required.".to_string());
        }

        let oauth_url = format!(
            "https://www.dropbox.com/oauth2/authorize?client_id={}&response_type=code&token_access_type=offline",
            app_key
        );

        println!("\n──────────────────────────────────────────────────────────────────────");
        println!("📋 STEP 1: Open the authorization URL in your browser:\n");
        println!("  👉 {}\n", oauth_url);
        println!("📋 STEP 2: Sign in, approve app permissions, and copy the authorization code.");
        println!("──────────────────────────────────────────────────────────────────────\n");

        print!("📥 Paste Authorization Code here: ");
        io::stdout().flush().map_err(|e| e.to_string())?;
        let mut code = String::new();
        io::stdin()
            .read_line(&mut code)
            .map_err(|e| e.to_string())?;
        let code = code.trim();

        if code.is_empty() {
            return Err("Authorization code cannot be empty.".to_string());
        }

        println!("\n⏳ Exchanging authorization code for permanent refresh token...");

        let client = reqwest::Client::new();
        let resp = client
            .post("https://api.dropbox.com/oauth2/token")
            .basic_auth(app_key, Some(app_secret))
            .form(&[("code", code), ("grant_type", "authorization_code")])
            .send()
            .await
            .map_err(|e| format!("OAuth request failed: {}", e))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status.is_success() {
            let data: serde_json::Value =
                serde_json::from_str(&body).map_err(|e| format!("Invalid JSON response: {}", e))?;

            if let Some(refresh_token) = data.get("refresh_token").and_then(|v| v.as_str()) {
                println!("\n====================================================================");
                println!("✅ AUTHORIZATION SUCCESSFUL!");
                println!("====================================================================");
                println!("Add this value to your GitHub Repository Secrets:");
                println!("Secret Name: DROPBOX_REFRESH_TOKEN\n");
                println!("DROPBOX_REFRESH_TOKEN:\n{}\n", refresh_token);
                println!("────────────────────────────────────────────────────────────────────");
                Ok(refresh_token.to_string())
            } else {
                Err(format!("No refresh_token returned in response: {}", body))
            }
        } else {
            Err(format!("Token exchange failed (HTTP {}): {}", status, body))
        }
    }
}
