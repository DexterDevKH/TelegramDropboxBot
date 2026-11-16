//! GitHub Actions Workflow Dispatcher, Release Inspector & SealedBox Secret Encryption

use std::fs::File;
use std::io::Write;
use std::path::Path;

use base64::prelude::*;
use crypto_box::aead::rand_core::OsRng;
use crypto_box::PublicKey;
use futures_util::StreamExt;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};
use tracing::info;

use crate::formatters::{extract_filename_from_url, parse_content_disposition_filename};

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubWorkflowRun {
    pub id: i64,
    pub name: Option<String>,
    pub status: Option<String>,
    pub conclusion: Option<String>,
    pub html_url: Option<String>,
    pub run_number: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubRunsResponse {
    pub workflow_runs: Vec<GitHubWorkflowRun>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubAsset {
    pub id: i64,
    pub name: String,
    pub size: u64,
    pub browser_download_url: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubRelease {
    pub tag_name: Option<String>,
    pub html_url: Option<String>,
    pub assets: Vec<GitHubAsset>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubArtifact {
    pub id: i64,
    pub name: String,
    pub size_in_bytes: u64,
    pub expired: bool,
    pub expires_at: Option<String>,
    pub archive_download_url: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubArtifactsResponse {
    pub artifacts: Vec<GitHubArtifact>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GitHubPublicKeyResponse {
    pub key_id: String,
    pub key: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct GitHubPutSecretBody {
    pub encrypted_value: String,
    pub key_id: String,
}

pub struct GitHubService {
    pub pat: String,
    client: reqwest::Client,
}

impl GitHubService {
    pub fn new(pat: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(45))
            .build()
            .unwrap_or_default();
        Self { pat, client }
    }

    fn get_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            ACCEPT,
            HeaderValue::from_static("application/vnd.github+json"),
        );
        headers.insert(
            HeaderName::from_static("x-github-api-version"),
            HeaderValue::from_static("2022-11-28"),
        );
        headers.insert(
            USER_AGENT,
            HeaderValue::from_static("Telegram-Dropbox-Dispatcher"),
        );
        if !self.pat.is_empty() {
            if let Ok(val) = HeaderValue::from_str(&format!("Bearer {}", self.pat)) {
                headers.insert(AUTHORIZATION, val);
            }
        }
        headers
    }

    pub async fn trigger_workflow_dispatch(
        &self,
        repo: &str,
        workflow_file: &str,
        inputs: serde_json::Value,
    ) -> Result<(), String> {
        if self.pat.is_empty() {
            return Err(
                "Missing GH_PAT secret. Configure GH_PAT in GitHub Secrets or environment."
                    .to_string(),
            );
        }

        let url = format!(
            "https://api.github.com/repos/{}/actions/workflows/{}/dispatches",
            repo, workflow_file
        );
        let body = serde_json::json!({
            "ref": "main",
            "inputs": inputs,
        });

        let resp = self
            .client
            .post(&url)
            .headers(self.get_headers())
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("HTTP request failed: {}", e))?;

        let status = resp.status();
        if status.is_success() {
            Ok(())
        } else {
            let err_text = resp.text().await.unwrap_or_default();
            Err(format!("Dispatch error ({}): {}", status, err_text))
        }
    }

    pub async fn get_latest_workflow_run(&self, repo: &str) -> Option<GitHubWorkflowRun> {
        let url = format!(
            "https://api.github.com/repos/{}/actions/runs?per_page=1",
            repo
        );
        let resp = self
            .client
            .get(&url)
            .headers(self.get_headers())
            .send()
            .await
            .ok()?;

        if resp.status().is_success() {
            let data: GitHubRunsResponse = resp.json().await.ok()?;
            return data.workflow_runs.into_iter().next();
        }
        None
    }

    pub async fn get_workflow_run_details(
        &self,
        repo: &str,
        run_id: i64,
    ) -> Option<GitHubWorkflowRun> {
        let url = format!(
            "https://api.github.com/repos/{}/actions/runs/{}",
            repo, run_id
        );
        let resp = self
            .client
            .get(&url)
            .headers(self.get_headers())
            .send()
            .await
            .ok()?;

        if resp.status().is_success() {
            return resp.json::<GitHubWorkflowRun>().await.ok();
        }
        None
    }

    pub async fn get_artifact_metadata(
        &self,
        repo: &str,
        artifact_id: &str,
    ) -> Option<GitHubArtifact> {
        let url = format!(
            "https://api.github.com/repos/{}/actions/artifacts/{}",
            repo, artifact_id
        );
        let resp = self
            .client
            .get(&url)
            .headers(self.get_headers())
            .send()
            .await
            .ok()?;

        if resp.status().is_success() {
            return resp.json::<GitHubArtifact>().await.ok();
        }
        None
    }

    pub async fn get_run_artifacts(&self, repo: &str, run_id: i64) -> Vec<GitHubArtifact> {
        let url = format!(
            "https://api.github.com/repos/{}/actions/runs/{}/artifacts",
            repo, run_id
        );
        if let Ok(resp) = self
            .client
            .get(&url)
            .headers(self.get_headers())
            .send()
            .await
        {
            if resp.status().is_success() {
                if let Ok(data) = resp.json::<GitHubArtifactsResponse>().await {
                    return data.artifacts;
                }
            }
        }
        Vec::new()
    }

    /// Downloads artifact zip archive from GitHub Actions, following storage redirects safely.
    pub async fn download_artifact_zip<F>(
        &self,
        repo: &str,
        artifact_id: &str,
        dest_path: &Path,
        mut progress_cb: F,
    ) -> Result<(), String>
    where
        F: FnMut(u64, u64),
    {
        if self.pat.is_empty() {
            return Err(
                "Missing GH_PAT. GitHub Actions artifacts require authentication.".to_string(),
            );
        }

        let api_url = format!(
            "https://api.github.com/repos/{}/actions/artifacts/{}/zip",
            repo, artifact_id
        );

        // Reqwest redirects automatically, but stripping auth headers across domains is standard behavior
        let resp = self
            .client
            .get(&api_url)
            .headers(self.get_headers())
            .send()
            .await
            .map_err(|e| format!("Artifact request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let err_txt = resp.text().await.unwrap_or_default();
            return Err(format!(
                "GitHub artifact download error ({}): {}",
                status, err_txt
            ));
        }

        let total_bytes = resp.content_length().unwrap_or(0);
        let mut downloaded: u64 = 0;
        let mut file = File::create(dest_path)
            .map_err(|e| format!("Failed to create destination file {:?}: {}", dest_path, e))?;

        let mut stream = resp.bytes_stream();
        while let Some(chunk_result) = stream.next().await {
            let chunk = chunk_result.map_err(|e| format!("Chunk download error: {}", e))?;
            file.write_all(&chunk)
                .map_err(|e| format!("File write error: {}", e))?;
            downloaded += chunk.len() as u64;
            progress_cb(downloaded, total_bytes);
        }

        Ok(())
    }

    /// Downloads any arbitrary HTTP/HTTPS URL with streaming and progress reporting.
    /// Returns: (detected_filename, total_bytes)
    pub async fn download_stream_url<F>(
        &self,
        url: &str,
        dest_path: &Path,
        mut progress_cb: F,
    ) -> Result<(Option<String>, u64), String>
    where
        F: FnMut(u64, u64),
    {
        let resp = self
            .client
            .get(url)
            .header(
                USER_AGENT,
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            .send()
            .await
            .map_err(|e| format!("URL request error: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("HTTP error {}", resp.status()));
        }

        let mut detected_name = None;
        if let Some(cd) = resp.headers().get("content-disposition") {
            if let Ok(cd_str) = cd.to_str() {
                detected_name = parse_content_disposition_filename(cd_str);
            }
        }
        if detected_name.is_none() {
            detected_name = Some(extract_filename_from_url(
                resp.url().as_str(),
                "downloaded_file.bin",
            ));
        }

        let total_bytes = resp.content_length().unwrap_or(0);
        let mut downloaded: u64 = 0;
        let mut file = File::create(dest_path).map_err(|e| format!("File create error: {}", e))?;

        let mut stream = resp.bytes_stream();
        while let Some(chunk_res) = stream.next().await {
            let chunk = chunk_res.map_err(|e| format!("Stream error: {}", e))?;
            file.write_all(&chunk)
                .map_err(|e| format!("Write error: {}", e))?;
            downloaded += chunk.len() as u64;
            progress_cb(downloaded, total_bytes);
        }

        Ok((detected_name, downloaded))
    }

    /// Fetches repository public key for Actions secrets encryption.
    pub async fn get_repo_public_key(&self, repo: &str) -> Result<GitHubPublicKeyResponse, String> {
        if self.pat.is_empty() {
            return Err("Missing GH_PAT secret.".to_string());
        }
        let url = format!(
            "https://api.github.com/repos/{}/actions/secrets/public-key",
            repo
        );
        let resp = self
            .client
            .get(&url)
            .headers(self.get_headers())
            .send()
            .await
            .map_err(|e| format!("Public key request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let err = resp.text().await.unwrap_or_default();
            return Err(format!("Failed to get public key ({}): {}", status, err));
        }

        resp.json::<GitHubPublicKeyResponse>()
            .await
            .map_err(|e| format!("Parse public key JSON error: {}", e))
    }

    /// Encrypts secret string using Libsodium SealedBox (crypto_box sealed box).
    pub fn encrypt_secret_value(
        public_key_b64: &str,
        secret_value: &str,
    ) -> Result<String, String> {
        let pk_bytes = BASE64_STANDARD
            .decode(public_key_b64.trim())
            .map_err(|e| format!("Base64 decode public key error: {}", e))?;

        if pk_bytes.len() != 32 {
            return Err(format!(
                "Invalid public key length: expected 32 bytes, got {}",
                pk_bytes.len()
            ));
        }

        let mut key_array = [0u8; 32];
        key_array.copy_from_slice(&pk_bytes);

        let pk = PublicKey::from(key_array);
        let mut rng = OsRng;

        let encrypted = pk
            .seal(&mut rng, secret_value.as_bytes())
            .map_err(|e| format!("SealedBox encryption error: {:?}", e))?;

        Ok(BASE64_STANDARD.encode(&encrypted))
    }

    /// Updates a repository secret in GitHub Actions using libsodium sealed box encryption.
    pub async fn update_repository_secret(
        &self,
        repo: &str,
        secret_name: &str,
        secret_value: &str,
    ) -> Result<String, String> {
        let pk_data = self.get_repo_public_key(repo).await?;
        let encrypted_b64 = Self::encrypt_secret_value(&pk_data.key, secret_value)?;

        let put_url = format!(
            "https://api.github.com/repos/{}/actions/secrets/{}",
            repo, secret_name
        );
        let body = GitHubPutSecretBody {
            encrypted_value: encrypted_b64,
            key_id: pk_data.key_id,
        };

        let resp = self
            .client
            .put(&put_url)
            .headers(self.get_headers())
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("Failed to update secret: {}", e))?;

        let status = resp.status();
        if status.as_u16() == 201 || status.as_u16() == 204 {
            info!(
                "Successfully updated secret '{}' in repo '{}'",
                secret_name, repo
            );
            Ok("Secret updated successfully.".to_string())
        } else {
            let err_txt = resp.text().await.unwrap_or_default();
            Err(format!(
                "GitHub secret update error ({}): {}",
                status, err_txt
            ))
        }
    }
}
