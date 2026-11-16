//! Privacy Shield & Log Sanitization Module

use std::io::{self, Write};

/// Masks filename for privacy in console logs (e.g. 'my_secret_file.pdf' -> 'my***e.pdf').
pub fn mask_filename(name: &str, enabled: bool) -> String {
    if !enabled || name.is_empty() {
        return name.to_string();
    }
    if let Some((base, ext)) = name.rsplit_once('.') {
        let masked_base = if base.chars().count() <= 3 {
            "***".to_string()
        } else {
            let start: String = base.chars().take(2).collect();
            let end: String = base.chars().rev().take(1).collect();
            format!("{}***{}", start, end)
        };
        format!("{}.{}", masked_base, ext)
    } else if name.chars().count() > 2 {
        let start: String = name.chars().take(2).collect();
        format!("{}***", start)
    } else {
        "***".to_string()
    }
}

/// Masks user ID for privacy in console logs (e.g. 12345678 -> '12***').
pub fn mask_user_id(user_id: i64, enabled: bool) -> String {
    if !enabled {
        return user_id.to_string();
    }
    let uid_str = user_id.to_string();
    if uid_str.chars().count() > 2 {
        let start: String = uid_str.chars().take(2).collect();
        format!("{}***", start)
    } else {
        "***".to_string()
    }
}

/// Registers dynamic mask in GitHub Actions runner so secret values never leak.
pub fn register_github_mask(secret_value: Option<&str>) {
    if let Some(val) = secret_value {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            println!("::add-mask::{}", trimmed);
            let _ = io::stdout().flush();
        }
    }
}
