//! Configuration Loader & Validation Module

use std::collections::HashSet;
use std::env;

#[derive(Debug, Clone)]
pub struct AppConfig {
    // Telegram credentials
    pub telegram_bot_token: String,
    pub telegram_api_id: i64,
    pub telegram_api_hash: String,

    // Dropbox credentials
    pub dropbox_app_key: Option<String>,
    pub dropbox_app_secret: Option<String>,
    pub dropbox_refresh_token: Option<String>,
    pub dropbox_access_token: Option<String>,
    pub dropbox_ipa_folder: String,
    pub dropbox_deb_folder: String,

    // Access control & limits
    pub authorized_user_ids: HashSet<i64>,
    pub max_files_in_folder: usize,
    pub max_files_in_deb_folder: Option<usize>,
    pub chunk_size_mb: usize,
    pub privacy_mode: bool,
    pub log_level: String,

    // GitHub Actions workflow dispatch & tracking
    pub gh_pat: String,
    pub gh_repo: String,

    // Targeted on-demand execution context
    pub target_chat_id: Option<i64>,
    pub target_message_id: Option<i64>,
    pub dispatch_message_id: Option<i64>,
    pub build_target_key: Option<String>,
    pub build_run_id: Option<i64>,
    pub build_start_time: f64,
    pub idle_keep_alive_seconds: u64,
    pub is_github_actions: bool,

    // URL & Artifact Ingestion Context
    pub download_url: Option<String>,
    pub is_artifact: bool,
    pub artifact_id: Option<String>,
    pub artifact_repo: Option<String>,
    pub file_name: Option<String>,
    pub file_size: u64,
}

impl AppConfig {
    pub fn is_authorized(&self, user_id: i64) -> bool {
        if self.authorized_user_ids.is_empty() {
            return true;
        }
        self.authorized_user_ids.contains(&user_id)
    }

    pub fn has_dropbox_credentials(&self) -> bool {
        (self.dropbox_refresh_token.is_some()
            && self.dropbox_app_key.is_some()
            && self.dropbox_app_secret.is_some())
            || self.dropbox_access_token.is_some()
    }

    pub fn dropbox_target_folder(&self) -> &str {
        &self.dropbox_ipa_folder
    }

    pub fn get_max_files_for_folder(&self, folder_path: &str) -> usize {
        let mut norm = folder_path.trim().trim_end_matches('/').to_string();
        if !norm.starts_with('/') {
            norm = format!("/{}", norm);
        }
        let mut deb_norm = self.dropbox_deb_folder.trim().trim_end_matches('/').to_string();
        if !deb_norm.starts_with('/') {
            deb_norm = format!("/{}", deb_norm);
        }

        if norm.eq_ignore_ascii_case(&deb_norm) {
            if let Some(deb_cap) = self.max_files_in_deb_folder {
                return deb_cap;
            }
        }
        self.max_files_in_folder
    }
}

pub fn load_config() -> Result<AppConfig, String> {
    dotenvy::dotenv().ok();

    let bot_token = env::var("TELEGRAM_BOT_TOKEN").unwrap_or_default().trim().to_string();
    let api_id_raw = env::var("TELEGRAM_API_ID").unwrap_or_default().trim().to_string();
    let api_hash = env::var("TELEGRAM_API_HASH").unwrap_or_default().trim().to_string();

    let api_id = api_id_raw.parse::<i64>().unwrap_or(0);

    let ipa_folder = env::var("DROPBOX_IPA_FOLDER")
        .or_else(|_| env::var("DROPBOX_TARGET_FOLDER"))
        .unwrap_or_else(|_| "/IPA".to_string())
        .trim()
        .to_string();
    let mut clean_ipa_folder = ipa_folder.trim_end_matches('/').to_string();
    if !clean_ipa_folder.starts_with('/') {
        clean_ipa_folder = format!("/{}", clean_ipa_folder);
    }

    let deb_folder = env::var("DROPBOX_DEB_FOLDER")
        .unwrap_or_else(|_| "/DEB".to_string())
        .trim()
        .to_string();
    let mut clean_deb_folder = deb_folder.trim_end_matches('/').to_string();
    if !clean_deb_folder.starts_with('/') {
        clean_deb_folder = format!("/{}", clean_deb_folder);
    }

    let max_files_global = env::var("MAX_FILES_IN_FOLDER")
        .unwrap_or_else(|_| "2".to_string())
        .trim()
        .parse::<usize>()
        .unwrap_or(2);

    let max_files_deb = env::var("MAX_FILES_IN_DEB_FOLDER")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok());

    let authorized_raw = env::var("AUTHORIZED_USER_IDS").unwrap_or_default();
    let mut authorized_ids = HashSet::new();
    for part in authorized_raw.split(',') {
        let trimmed = part.trim();
        if let Ok(id) = trimmed.parse::<i64>() {
            authorized_ids.insert(id);
        }
    }

    let target_chat = env::var("TARGET_CHAT_ID")
        .ok()
        .and_then(|v| v.trim().parse::<i64>().ok());
    let target_msg = env::var("TARGET_MESSAGE_ID")
        .ok()
        .and_then(|v| v.trim().parse::<i64>().ok());
    let disp_msg = env::var("DISPATCH_MESSAGE_ID")
        .ok()
        .and_then(|v| v.trim().parse::<i64>().ok());

    let build_target_key = env::var("BUILD_TARGET_KEY")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|s| !s.is_empty());
    let build_run_id = env::var("BUILD_RUN_ID")
        .ok()
        .and_then(|v| v.trim().parse::<i64>().ok())
        .filter(|id| *id > 0);

    let build_start_time = env::var("BUILD_START_TIME")
        .ok()
        .and_then(|v| v.trim().parse::<f64>().ok())
        .map(|ms| ms / 1000.0)
        .unwrap_or(0.0);

    let gh_pat = env::var("GH_PAT")
        .or_else(|_| env::var("PAT"))
        .or_else(|_| env::var("GITHUB_TOKEN"))
        .unwrap_or_default()
        .trim()
        .to_string();

    let gh_repo = env::var("GH_REPO")
        .unwrap_or_else(|_| "DexterDevKH/TelegramDropboxBot".to_string())
        .trim()
        .to_string();

    let privacy_raw = env::var("PRIVACY_MODE")
        .unwrap_or_else(|_| "true".to_string())
        .trim()
        .to_lowercase();
    let privacy_mode = privacy_raw == "true" || privacy_raw == "1" || privacy_raw == "yes";

    let log_level = env::var("LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string()).trim().to_string();

    let download_url = env::var("DOWNLOAD_URL")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|s| !s.is_empty());

    let is_artifact_raw = env::var("IS_ARTIFACT")
        .unwrap_or_else(|_| "false".to_string())
        .trim()
        .to_lowercase();
    let is_artifact = is_artifact_raw == "true" || is_artifact_raw == "1" || is_artifact_raw == "yes";

    let artifact_id = env::var("ARTIFACT_ID")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|s| !s.is_empty());

    let artifact_repo = env::var("ARTIFACT_REPO")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|s| !s.is_empty());

    let file_name = env::var("FILE_NAME")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|s| !s.is_empty());

    let file_size = env::var("FILE_SIZE")
        .unwrap_or_else(|_| "0".to_string())
        .trim()
        .parse::<u64>()
        .unwrap_or(0);

    let chunk_size_mb = env::var("CHUNK_SIZE_MB")
        .unwrap_or_else(|_| "8".to_string())
        .trim()
        .parse::<usize>()
        .unwrap_or(8);

    let idle_keep_alive_seconds = env::var("IDLE_KEEP_ALIVE_SECONDS")
        .unwrap_or_else(|_| "0".to_string())
        .trim()
        .parse::<u64>()
        .unwrap_or(0);

    let is_github_actions = env::var("GITHUB_ACTIONS")
        .map(|v| v.trim().to_lowercase() == "true")
        .unwrap_or(false);

    let dbx_app_key = env::var("DROPBOX_APP_KEY").ok().map(|v| v.trim().to_string()).filter(|s| !s.is_empty());
    let dbx_app_secret = env::var("DROPBOX_APP_SECRET").ok().map(|v| v.trim().to_string()).filter(|s| !s.is_empty());
    let dbx_refresh_token = env::var("DROPBOX_REFRESH_TOKEN").ok().map(|v| v.trim().to_string()).filter(|s| !s.is_empty());
    let dbx_access_token = env::var("DROPBOX_ACCESS_TOKEN").ok().map(|v| v.trim().to_string()).filter(|s| !s.is_empty());

    Ok(AppConfig {
        telegram_bot_token: bot_token,
        telegram_api_id: api_id,
        telegram_api_hash: api_hash,
        dropbox_app_key: dbx_app_key,
        dropbox_app_secret: dbx_app_secret,
        dropbox_refresh_token: dbx_refresh_token,
        dropbox_access_token: dbx_access_token,
        dropbox_ipa_folder: clean_ipa_folder,
        dropbox_deb_folder: clean_deb_folder,
        authorized_user_ids: authorized_ids,
        max_files_in_folder: max_files_global,
        max_files_in_deb_folder: max_files_deb,
        chunk_size_mb,
        privacy_mode,
        log_level,
        gh_pat,
        gh_repo,
        target_chat_id: target_chat,
        target_message_id: target_msg,
        dispatch_message_id: disp_msg,
        build_target_key,
        build_run_id,
        build_start_time,
        idle_keep_alive_seconds,
        is_github_actions,
        download_url,
        is_artifact,
        artifact_id,
        artifact_repo,
        file_name,
        file_size,
    })
}

