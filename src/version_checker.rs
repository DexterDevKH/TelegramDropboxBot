//! iOS App Store Version Monitor & Alert Service
//! Tracks official App Store releases for YouTube and YouTube Music.

use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use reqwest::header::USER_AGENT;
use serde::{Deserialize, Serialize};
use tracing::{error, info};

#[derive(Debug, Clone)]
pub struct TrackedAppMeta {
    pub key: &'static str,
    pub name: &'static str,
    pub bundle_id: &'static str,
    pub app_store_id: &'static str,
    pub target_keys: &'static [&'static str],
    pub icon: &'static str,
}

pub static IOS_TRACKED_APPS: &[TrackedAppMeta] = &[
    TrackedAppMeta {
        key: "youtube",
        name: "YouTube",
        bundle_id: "com.google.ios.youtube",
        app_store_id: "544007664",
        target_keys: &["dtkace", "dtlite"],
        icon: "📺",
    },
    TrackedAppMeta {
        key: "youtubemusic",
        name: "YouTube Music",
        bundle_id: "com.google.ios.youtubemusic",
        app_store_id: "1012933549",
        target_keys: &["dtmusic"],
        icon: "🎵",
    },
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ItunesRawResult {
    #[serde(rename = "trackName")]
    pub track_name: Option<String>,
    #[serde(rename = "bundleId")]
    pub bundle_id: Option<String>,
    pub version: Option<String>,
    #[serde(rename = "currentVersionReleaseDate")]
    pub current_version_release_date: Option<String>,
    #[serde(rename = "releaseNotes")]
    pub release_notes: Option<String>,
    #[serde(rename = "trackViewUrl")]
    pub track_view_url: Option<String>,
    #[serde(rename = "artworkUrl100")]
    pub artwork_url100: Option<String>,
    #[serde(rename = "minimumOsVersion")]
    pub minimum_os_version: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ItunesLookupResponse {
    pub results: Vec<ItunesRawResult>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IosAppInfo {
    pub app_key: String,
    pub app_name: String,
    pub bundle_id: String,
    pub version: String,
    pub release_date: String,
    pub release_date_full: String,
    pub release_notes: String,
    pub track_view_url: String,
    pub artwork_url: String,
    pub min_os: String,
    pub icon: String,
    pub target_keys: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IosVersionCacheEntry {
    pub version: String,
    #[serde(rename = "releaseDate")]
    pub release_date: String,
    #[serde(rename = "trackName")]
    pub track_name: String,
}

/// Queries official Apple iTunes Lookup API for iOS app metadata.
pub async fn fetch_ios_app_info(bundle_id: &str) -> Option<IosAppInfo> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(12))
        .build()
        .ok()?;

    let url = format!("https://itunes.apple.com/lookup?bundleId={}", bundle_id.trim());
    let resp = client
        .get(&url)
        .header(
            USER_AGENT,
            "TelegramDropboxBot/3.1.0 (iOS Version Monitor; Rust Native)",
        )
        .send()
        .await
        .ok()?;

    if !resp.status().is_success() {
        return None;
    }

    let data: ItunesLookupResponse = resp.json().await.ok()?;
    let r = data.results.into_iter().next()?;

    let release_date_raw = r.current_version_release_date.unwrap_or_default();
    let release_date = release_date_raw
        .split('T')
        .next()
        .unwrap_or(&release_date_raw)
        .to_string();

    let meta = IOS_TRACKED_APPS.iter().find(|m| m.bundle_id == bundle_id);

    Some(IosAppInfo {
        app_key: meta.map(|m| m.key).unwrap_or("app").to_string(),
        app_name: r.track_name.clone().unwrap_or_else(|| meta.map(|m| m.name).unwrap_or("iOS App").to_string()),
        bundle_id: r.bundle_id.unwrap_or_else(|| bundle_id.to_string()),
        version: r.version.unwrap_or_default(),
        release_date,
        release_date_full: release_date_raw,
        release_notes: r.release_notes.unwrap_or_else(|| "Bug fixes and performance improvements.".to_string()),
        track_view_url: r.track_view_url.unwrap_or_default(),
        artwork_url: r.artwork_url100.unwrap_or_default(),
        min_os: r.minimum_os_version.unwrap_or_default(),
        icon: meta.map(|m| m.icon).unwrap_or("📱").to_string(),
        target_keys: meta
            .map(|m| m.target_keys.iter().map(|s| s.to_string()).collect())
            .unwrap_or_default(),
    })
}

pub fn get_default_cache_path() -> PathBuf {
    PathBuf::from(".ios_versions_cache.json")
}

pub fn load_version_cache(path: &Path) -> HashMap<String, IosVersionCacheEntry> {
    if path.exists() {
        if let Ok(mut file) = File::open(path) {
            let mut contents = String::new();
            if file.read_to_string(&mut contents).is_ok() {
                if let Ok(cache) = serde_json::from_str(&contents) {
                    return cache;
                }
            }
        }
    }
    HashMap::new()
}

pub fn save_version_cache(path: &Path, cache: &HashMap<String, IosVersionCacheEntry>) {
    if let Ok(json_str) = serde_json::to_string_pretty(cache) {
        if let Ok(mut file) = File::create(path) {
            let _ = file.write_all(json_str.as_bytes());
        }
    }
}

/// Checks Apple App Store for all tracked apps (YouTube and YouTube Music).
/// Returns: (all_apps_data, alerts_list)
pub async fn check_all_ios_versions(
    cache_path: Option<&Path>,
) -> (Vec<IosAppInfo>, Vec<(IosAppInfo, Option<String>)>) {
    let default_path = get_default_cache_path();
    let effective_path = cache_path.unwrap_or(&default_path);

    let mut cache = load_version_cache(effective_path);
    let mut all_apps = Vec::new();
    let mut alerts = Vec::new();
    let mut cache_updated = false;

    for app in IOS_TRACKED_APPS {
        let bundle_id = app.bundle_id;
        if let Some(info) = fetch_ios_app_info(bundle_id).await {
            all_apps.push(info.clone());

            let current_ver = info.version.clone();
            let prev_entry = cache.get(bundle_id);
            let prev_ver = prev_entry.map(|e| e.version.clone());

            match prev_ver {
                None => {
                    // First run: seed cache without alert
                    cache.insert(
                        bundle_id.to_string(),
                        IosVersionCacheEntry {
                            version: current_ver.clone(),
                            release_date: info.release_date.clone(),
                            track_name: info.app_name.clone(),
                        },
                    );
                    cache_updated = true;
                    info!("Initialized iOS version tracking for {}: {}", app.name, current_ver);
                }
                Some(ref pv) if pv != &current_ver => {
                    // New version detected!
                    alerts.push((info.clone(), Some(pv.clone())));
                    cache.insert(
                        bundle_id.to_string(),
                        IosVersionCacheEntry {
                            version: current_ver.clone(),
                            release_date: info.release_date.clone(),
                            track_name: info.app_name.clone(),
                        },
                    );
                    cache_updated = true;
                    info!(
                        "New iOS version detected for {}: {} -> {}",
                        app.name, pv, current_ver
                    );
                }
                _ => {}
            }
        }
    }

    if cache_updated {
        save_version_cache(effective_path, &cache);
    }

    (all_apps, alerts)
}

pub fn format_version_alert_text(app_info: &IosAppInfo, prev_version: Option<&str>) -> String {
    let prev_str = prev_version
        .map(|v| format!("`{}`", v))
        .unwrap_or_else(|| "Initial Detection".to_string());

    let mut notes = app_info.release_notes.trim().to_string();
    if notes.chars().count() > 400 {
        notes = notes.chars().take(397).collect::<String>() + "...";
    }

    format!(
        "🚨 **NEW IOS VERSION DETECTED!**\n\
         ──────────────────────────────\n\
         {} **App:** {}\n\
         🆔 **Bundle ID:** `{}`\n\
         🆕 **New Version:** `{}`\n\
         ⏮️ **Previous Version:** {}\n\
         📅 **Release Date:** `{}`\n\
         ──────────────────────────────\n\
         📝 **Release Notes:**\n\
         {}\n\
         ──────────────────────────────\n\
         💡 *A new official iOS version is available! Tap below to build your updated IPA.*",
        app_info.icon,
        app_info.app_name,
        app_info.bundle_id,
        app_info.version,
        prev_str,
        app_info.release_date,
        notes
    )
}

pub fn format_version_status_text(apps_data: &[IosAppInfo]) -> String {
    let mut lines = vec![
        "🍎 **IOS APP STORE VERSION MONITOR**".to_string(),
        "──────────────────────────────".to_string(),
    ];

    for app in apps_data {
        let targets_str = app
            .target_keys
            .iter()
            .map(|k| format!("`{}`", k.to_uppercase()))
            .collect::<Vec<_>>()
            .join(", ");

        lines.push(format!(
            "{} **{}**\n\
             • 🆔 **Bundle ID:** `{}`\n\
             • 🏷️ **App Store Version:** `{}`\n\
             • 📅 **Released:** `{}`\n\
             • 🛠️ **Workflow Targets:** {}\n",
            app.icon, app.app_name, app.bundle_id, app.version, app.release_date, targets_str
        ));
    }

    lines.push(
        "──────────────────────────────\n\
         ⚡ *Auto-check monitor is active. You will receive an instant alert when YouTube or YouTube Music gets updated on iOS.*"
            .to_string(),
    );

    lines.join("\n")
}

pub async fn send_telegram_alert(
    bot_token: &str,
    chat_ids: &[i64],
    text: &str,
    buttons: Option<serde_json::Value>,
) -> Result<bool, String> {
    if bot_token.is_empty() || chat_ids.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let url = format!("https://api.telegram.org/bot{}/sendMessage", bot_token);
    let mut any_success = false;

    for chat_id in chat_ids {
        let mut payload = serde_json::json!({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": true,
        });

        if let Some(ref b) = buttons {
            payload["reply_markup"] = serde_json::json!({ "inline_keyboard": b });
        }

        match client.post(&url).json(&payload).send().await {
            Ok(resp) if resp.status().is_success() => {
                any_success = true;
            }
            Ok(resp) => {
                let err_text = resp.text().await.unwrap_or_default();
                error!("Failed to send alert to chat {}: {}", chat_id, err_text);
            }
            Err(e) => {
                error!("Alert request failed to chat {}: {}", chat_id, e);
            }
        }
    }

    Ok(any_success)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_version_alert_text() {
        let info = IosAppInfo {
            app_key: "youtube".to_string(),
            app_name: "YouTube: Watch, Listen, Stream".to_string(),
            bundle_id: "com.google.ios.youtube".to_string(),
            version: "20.02.1".to_string(),
            release_date: "2026-03-25".to_string(),
            release_date_full: "2026-03-25T08:00:00Z".to_string(),
            release_notes: "Bug fixes and improvements.".to_string(),
            track_view_url: "https://apps.apple.com/...".to_string(),
            artwork_url: "https://...".to_string(),
            min_os: "15.0".to_string(),
            icon: "📺".to_string(),
            target_keys: vec!["dtkace".to_string(), "dtlite".to_string()],
        };

        let card = format_version_alert_text(&info, Some("20.01.2"));
        assert!(card.contains("NEW IOS VERSION DETECTED!"));
        assert!(card.contains("`20.02.1`"));
        assert!(card.contains("`20.01.2`"));
        assert!(card.contains("com.google.ios.youtube"));
    }
}
