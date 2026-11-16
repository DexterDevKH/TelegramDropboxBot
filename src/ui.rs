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
    let text = "🚀 **GITHUB ACTIONS WORKFLOW BUILDER**\n\
                ──────────────────────────────\n\
                Choose a target iOS application to configure:\n\n\
                • 🚀 **DTKACE Plus** — Enhanced YouTube (13 modular tweaks)\n\
                • ✨ **DTLite Plus** — Lightweight YouTube (Ad-block, PiP, RYD)\n\
                • 🎵 **DTMusicUltimate** — DexTube Music (Lossless audio mod)\n\n\
                ──────────────────────────────\n\
                💡 *Select an app button below to customize and build.*";

    let buttons = serde_json::json!([
        [
            {"text": "🚀 DTKACE Plus", "callback_data": "sel:dtkace"},
            {"text": "✨ DTLite Plus", "callback_data": "sel:dtlite"}
        ],
        [
            {"text": "🎵 DTMusicUltimate", "callback_data": "sel:dtmusic"}
        ],
        [
            {"text": "❌ Dismiss", "callback_data": "cancel"}
        ]
    ]);

    (text.to_string(), buttons)
}

pub fn render_dashboard_text(state: &DashboardState) -> String {
    let target = get_target(&state.target_key).unwrap_or(&TARGET_DTKACE);
    let exts = get_extensions(&state.target_key);
    let decoded = decode_bitmask(&state.mask_hex, exts);

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
        "🛠️ **BUILD CONFIGURATION: {}**\n\
         ──────────────────────────────\n\
         • 📦 **Repository:** `{}`\n\
         • 📄 **Workflow:**   `{}`\n\
         • ℹ️ *{}*\n\n\
         📋 **Parameters:**\n\
         • 🔗 **IPA URL:**     {}\n\
         • 🏷️ **App Name:**    {}\n\
         • 🆔 **Bundle ID:**   {}\n",
        target.name,
        target.repo,
        target.workflow,
        target.desc,
        ipa_display,
        name_display,
        bundle_display
    );

    if target.has_extensions {
        text.push_str(&format!("• 💉 **Tweak URL:**   {}\n", tweak_display));
        text.push_str(&format!(
            "• 🧩 **Extensions:**  `{}/{} active`",
            decoded.enabled_count, decoded.total_count
        ));
        if !decoded.disabled.is_empty() {
            let disabled_names: Vec<&str> = exts
                .iter()
                .filter(|e| decoded.disabled.contains(&e.key.to_string()))
                .map(|e| e.name)
                .collect();
            text.push_str(&format!(" *(Disabled: {})*\n", disabled_names.join(", ")));
        } else {
            text.push_str(" *(All active)*\n");
        }
    }

    text.push_str(
        "──────────────────────────────\n\
         💡 *Tap buttons below to modify values or trigger dispatch:*",
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
        let exts = get_extensions(target_key);
        let decoded = decode_bitmask(&state.mask_hex, exts);
        buttons.push(vec![
            serde_json::json!({
                "text": if state.tweak.is_some() { "💉 Tweak: Custom ✅" } else { "💉 Set Tweak URL" },
                "callback_data": format!("ask:tweak:{}", target_key)
            }),
            serde_json::json!({
                "text": format!("🧩 Extensions ({}/{})", decoded.enabled_count, decoded.total_count),
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
            "text": "◀️ Change App",
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
        "🚀 **WORKFLOW DISPATCH SUCCESSFUL**\n\
         ──────────────────────────────\n\
         • 📦 **Target:**   `{}`\n\
         • 📄 **Workflow:** `{}`\n\
         • ⚡ **Status:**   `Queued on macOS runner`\n\
         ──────────────────────────────\n\
         💡 *Cloud runner is compiling tweaks. Click below to track progress.*",
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
                "text": "🌐 View Live Logs on GitHub",
                "url": format!("https://github.com/{}/actions", target.repo)
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
        "📊 **SYSTEM STATUS & METRICS**\n\
         ──────────────────────────────\n\
         • 🤖 **Telegram Bot:**   `{}`\n\
         • ☁️ **Dropbox Vault:**  `{}`\n\
         • 📁 **IPA Vault:**      `{}` (Cap: {} files)\n\
         • 📁 **DEB Vault:**      `{}` (Cap: {} files)\n\
         • 📦 **Chunk Size:**     `{} MB blocks`\n\
         • 🛡️ **Privacy Shield:** `{}`\n\
         ──────────────────────────────\n\
         ⚡ *Native engine is fully operational.*",
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

pub fn render_help_card() -> String {
    "⚡ **TELEGRAM TO DROPBOX PIPELINE**\n\
     ──────────────────────────────\n\
     📥 **Quick Transfer:** Forward any file or paste direct URLs (up to 2 GB).\n\
     🚀 **GitHub Builder:** Send `/build` to configure parameters & trigger builds.\n\n\
     🕹️ **Commands Manual**\n\
     • `/build` — Configure inputs, toggle extensions & dispatch build\n\
     • `/settweak` — Update secret TWEAK_URL env for DTKACE and DTLite\n\
     • `/checkversion` — Check official App Store iOS releases\n\
     • `/status` — View real-time runner status & health metrics\n\
     • `/ping` — Measure gateway round-trip edge latency\n\
     • `/help` — Display this operational manual\n\n\
     🟢 **Status:** Armed and ready for transmission."
        .to_string()
}

pub fn render_ping_card() -> String {
    "⚡ **GATEWAY PONG**\n\
     ──────────────────────────────\n\
     • 🟢 **Status:** `Operational (100%)`\n\
     • 🛰️ **Host:**   `Native Rust Core Engine`\n\
     • ⚡ **Engine:** `High-Performance Async Daemon`\n\n\
     💡 *Drop any media or URL to sync, or send /build to trigger builds.*"
        .to_string()
}

pub fn render_extensions_keyboard(target_key: &str, mask_hex: &str) -> serde_json::Value {
    let exts = get_extensions(target_key);
    let decoded = decode_bitmask(mask_hex, exts);
    let mut keyboard = Vec::new();

    for (i, chunk) in exts.chunks(2).enumerate() {
        let mut row = Vec::new();
        let idx1 = i * 2;
        let is_enabled1 = decoded.is_enabled(chunk[0].key);
        row.push(serde_json::json!({
            "text": format!("{} {}", if is_enabled1 { "✅" } else { "❌" }, chunk[0].name),
            "callback_data": format!("tgl:{}:{}:{}", target_key, idx1, mask_hex)
        }));
        if chunk.len() > 1 {
            let idx2 = idx1 + 1;
            let is_enabled2 = decoded.is_enabled(chunk[1].key);
            row.push(serde_json::json!({
                "text": format!("{} {}", if is_enabled2 { "✅" } else { "❌" }, chunk[1].name),
                "callback_data": format!("tgl:{}:{}:{}", target_key, idx2, mask_hex)
            }));
        }
        keyboard.push(row);
    }

    let all_disabled = decoded.enabled_count == 0;
    keyboard.push(vec![
        serde_json::json!({
            "text": if all_disabled { "⚡ Enable All" } else { "⚡ Disable All" },
            "callback_data": format!("tgl_all:{}:{}", target_key, mask_hex)
        }),
        serde_json::json!({
            "text": "🔄 Reset Defaults",
            "callback_data": format!("tgl_rst:{}", target_key)
        }),
    ]);

    keyboard.push(vec![serde_json::json!({
        "text": format!("💾 Save & Return ({}/{})", decoded.enabled_count, decoded.total_count),
        "callback_data": format!("ext_done:{}:{}", target_key, mask_hex)
    })]);

    serde_json::Value::Array(keyboard.into_iter().map(serde_json::Value::Array).collect())
}
