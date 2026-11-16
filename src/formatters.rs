//! Metric, Time, URL & Bitmask Presentation Formatting Utilities

use std::collections::HashSet;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Instant;

use regex::Regex;
use url::Url;

use crate::constants::ExtensionConfig;

/// Converts raw byte counts into clean human-readable formatted strings.
pub fn format_size(size_bytes: u64) -> String {
    if size_bytes == 0 {
        return "0 B".to_string();
    }
    let units = ["B", "KB", "MB", "GB"];
    let mut val = size_bytes as f64;
    for unit in units.iter() {
        if val < 1024.0 {
            return format!("{:.2} {}", val, unit);
        }
        val /= 1024.0;
    }
    format!("{:.2} TB", val)
}

/// Converts duration in seconds into clean human-readable ETA.
pub fn format_eta(seconds: f64) -> String {
    if seconds < 0.0 || seconds > 86400.0 {
        return "Calculating...".to_string();
    }
    let s = seconds as u64;
    if s < 60 {
        format!("{}s", s)
    } else if s < 3600 {
        format!("{}m {}s", s / 60, s % 60)
    } else {
        format!("{}h {}m", s / 3600, (s % 3600) / 60)
    }
}

/// Renders a sleek visual block progress bar: [████████░░░░] 66.7%
pub fn render_progress_bar(percent: f64, bar_length: usize) -> String {
    let clamped = percent.clamp(0.0, 100.0);
    let filled = ((bar_length as f64) * (clamped / 100.0)).round() as usize;
    let filled = filled.min(bar_length);
    let unfilled = bar_length.saturating_sub(filled);
    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(unfilled));
    format!("[{}] {:.1}%", bar, clamped)
}

/// Sanitizes filename for cross-platform cloud storage safety.
pub fn sanitize_filename(name: &str) -> String {
    if name.is_empty() {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        return format!("payload_{}.bin", now);
    }
    let forbidden = ['\\', '/', ':', '*', '?', '"', '<', '>', '|'];
    let clean: String = name.chars().filter(|c| !forbidden.contains(c)).collect();
    let trimmed = clean.trim();
    if trimmed.is_empty() {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        format!("payload_{}.bin", now)
    } else {
        trimmed.to_string()
    }
}

/// Sanitizes URLs ensuring Dropbox links use direct download dl=1.
pub fn normalize_url(url: &str) -> String {
    if url.is_empty() {
        return String::new();
    }
    let mut cleaned = url.trim().to_string();
    if cleaned.contains("dropbox.com") {
        if cleaned.contains("dl=0") {
            cleaned = cleaned.replace("dl=0", "dl=1");
        } else if !cleaned.contains("dl=1") {
            if cleaned.contains('?') {
                cleaned.push_str("&dl=1");
            } else {
                cleaned.push_str("?dl=1");
            }
        }
    }
    cleaned
}

/// Encodes disabled extension keys into a compact hexadecimal bitmask string.
pub fn encode_bitmask(disabled_keys: &[String], exts: &[ExtensionConfig]) -> String {
    if exts.is_empty() {
        return "0".to_string();
    }
    let disabled_set: HashSet<&str> = disabled_keys.iter().map(|s| s.as_str()).collect();
    let mut mask: u64 = 0;
    for (i, ext) in exts.iter().enumerate() {
        if !disabled_set.contains(ext.key) {
            mask |= 1 << i;
        }
    }
    format!("{:x}", mask)
}

#[derive(Debug, Clone)]
pub struct DecodedBitmask {
    pub disabled: Vec<String>,
    pub enabled_count: usize,
    pub total_count: usize,
    pub mask_hex: String,
}

impl DecodedBitmask {
    pub fn is_enabled(&self, key: &str) -> bool {
        !self.disabled.iter().any(|d| d == key)
    }
}

/// Decodes a hexadecimal bitmask string into enabled/disabled status.
pub fn decode_bitmask(mask_hex: &str, exts: &[ExtensionConfig]) -> DecodedBitmask {
    if exts.is_empty() {
        return DecodedBitmask {
            disabled: Vec::new(),
            enabled_count: 0,
            total_count: 0,
            mask_hex: "0".to_string(),
        };
    }
    let default_mask = (1u64 << exts.len()) - 1;
    let mask = if mask_hex.is_empty() {
        default_mask
    } else {
        u64::from_str_radix(mask_hex, 16).unwrap_or(default_mask)
    };

    let mut disabled = Vec::new();
    let mut enabled_count = 0;

    for (i, ext) in exts.iter().enumerate() {
        if (mask & (1 << i)) != 0 {
            enabled_count += 1;
        } else {
            disabled.push(ext.key.to_string());
        }
    }

    DecodedBitmask {
        disabled,
        enabled_count,
        total_count: exts.len(),
        mask_hex: format!("{:x}", mask),
    }
}

/// Exponential Moving Average (EMA) speed calculator for smooth transfer rate reporting.
pub struct SpeedTracker {
    pub alpha: f64,
    pub smoothed_speed: f64,
    pub last_bytes: u64,
    pub last_time: Option<Instant>,
}

impl SpeedTracker {
    pub fn new(alpha: f64) -> Self {
        Self {
            alpha,
            smoothed_speed: 0.0,
            last_bytes: 0,
            last_time: None,
        }
    }

    pub fn update(&mut self, current_bytes: u64) -> f64 {
        let now = Instant::now();
        let Some(prev_time) = self.last_time else {
            self.last_time = Some(now);
            self.last_bytes = current_bytes;
            return 0.0;
        };

        let elapsed = now.duration_since(prev_time).as_secs_f64();
        if elapsed <= 0.001 {
            return self.smoothed_speed;
        }

        let delta_bytes = current_bytes.saturating_sub(self.last_bytes) as f64;
        let instant_speed = delta_bytes / elapsed;

        if self.smoothed_speed == 0.0 {
            self.smoothed_speed = instant_speed;
        } else {
            self.smoothed_speed =
                (self.alpha * instant_speed) + ((1.0 - self.alpha) * self.smoothed_speed);
        }

        self.last_time = Some(now);
        self.last_bytes = current_bytes;
        self.smoothed_speed
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactUrlInfo {
    pub owner: String,
    pub repo: String,
    pub repo_full_name: String,
    pub artifact_id: String,
}

/// Parses a GitHub Actions artifact URL into owner, repo, and artifact_id.
pub fn parse_artifact_url(url: &str) -> Option<ArtifactUrlInfo> {
    if url.is_empty() {
        return None;
    }
    let re1 = Regex::new(
        r"https?://github\.com/([^/]+)/([^/]+)/(?:actions/runs/\d+|suites/\d+)/artifacts/(\d+)",
    )
    .ok()?;
    if let Some(caps) = re1.captures(url) {
        let owner = caps.get(1)?.as_str().to_string();
        let repo = caps.get(2)?.as_str().to_string();
        let artifact_id = caps.get(3)?.as_str().to_string();
        return Some(ArtifactUrlInfo {
            owner: owner.clone(),
            repo: repo.clone(),
            repo_full_name: format!("{}/{}", owner, repo),
            artifact_id,
        });
    }

    let re2 =
        Regex::new(r"https?://api\.github\.com/repos/([^/]+)/([^/]+)/actions/artifacts/(\d+)")
            .ok()?;
    if let Some(caps) = re2.captures(url) {
        let owner = caps.get(1)?.as_str().to_string();
        let repo = caps.get(2)?.as_str().to_string();
        let artifact_id = caps.get(3)?.as_str().to_string();
        return Some(ArtifactUrlInfo {
            owner: owner.clone(),
            repo: repo.clone(),
            repo_full_name: format!("{}/{}", owner, repo),
            artifact_id,
        });
    }

    None
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunUrlInfo {
    pub owner: String,
    pub repo: String,
    pub repo_full_name: String,
    pub run_id: String,
}

/// Parses a GitHub Actions workflow run URL into owner, repo, and run_id.
pub fn parse_run_url(url: &str) -> Option<RunUrlInfo> {
    if url.is_empty() {
        return None;
    }
    let re = Regex::new(r"https?://github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)/?$").ok()?;
    let caps = re.captures(url)?;
    let owner = caps.get(1)?.as_str().to_string();
    let repo = caps.get(2)?.as_str().to_string();
    let run_id = caps.get(3)?.as_str().to_string();
    Some(RunUrlInfo {
        owner: owner.clone(),
        repo: repo.clone(),
        repo_full_name: format!("{}/{}", owner, repo),
        run_id,
    })
}

/// Extracts filename from Content-Disposition header.
pub fn parse_content_disposition_filename(cd_header: &str) -> Option<String> {
    if cd_header.is_empty() {
        return None;
    }
    let re_star = Regex::new(r"(?i)filename\*=(?:UTF-8''|utf-8'')([^;]+)").ok()?;
    if let Some(caps) = re_star.captures(cd_header) {
        let raw = caps
            .get(1)?
            .as_str()
            .trim_matches(|c| c == '"' || c == '\'' || c == ' ');
        let unquoted = urlencoding_decode(raw);
        return Some(sanitize_filename(&unquoted));
    }

    let re_std = Regex::new(r#"(?i)filename="?([^";]+)"?"#).ok()?;
    if let Some(caps) = re_std.captures(cd_header) {
        let raw = caps
            .get(1)?
            .as_str()
            .trim_matches(|c| c == '"' || c == '\'' || c == ' ');
        let unquoted = urlencoding_decode(raw);
        return Some(sanitize_filename(&unquoted));
    }

    None
}

/// Minimal percent-decode helper
fn urlencoding_decode(input: &str) -> String {
    let mut bytes = Vec::new();
    let mut chars = input.bytes().peekable();
    while let Some(b) = chars.next() {
        if b == b'%' {
            let h1 = chars.next();
            let h2 = chars.next();
            if let (Some(h1), Some(h2)) = (h1, h2) {
                let hex_str = [h1, h2];
                if let Ok(s) = std::str::from_utf8(&hex_str) {
                    if let Ok(byte) = u8::from_str_radix(s, 16) {
                        bytes.push(byte);
                        continue;
                    }
                }
            }
        }
        bytes.push(b);
    }
    String::from_utf8_lossy(&bytes).to_string()
}

/// Extracts the filename component from a URL path, decoding percent-encoded chars.
pub fn extract_filename_from_url(url: &str, default_name: &str) -> String {
    if url.is_empty() {
        return default_name.to_string();
    }
    if let Ok(parsed) = Url::parse(url) {
        if let Some(mut segments) = parsed.path_segments() {
            if let Some(last) = segments.next_back() {
                let unquoted = urlencoding_decode(last);
                let trimmed = unquoted.trim();
                if !trimmed.is_empty() {
                    return sanitize_filename(trimmed);
                }
            }
        }
    }
    default_name.to_string()
}

#[derive(Debug, Clone)]
pub struct ExtractedZipFile {
    pub final_file_path: PathBuf,
    pub extracted_name: String,
    pub file_size: u64,
    pub extract_dest_dir: PathBuf,
}

/// Inspects a ZIP archive, filters out OS metadata (__MACOSX, .DS_Store, hidden files),
/// identifies the target file inside, extracts it to tmp_dir.
pub fn extract_single_file_from_zip(zip_path: &Path, tmp_dir: &Path) -> Option<ExtractedZipFile> {
    if !zip_path.exists() {
        return None;
    }
    let file = File::open(zip_path).ok()?;
    let mut archive = zip::ZipArchive::new(file).ok()?;

    let mut valid_indices = Vec::new();
    for i in 0..archive.len() {
        if let Ok(entry) = archive.by_index(i) {
            let name = entry.name().to_string();
            if !entry.is_dir()
                && !name.starts_with("__MACOSX")
                && !Path::new(&name)
                    .file_name()
                    .and_then(|f| f.to_str())
                    .map(|f| f.starts_with('.'))
                    .unwrap_or(false)
            {
                valid_indices.push((i, name, entry.size()));
            }
        }
    }

    if valid_indices.is_empty() {
        return None;
    }

    // Prioritize app / package binaries (.ipa, .deb, .tipa, .apk, .dylib)
    let priority_exts = [".ipa", ".deb", ".tipa", ".apk", ".dylib"];
    let chosen_idx = valid_indices
        .iter()
        .find(|(_, name, _)| {
            let lower = name.to_lowercase();
            priority_exts.iter().any(|ext| lower.ends_with(ext))
        })
        .or_else(|| valid_indices.iter().max_by_key(|(_, _, size)| *size))
        .map(|(idx, _, _)| *idx)?;

    let mut entry = archive.by_index(chosen_idx).ok()?;
    let raw_name = entry.name().to_string();
    let basename = Path::new(&raw_name)
        .file_name()
        .and_then(|f| f.to_str())
        .unwrap_or("extracted_file.bin")
        .to_string();

    let now_ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let extract_dest_dir = tmp_dir.join(format!("ext_{}_{}", now_ts, std::process::id()));
    std::fs::create_dir_all(&extract_dest_dir).ok()?;

    let sanitized_name = sanitize_filename(&basename);
    let final_flat = tmp_dir.join(format!("{}_{}", now_ts, sanitized_name));

    let mut out_file = File::create(&final_flat).ok()?;
    std::io::copy(&mut entry, &mut out_file).ok()?;
    drop(out_file);

    let file_size = std::fs::metadata(&final_flat).map(|m| m.len()).unwrap_or(0);

    Some(ExtractedZipFile {
        final_file_path: final_flat,
        extracted_name: sanitized_name,
        file_size,
        extract_dest_dir,
    })
}

/// Determines Dropbox destination path, retention folder, and presentation vault display.
pub fn resolve_dropbox_destination(
    filename: &str,
    ipa_folder: &str,
    deb_folder: &str,
) -> (String, String, String) {
    let is_ipa = filename.to_lowercase().ends_with(".ipa");
    let base_folder = if is_ipa {
        if ipa_folder.trim().is_empty() {
            "/IPA"
        } else {
            ipa_folder.trim()
        }
    } else {
        if deb_folder.trim().is_empty() {
            "/DEB"
        } else {
            deb_folder.trim()
        }
    };

    let mut folder = base_folder.trim_end_matches('/').to_string();
    if !folder.starts_with('/') {
        folder = format!("/{}", folder);
    }

    let dest_path = format!("{}/{}", folder, filename);
    let retention_folder = folder.clone();
    let vault_display = folder;
    (dest_path, retention_folder, vault_display)
}

/// Extracts CFBundleIdentifier from an IPA file's embedded Info.plist.
pub fn extract_ipa_bundle_id(file_path: &Path) -> Option<String> {
    if !file_path.exists() {
        return None;
    }
    let file = File::open(file_path).ok()?;
    let mut archive = zip::ZipArchive::new(file).ok()?;

    for i in 0..archive.len() {
        let entry = archive.by_index(i).ok()?;
        let name = entry.name().to_string();
        if name.starts_with("Payload/") && name.ends_with(".app/Info.plist") {
            let mut plist_bytes = Vec::new();
            let mut reader = entry;
            if reader.read_to_end(&mut plist_bytes).is_ok() {
                if let Ok(plist_val) = plist::Value::from_reader(std::io::Cursor::new(plist_bytes))
                {
                    if let Some(dict) = plist_val.as_dictionary() {
                        if let Some(bundle_id) =
                            dict.get("CFBundleIdentifier").and_then(|v| v.as_string())
                        {
                            return Some(bundle_id.trim().to_string());
                        }
                    }
                }
            }
        }
    }
    None
}

/// Identifies whether a bundle identifier or filename belongs to YouTube or YouTube Music.
pub fn match_app_bundle(identifier_or_name: &str) -> Option<&'static str> {
    if identifier_or_name.is_empty() {
        return None;
    }
    let clean = identifier_or_name.trim().to_lowercase();

    // Priority 1: Exact / substring check for YouTube Music
    if clean.contains("com.google.ios.youtubemusic")
        || clean.contains("youtubemusic")
        || clean.contains("dtmusic")
        || (clean.contains("music")
            && (clean.contains("youtube") || clean.contains("yt") || clean.contains("dextube")))
    {
        return Some("com.google.ios.youtubemusic");
    }

    // Priority 2: Exact / substring check for YouTube
    if clean.contains("com.google.ios.youtube")
        || clean.contains("dtkace")
        || clean.contains("dtlite")
        || clean.contains("youtube")
        || clean.contains("dextube")
    {
        return Some("com.google.ios.youtube");
    }

    None
}
