"""
iOS App Store Version Monitor & Alert Service (v3.0.0)
Tracks official App Store releases for YouTube and YouTube Music.
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("SyncEngine.VersionChecker")

IOS_TRACKED_APPS: List[Dict[str, Any]] = [
    {
        "key": "youtube",
        "name": "YouTube",
        "bundle_id": "com.google.ios.youtube",
        "app_store_id": "544007664",
        "target_keys": ["dtkace", "dtlite"],
        "icon": "📺",
    },
    {
        "key": "youtubemusic",
        "name": "YouTube Music",
        "bundle_id": "com.google.ios.youtubemusic",
        "app_store_id": "1012933549",
        "target_keys": ["dtmusic"],
        "icon": "🎵",
    },
]

def fetch_ios_app_info(bundle_id: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
    Queries official Apple iTunes Lookup API for iOS app metadata.
    Returns app info dictionary or None on failure.
    """
    encoded_bundle = urllib.parse.quote(bundle_id.strip())
    url = f"https://itunes.apple.com/lookup?bundleId={encoded_bundle}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TelegramDropboxBot/3.0.0 (iOS Version Monitor)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                results = data.get("results", [])
                if results and len(results) > 0:
                    r = results[0]
                    release_date_raw = r.get("currentVersionReleaseDate", "")
                    release_date = release_date_raw.split("T")[0] if "T" in release_date_raw else release_date_raw
                    return {
                        "trackName": r.get("trackName", ""),
                        "bundleId": r.get("bundleId", bundle_id),
                        "version": r.get("version", ""),
                        "releaseDate": release_date,
                        "releaseDateFull": release_date_raw,
                        "releaseNotes": r.get("releaseNotes", "Bug fixes and performance improvements."),
                        "trackViewUrl": r.get("trackViewUrl", ""),
                        "artworkUrl": r.get("artworkUrl100", ""),
                        "minOs": r.get("minimumOsVersion", ""),
                    }
    except Exception as exc:
        logger.warning(f"Error fetching iOS version for {bundle_id}: {exc}")
    return None

def get_default_state_path() -> str:
    """Returns local path for persisting known iOS app versions."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".ios_versions_cache.json")

def load_version_cache(cache_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads previously recorded app versions from disk."""
    path = cache_path or get_default_state_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to read version cache at {path}: {exc}")
    return {}

def save_version_cache(cache: Dict[str, Any], cache_path: Optional[str] = None):
    """Persists recorded app versions to disk."""
    path = cache_path or get_default_state_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as exc:
        logger.warning(f"Failed to save version cache to {path}: {exc}")

def check_all_ios_versions(
    cache_path: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], Optional[str]]]]:
    """
    Checks Apple App Store for all tracked apps (YouTube and YouTube Music).
    Returns (all_apps_data, alerts_list).
    alerts_list contains (app_info, previous_version) for each newly detected version.
    """
    cache = load_version_cache(cache_path)
    all_apps: List[Dict[str, Any]] = []
    alerts: List[Tuple[Dict[str, Any], Optional[str]]] = []
    cache_updated = False

    for app in IOS_TRACKED_APPS:
        bundle_id = app["bundle_id"]
        info = fetch_ios_app_info(bundle_id)
        if not info:
            continue

        info["app_key"] = app["key"]
        info["app_name"] = app["name"]
        info["icon"] = app["icon"]
        info["target_keys"] = app["target_keys"]
        all_apps.append(info)

        current_ver = info["version"]
        prev_data = cache.get(bundle_id)
        prev_ver = prev_data.get("version") if isinstance(prev_data, dict) else prev_data

        if prev_ver is None:
            # First run: seed cache without alert
            cache[bundle_id] = {
                "version": current_ver,
                "releaseDate": info.get("releaseDate", ""),
                "trackName": info.get("trackName", ""),
            }
            cache_updated = True
            logger.info(f"Initialized iOS version tracking for {app['name']}: {current_ver}")
        elif prev_ver != current_ver:
            # New version detected!
            alerts.append((info, prev_ver))
            cache[bundle_id] = {
                "version": current_ver,
                "releaseDate": info.get("releaseDate", ""),
                "trackName": info.get("trackName", ""),
            }
            cache_updated = True
            logger.info(f"New iOS version detected for {app['name']}: {prev_ver} -> {current_ver}")

    if cache_updated:
        save_version_cache(cache, cache_path)

    return all_apps, alerts

def format_version_alert_text(app_info: Dict[str, Any], prev_version: Optional[str] = None) -> str:
    """Renders alert card text for a newly released iOS app version."""
    prev_str = f"`{prev_version}`" if prev_version else "Initial Detection"
    notes = app_info.get("releaseNotes", "Bug fixes and improvements.").strip()
    if len(notes) > 400:
        notes = notes[:397] + "..."

    return (
        "🚨 **NEW IOS VERSION DETECTED!**\n"
        "──────────────────────────────\n"
        f"{app_info.get('icon', '📱')} **App:** {app_info.get('trackName', app_info.get('app_name', 'iOS App'))}\n"
        f"🆔 **Bundle ID:** `{app_info.get('bundleId')}`\n"
        f"🆕 **New Version:** `{app_info.get('version')}`\n"
        f"⏮️ **Previous Version:** {prev_str}\n"
        f"📅 **Release Date:** `{app_info.get('releaseDate', 'Recent')}`\n"
        "──────────────────────────────\n"
        "📝 **Release Notes:**\n"
        f"{notes}\n"
        "──────────────────────────────\n"
        "💡 *A new official iOS version is available! Tap below to build your updated IPA.*"
    )

def format_version_status_text(apps_data: List[Dict[str, Any]]) -> str:
    """Renders status overview text for all tracked iOS apps."""
    lines = [
        "🍎 **IOS APP STORE VERSION MONITOR**",
        "──────────────────────────────",
    ]
    for app in apps_data:
        targets_str = ", ".join([f"`{k.upper()}`" for k in app.get("target_keys", [])])
        lines.append(
            f"{app.get('icon', '📱')} **{app.get('trackName', app.get('app_name'))}**\n"
            f"• 🆔 **Bundle ID:** `{app.get('bundleId')}`\n"
            f"• 🏷️ **App Store Version:** `{app.get('version')}`\n"
            f"• 📅 **Released:** `{app.get('releaseDate', 'Recent')}`\n"
            f"• 🛠️ **Workflow Targets:** {targets_str}\n"
        )
    lines.append(
        "──────────────────────────────\n"
        "⚡ *Auto-check monitor is active. You will receive an instant alert when YouTube or YouTube Music gets updated on iOS.*"
    )
    return "\n".join(lines)

def send_telegram_alert_http(
    bot_token: str,
    chat_ids: List[int],
    text: str,
    buttons: Optional[List[List[Dict[str, str]]]] = None,
) -> bool:
    """Sends a Telegram alert message directly via HTTP Bot API."""
    if not bot_token or not chat_ids:
        return False

    success = False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for chat_id in chat_ids:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    success = True
        except Exception as exc:
            logger.error(f"Failed to send Telegram alert to chat {chat_id}: {exc}")

    return success

if __name__ == "__main__":
    # Standalone CLI / CI Runner Execution
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("Checking iOS App Store versions for YouTube and YouTube Music...")
    apps, new_alerts = check_all_ios_versions()
    print(format_version_status_text(apps))

    if new_alerts:
        print(f"\nFound {len(new_alerts)} new version alert(s)!")
        bot_tok = os.getenv("TELEGRAM_BOT_TOKEN")
        auth_raw = os.getenv("AUTHORIZED_USER_IDS", "")
        recipients = [int(i.strip()) for i in auth_raw.split(",") if i.strip().isdigit()]

        for app_info, prev_ver in new_alerts:
            alert_text = format_version_alert_text(app_info, prev_ver)
            print("\n" + alert_text)
            if bot_tok and recipients:
                send_telegram_alert_http(bot_tok, recipients, alert_text)
                print(f"Alert dispatched to {len(recipients)} recipient(s).")
    else:
        print("\nAll tracked iOS apps are up to date.")
