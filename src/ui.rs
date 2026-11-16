//! Telegram UI Presentation Cards, Keyboards & Bot API v7.0+ Button Actions

use serde::{Deserialize, Serialize};

use crate::config::AppConfig;
use crate::constants::{
    get_default_bundle_id, get_default_display_name, get_extensions, get_target, BuildTarget,
    TARGET_DTKACE,
};
use crate::formatters::decode_bitmask;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DashboardState {
    pub target_key: String,
    pub ipa: Option<String>,
    pub name: Option<String>,
    pub bundle: Option<String>,
    pub tweak: Option<String>,
    pub mask_hex: String,
}

impl Default for DashboardState {
    fn default() -> Self {
        Self {
            target_key: "dtkace".to_string(),
            ipa: None,
            name: None,
            bundle: None,
            tweak: None,
            mask_hex: "1fff".to_string(),
        }
    }
}

pub fn render_main_menu() -> (String, serde_json::Value) {
    let text = "🚀 **TRIGGER GITHUB ACTIONS BUILD**\n\
        ──────────────────────────────\n\
        Choose which target repository you want to build:\n\n\
        • 🚀 **DTKACE Plus**: Enhanced YouTube with YTKACE & 13 extensions\n\
        • ✨ **DTLite Plus**: Lightweight YouTube mod with 10 extensions\n\
        • 🎵 **DTMusicUltimate**: DexTube Music (Lossless audio mod)\n\
        ──────────────────────────────\n\
        💡 *Tap an app button below to customize parameters & trigger the build.*";

    let buttons = serde_json::json!([
        [
            {"text": "🚀 DTKACE Plus", "callback_data": "sel:dtkace"},
            {"text": "✨ DTLite Plus", "callback_data": "sel:dtlite"}
        ],
        [
            {"text": "🎵 DTMusicUltimate", "callback_data": "sel:dtmusic"}
        ],
        [
            {"text": "❌ Cancel", "callback_data": "cancel"}
        ]
    ]);

    (text.to_string(), buttons)
}

pub fn render_dashboard_text(state: &DashboardState) -> String {
    let target = get_target(&state.target_key).unwrap_or(&TARGET_DTKACE);
    let exts = get_extensions(&state.target_key);
    let decoded = decode_bitmask(&state.mask_hex, exts);

    let mut ext_section = String::new();
    if target.has_extensions && !exts.is_empty() {
        ext_section = format!(
            "• 🧩 **Extensions:** `{}/{} active`",
            decoded.enabled_count, decoded.total_count
        );
        if !decoded.disabled.is_empty() {
            let disabled_names: Vec<&str> = exts
                .iter()
                .filter(|e| decoded.disabled.contains(&e.key.to_string()))
                .map(|e| e.name)
                .collect();
            ext_section.push_str(&format!(" *(Disabled: {})*\n", disabled_names.join(", ")));
        } else {
            ext_section.push_str(" *(All enabled)*\n");
        }
    }

    let ipa_display = state
        .ipa
        .as_deref()
        .map(|url| format!("`{}`", url))
        .unwrap_or_else(|| "⚠️ *Not Configured (Required)*".to_string());

    let name_display = format!(
        "`{}`",
        state
            .name
            .as_deref()
            .unwrap_or_else(|| get_default_display_name(&state.target_key))
    );

    let bundle_display = format!(
        "`{}`",
        state
            .bundle
            .as_deref()
            .unwrap_or_else(|| get_default_bundle_id(&state.target_key))
    );

    let tweak_display = state
        .tweak
        .as_deref()
        .map(|t| format!("`{}`", t))
        .unwrap_or_else(|| "`Default (Built-in)`".to_string());

    let mut text = format!(
        "🛠️ **BUILD PARAMETERS: {}**\n\
         ──────────────────────────────\n\
         📦 **Repository:** `{}`\n\
         📄 **Workflow:** `{}`\n\
         ℹ️ *{}*\n\n\
         📋 **Current Configuration:**\n\
         • 🔗 **IPA URL:** {}\n\
         • 🏷️ **App Name:** {}\n\
         • 🆔 **Bundle ID:** {}\n",
        target.name,
        target.repo,
        target.workflow,
        target.desc,
        ipa_display,
        name_display,
        bundle_display
    );

    if target.has_extensions {
        text.push_str(&format!("• 💉 **Tweak URL:** {}\n", tweak_display));
    }
    text.push_str(&ext_section);
    text.push_str(
        "──────────────────────────────\n\
         💡 *Press any button below to enter or change values:*",
    );

    text
}

pub fn render_dashboard_buttons(state: &DashboardState) -> serde_json::Value {
    let target_key = &state.target_key;
    let target = get_target(target_key).unwrap_or(&TARGET_DTKACE);
    let has_ipa = state.ipa.is_some();

    let mut buttons = Vec::new();

    buttons.push(vec![serde_json::json!({
        "text": if has_ipa { "🔗 Change IPA URL ✅" } else { "🔗 Set IPA URL (Required) ⚠️" },
        "callback_data": format!("ask:ipa:{}", target_key)
    })]);

    buttons.push(vec![
        serde_json::json!({
            "text": "🏷️ App Name",
            "callback_data": format!("ask:name:{}", target_key)
        }),
        serde_json::json!({
            "text": "🆔 Bundle ID",
            "callback_data": format!("ask:bundle:{}", target_key)
        }),
    ]);

    if target.has_extensions {
        buttons.push(vec![
            serde_json::json!({
                "text": "💉 Custom Tweak URL",
                "callback_data": format!("ask:tweak:{}", target_key)
            }),
            serde_json::json!({
                "text": "🧩 Extensions",
                "callback_data": format!("exts:{}:{}", target_key, state.mask_hex)
            }),
        ]);
    }

    if has_ipa {
        buttons.push(vec![serde_json::json!({
            "text": "🚀 TRIGGER GITHUB ACTIONS BUILD",
            "callback_data": format!("trig:{}", target_key)
        })]);
    }

    buttons.push(vec![
        serde_json::json!({
            "text": "◀️ Back",
            "callback_data": "nav:main"
        }),
        serde_json::json!({
            "text": "❌ Cancel",
            "callback_data": "cancel"
        }),
    ]);

    serde_json::Value::Array(buttons.into_iter().map(serde_json::Value::Array).collect())
}

pub fn render_build_success_card(
    target: &BuildTarget,
    _inputs: &serde_json::Value,
) -> (String, serde_json::Value) {
    let text = format!(
        "✅ **WORKFLOW DISPATCH SUCCESSFUL**\n\
         ──────────────────────────────\n\
         📦 **Target:** `{}`\n\
         📄 **Workflow:** `{}`\n\
         ──────────────────────────────\n\
         ⚡ *GitHub Actions runner is initializing... Click below to track execution.*",
        target.name, target.workflow
    );

    let buttons = serde_json::json!([
        [
            {
                "text": "🛰️ Track Build Progress",
                "callback_data": format!("track:{}", target.key)
            }
        ],
        [
            {
                "text": "🌐 View Repository",
                "url": format!("https://github.com/{}", target.repo)
            }
        ]
    ]);

    (text, buttons)
}

pub fn render_status_card(config: &AppConfig, account_name: &str) -> String {
    let bot_str = if config.privacy_mode {
        "@[PROTECTED]"
    } else {
        &config.telegram_bot_token
    };

    let dbx_str = if config.privacy_mode {
        "[PROTECTED/MASKED]"
    } else {
        account_name
    };

    let ipa_str = if config.privacy_mode {
        "[PROTECTED_VAULT]"
    } else {
        &config.dropbox_ipa_folder
    };

    let deb_str = if config.privacy_mode {
        "[PROTECTED_VAULT]"
    } else {
        &config.dropbox_deb_folder
    };

    format!(
        "🛡️ **CLOUD SYNC ENGINE STATUS**\n\
         ──────────────────────────────\n\
         🤖 **Telegram Bot:** `{}`\n\
         ☁️ **Dropbox Account:** `{}`\n\
         📁 **IPA Vault:** `{}` (Cap: {} files)\n\
         📁 **DEB Vault:** `{}` (Cap: {} files)\n\
         📦 **Chunk Size:** `{} MB`\n\
         🛡️ **Privacy Shield:** `{}`\n\
         ──────────────────────────────\n\
         ⚡ *Engine is fully operational.*",
        bot_str,
        dbx_str,
        ipa_str,
        config.max_files_in_folder,
        deb_str,
        config
            .max_files_in_deb_folder
            .unwrap_or(config.max_files_in_folder),
        config.chunk_size_mb,
        if config.privacy_mode {
            "Active (Masked)"
        } else {
            "Disabled"
        }
    )
}
