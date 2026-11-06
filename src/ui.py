"""
Telegram UI Presentation Cards, Keyboards & Bot API v7.0+ Button Actions
"""

import logging
from typing import Tuple, List, Dict, Any, Optional
import requests
from telethon import Button

from src.constants import BUILD_TARGETS, get_target, get_extensions
from src.formatters import (
    format_size,
    format_eta,
    render_progress_bar,
    normalize_url,
    decode_bitmask,
)

logger = logging.getLogger("SyncEngine.UI")

def render_main_menu() -> Tuple[str, List[List[Any]]]:
    """Returns the main app selection menu text and inline buttons."""
    text = (
        "🚀 **TRIGGER GITHUB ACTIONS BUILD**\n"
        "──────────────────────────────\n"
        "Choose which target repository you want to build:\n\n"
        "• 🚀 **DTKACE Plus**: Enhanced YouTube with YTKACE & 13 extensions\n"
        "• ✨ **DTLite Plus**: Lightweight YouTube mod with 10 extensions\n"
        "• 🎵 **DTMusicUltimate**: DexTube Music (Lossless audio mod)\n"
        "──────────────────────────────\n"
        "💡 *Tap an app button below to customize parameters & trigger the build.*"
    )
    buttons = [
        [
            Button.inline("🚀 DTKACE Plus", b"sel:dtkace"),
            Button.inline("✨ DTLite Plus", b"sel:dtlite"),
        ],
        [
            Button.inline("🎵 DTMusicUltimate", b"sel:dtmusic"),
        ],
        [
            Button.inline("❌ Cancel", b"cancel"),
        ],
    ]
    return text, buttons

def render_dashboard_text(state: Dict[str, Any]) -> str:
    """Renders Parameters Dashboard text for the selected app."""
    target_key = state.get("targetKey", state.get("target", "dtkace"))
    target = get_target(target_key) or BUILD_TARGETS["dtkace"]
    exts = get_extensions(target_key)

    mask_hex = state.get("maskHex", "1fff")
    decoded = decode_bitmask(mask_hex, exts)

    ext_section = ""
    if target.get("hasExtensions") and exts:
        ext_section = f"• 🧩 **Extensions:** `{decoded['enabled_count']}/{decoded['total_count']} active`"
        if decoded["disabled"]:
            disabled_names = [e["name"] for e in exts if e["key"] in decoded["disabled"]]
            ext_section += f" *(Disabled: {', '.join(disabled_names)})*\n"
        else:
            ext_section += " *(All enabled)*\n"

    ipa_display = f"`{state['ipa']}`" if state.get("ipa") else "⚠️ *Not Configured (Required)*"
    name_display = f"`{state.get('name') or target.get('defaultInputs', {}).get('display_name', 'DexTube')}`"
    bundle_display = f"`{state.get('bundle') or target.get('defaultInputs', {}).get('bundle_id', 'com.google.ios.youtube')}`"
    tweak_display = f"`{state['tweak']}`" if state.get("tweak") else "`Default (Built-in)`"

    return (
        f"🛠️ **BUILD PARAMETERS: {target['name']}**\n"
        f"──────────────────────────────\n"
        f"📦 **Repository:** `{target['repo']}`\n"
        f"📄 **Workflow:** `{target['workflow']}`\n"
        f"ℹ️ *{target['desc']}*\n\n"
        f"📋 **Current Configuration:**\n"
        f"• 🔗 **IPA URL:** {ipa_display}\n"
        f"• 🏷️ **App Name:** {name_display}\n"
        f"• 🆔 **Bundle ID:** {bundle_display}\n"
        + (f"• 💉 **Tweak URL:** {tweak_display}\n" if target.get("hasExtensions") else "")
        + ext_section
        + "──────────────────────────────\n"
        "💡 *Press any button below to enter or change values:*"
    )

def render_dashboard_buttons(state: Dict[str, Any]) -> List[List[Any]]:
    """Renders inline buttons for the Parameters Dashboard."""
    target_key = state.get("targetKey", state.get("target", "dtkace"))
    target = get_target(target_key) or BUILD_TARGETS["dtkace"]
    has_ipa = bool(state.get("ipa"))

    buttons = [
        [
            Button.inline(
                "🔗 Change IPA URL ✅" if has_ipa else "🔗 Set IPA URL (Required) ⚠️",
                f"ask:ipa:{target_key}".encode("utf-8"),
            )
        ],
        [
            Button.inline(
                f"🏷️ Name: {state.get('name', 'Default')}",
                f"ask:name:{target_key}".encode("utf-8"),
            ),
            Button.inline(
                f"🆔 Bundle: {state.get('bundle', '').split('.')[-1] if state.get('bundle') else 'Default'}",
                f"ask:bundle:{target_key}".encode("utf-8"),
            ),
        ],
    ]

    if target.get("hasExtensions"):
        exts = get_extensions(target_key)
        mask_hex = state.get("maskHex", "1fff")
        decoded = decode_bitmask(mask_hex, exts)
        buttons.append([
            Button.inline(
                "💉 Tweak: Custom ✅" if state.get("tweak") else "💉 Set Tweak URL (Optional)",
                f"ask:tweak:{target_key}".encode("utf-8"),
            ),
            Button.inline(
                f"🧩 Extensions ({decoded['enabled_count']}/{decoded['total_count']})",
                f"ext:{target_key}".encode("utf-8"),
            ),
        ])

    buttons.append([
        Button.inline(
            "🚀 Trigger Build Now" if has_ipa else "🚀 Trigger Build (Set IPA First)",
            f"trig:{target_key}".encode("utf-8"),
        )
    ])

    buttons.append([
        Button.inline("◀️ Back", b"menu"),
        Button.inline("❌ Cancel", b"cancel"),
    ])

    return buttons

def render_extensions_keyboard(target_key: str, mask_hex: str) -> List[List[Any]]:
    """Renders a 2-column inline toggle matrix for modular extensions."""
    exts = get_extensions(target_key)
    keyboard: List[List[Any]] = []
    decoded = decode_bitmask(mask_hex, exts)
    disabled_set = set(decoded["disabled"])

    for i in range(0, len(exts), 2):
        row = []
        ext1 = exts[i]
        icon1 = "✅" if ext1["key"] not in disabled_set else "❌"
        row.append(Button.inline(f"{icon1} {ext1['name']}", f"tgl:{target_key}:{i}:{mask_hex}".encode("utf-8")))

        if i + 1 < len(exts):
            ext2 = exts[i + 1]
            icon2 = "✅" if ext2["key"] not in disabled_set else "❌"
            row.append(Button.inline(f"{icon2} {ext2['name']}", f"tgl:{target_key}:{i+1}:{mask_hex}".encode("utf-8")))

        keyboard.append(row)

    enabled_count = decoded["enabled_count"]
    all_disabled = (enabled_count == 0)

    keyboard.append([
        Button.inline(
            "⚡ Enable All" if all_disabled else "⚡ Disable All",
            f"tgl_all:{target_key}:{mask_hex}".encode("utf-8"),
        ),
        Button.inline(
            "🔄 Reset All",
            f"tgl_rst:{target_key}".encode("utf-8"),
        ),
    ])

    keyboard.append([
        Button.inline(f"💾 Save & Back ({enabled_count}/{len(exts)})", f"ext_done:{target_key}:{mask_hex}".encode("utf-8")),
    ])

    return keyboard

def render_build_tracking_card(
    target: Dict[str, Any], run_id: Optional[int], status: str, elapsed_secs: float, run_url: str
) -> Tuple[str, List[List[Any]]]:
    """Renders real-time workflow tracking card."""
    status_icon = "🟢" if status == "in_progress" else "🟡"
    status_text = "In Progress (Building on macOS runner...)" if status == "in_progress" else "Queued (Waiting for macOS runner...)"
    card = (
        f"⚙️ **BUILD IN PROGRESS: {target['name']}**\n"
        f"──────────────────────────────\n"
        f"📦 **Repository:** `{target['repo']}`\n"
        f"📄 **Workflow:** `{target['workflow']}`\n"
        + (f"🆔 **Run ID:** `{run_id}`\n" if run_id else "")
        + f"⏱️ **Elapsed Time:** `{format_eta(elapsed_secs)}`\n"
        f"{status_icon} **Status:** `{status_text}`\n"
        f"──────────────────────────────\n"
        f"⚡ *Auto-refreshing status in real-time (No action needed)...*\n"
        f"💡 *This card will automatically transform into your IPA download button once compilation finishes.*"
    )
    buttons = [
        [Button.url("🌐 View Live Logs on GitHub", run_url or f"https://github.com/{target['repo']}/actions")]
    ]
    return card, buttons

def render_build_completed_card(
    target: Dict[str, Any], release: Optional[Dict[str, Any]], ipa_asset: Optional[Dict[str, Any]], elapsed_secs: float
) -> Tuple[str, List[List[Any]], str]:
    """Renders completion card with 1-tap download button for compiled IPA."""
    asset_name = ipa_asset.get("name", f"{target['name']}.ipa") if ipa_asset else f"{target['name']}.ipa"
    asset_size = f" ({format_size(ipa_asset.get('size', 0))})" if ipa_asset and ipa_asset.get("size") else ""
    tag_name = release.get("tagName", "Latest") if release else "Latest"
    download_url = (
        ipa_asset.get("browser_download_url")
        if ipa_asset
        else (release.get("htmlUrl") if release else f"https://github.com/{target['repo']}/releases")
    )

    card = (
        f"🎉 **BUILD COMPLETED SUCCESSFULLY!**\n"
        f"──────────────────────────────\n"
        f"🚀 **Target:** `{target['name']}`\n"
        f"📦 **Package:** `{asset_name}`{asset_size}\n"
        f"🏷️ **Release Tag:** `{tag_name}`\n"
        f"⏱️ **Build Duration:** `{format_eta(elapsed_secs)}`\n"
        f"──────────────────────────────\n"
        f"✅ Your modified IPA is compiled and ready for download! Tap below to get your file."
    )
    buttons = [
        [Button.url("📥 Download IPA", download_url)],
        [Button.url("🌐 Open GitHub Release", release.get("htmlUrl") if release else f"https://github.com/{target['repo']}/releases")],
    ]
    return card, buttons, download_url

def render_build_failed_card(
    target: Dict[str, Any], run_id: Optional[int], conclusion: str, elapsed_secs: float, run_url: str
) -> Tuple[str, List[List[Any]]]:
    """Renders failure card with button to inspect workflow error logs."""
    conclusion_display = (conclusion or "FAILURE").upper()
    card = (
        f"❌ **BUILD FAILED**\n"
        f"──────────────────────────────\n"
        f"🚀 **Target:** `{target['name']}`\n"
        f"📦 **Repository:** `{target['repo']}`\n"
        + (f"🆔 **Run ID:** `{run_id}`\n" if run_id else "")
        + f"⚠️ **Conclusion:** `{conclusion_display}`\n"
        f"⏱️ **Elapsed Time:** `{format_eta(elapsed_secs)}`\n"
        f"──────────────────────────────\n"
        f"💡 *The build failed on the GitHub Actions runner. Tap below to inspect error logs.*"
    )
    buttons = [
        [Button.url("🌐 View Workflow on GitHub", run_url or f"https://github.com/{target['repo']}/actions")]
    ]
    return card, buttons

def apply_native_copy_button(bot_token: str, chat_id: int, message_id: int, shared_url: str) -> bool:
    """
    Applies official client-side CopyTextButton via HTTP Bot API (v7.0+).
    Writes direct download link (dl=1) straight to OS clipboard on a single tap.
    """
    web_url = shared_url
    direct_url = normalize_url(shared_url)

    endpoint = f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "📋 Copy Direct Link",
                        "copy_text": {"text": direct_url},
                    },
                    {
                        "text": "🌐 Open in Dropbox",
                        "url": web_url,
                    },
                ]
            ]
        },
    }
    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as exc:
        logger.error(f"Error applying Telegram Bot API CopyTextButton: {exc}")
        return False

