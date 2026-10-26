#!/usr/bin/env python3
"""
Telegram Webhook to GitHub Actions Dispatcher (Docker & Standalone Server)
Author: Automated Cloud Solutions
Description: High-performance, lightweight webhook receiver that intercepts incoming
             Telegram media files, sends an instant acknowledgment to the user,
             and triggers GitHub Actions on-demand via repository_dispatch.
"""

import os
import sys
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Set
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ WebhookDispatcher: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("WebhookDispatcher")

# ---------------------------------------------------------------------------
# Configuration & Credentials
# ---------------------------------------------------------------------------
PORT = int(os.getenv("PORT", "8080"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "").strip()
GH_REPO = os.getenv("GH_REPO", "DexterDevKH/TelegramDropboxBot").strip()
GH_PAT = os.getenv("GH_PAT", "").strip()
AUTHORIZED_USER_IDS_RAW = os.getenv("AUTHORIZED_USER_IDS", "").strip()

AUTHORIZED_USER_IDS: Set[int] = set()
if AUTHORIZED_USER_IDS_RAW:
    for item in AUTHORIZED_USER_IDS_RAW.split(","):
        item = item.strip()
        if item.isdigit():
            AUTHORIZED_USER_IDS.add(int(item))

# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------
def format_size(bytes_val: int) -> str:
    """Formats bytes into human-readable strings."""
    if not bytes_val:
        return "Unknown size"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def send_telegram_message(chat_id: int, reply_to_id: Optional[int], text: str) -> bool:
    """Dispatches a direct Telegram markdown message using the standard Bot API."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to_id:
        payload["reply_to_message_id"] = reply_to_id

    try:
        resp = requests.post(url, json=payload, timeout=8)
        return resp.status_code == 200
    except Exception as exc:
        logger.error(f"Failed to deliver Telegram feedback message: {exc}")
        return False


def dispatch_github_action(chat_id: int, message_id: int, user_id: int, has_media: bool, text: str, file_name: str) -> bool:
    """Dispatches the on-demand sync event to GitHub Actions via repository_dispatch."""
    if not GH_PAT:
        logger.error("Configuration Missing: GH_PAT (GitHub Personal Access Token) is not set!")
        return False

    url = f"https://api.github.com/repos/{GH_REPO}/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Telegram-Dropbox-Webhook-Dispatcher",
        "Content-Type": "application/json",
    }
    payload = {
        "event_type": "telegram_sync",
        "client_payload": {
            "chat_id": chat_id,
            "message_id": message_id,
            "user_id": user_id,
            "has_media": has_media,
            "file_name": file_name,
            "text": text,
        }
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        if resp.status_code in (200, 204):
            logger.info(f"Successfully dispatched GitHub Actions workflow for repo '{GH_REPO}'.")
            return True
        else:
            logger.error(f"GitHub API Error [{resp.status_code}]: {resp.text}")
            return False
    except Exception as exc:
        logger.error(f"Network error while contacting GitHub API: {exc}")
        return False

# ---------------------------------------------------------------------------
# Request Handler
# ---------------------------------------------------------------------------
class WebhookHandler(BaseHTTPRequestHandler):
    """Processes incoming Telegram webhook notifications."""

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Health check and status endpoint."""
        if self.path in ("/", "/health", "/status"):
            self._send_json(200, {
                "status": "healthy",
                "service": "Telegram-Dropbox Webhook Dispatcher",
                "repo": GH_REPO,
                "auth_users_count": len(AUTHORIZED_USER_IDS),
                "pat_configured": bool(GH_PAT),
            })
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        """Receives and evaluates Telegram updates."""
        # Optional Secret Token Verification
        if TELEGRAM_SECRET_TOKEN:
            secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret != TELEGRAM_SECRET_TOKEN:
                logger.warning("Rejected webhook request: Invalid secret token.")
                self._send_json(403, {"error": "Unauthorized Secret Token"})
                return

        # Read JSON Body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty body"})
            return

        try:
            raw_body = self.rfile.read(content_length)
            update = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            logger.error(f"Failed to parse incoming JSON payload: {exc}")
            self._send_json(200, {"status": "parse_error"})
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            # Acknowledge non-message updates (e.g. callback queries, channel posts)
            self._send_json(200, {"status": "ignored_non_message"})
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user = message.get("from", {})
        user_id = user.get("id", 0)
        user_name = user.get("first_name", "User")
        message_id = message.get("message_id")

        # 1. Access Control
        if AUTHORIZED_USER_IDS and user_id not in AUTHORIZED_USER_IDS:
            logger.warning(f"Access denied for unauthorized user ID: {user_id}")
            denied_msg = (
                "🔒 **ACCESS RESTRICTED**\n"
                "──────────────────────────────\n"
                "You are not authorized to dispatch this cloud sync pipeline.\n"
                f"👤 **Your ID:** `{user_id}`"
            )
            send_telegram_message(chat_id, message_id, denied_msg)
            self._send_json(200, {"status": "unauthorized"})
            return

        # 2. Extract Media Metadata
        file_name = "Payload"
        file_size = 0
        has_media = False

        if "document" in message:
            has_media = True
            doc = message["document"]
            file_name = doc.get("file_name", f"document_{message_id}.bin")
            file_size = doc.get("file_size", 0)
        elif "video" in message:
            has_media = True
            vid = message["video"]
            file_name = vid.get("file_name", f"video_{message_id}.mp4")
            file_size = vid.get("file_size", 0)
        elif "audio" in message:
            has_media = True
            aud = message["audio"]
            file_name = aud.get("file_name", f"audio_{message_id}.mp3")
            file_size = aud.get("file_size", 0)
        elif "photo" in message:
            has_media = True
            photos = message["photo"]
            file_name = f"photo_{message_id}.jpg"
            if isinstance(photos, list) and photos:
                file_size = photos[-1].get("file_size", 0)
        elif "voice" in message:
            has_media = True
            file_name = f"voice_{message_id}.ogg"
            file_size = message["voice"].get("file_size", 0)
        elif "video_note" in message:
            has_media = True
            file_name = f"videonote_{message_id}.mp4"
            file_size = message["video_note"].get("file_size", 0)

        text = message.get("text", "") or message.get("caption", "")
        is_command = text.startswith("/")

        if not has_media and not is_command:
            # Plain conversation text - ignore without triggering CI
            self._send_json(200, {"status": "ignored_plain_text"})
            return

        # 3. Deliver Instant User Feedback
        if has_media:
            notice = (
                "⚡ **TRANSFER REQUEST RECEIVED**\n"
                "──────────────────────────────\n"
                f"📄 **Target:** `{file_name}`\n"
                f"📦 **Size:** `{format_size(file_size)}`\n"
                "🛰️ **Status:** *Dispatching GitHub Actions cloud runner...*\n"
                "⏳ *Sync engine will engage in ~25-30s.*"
            )
        else:
            cmd = text.split()[0]
            notice = (
                "🛰️ **COMMAND RECEIVED**\n"
                "──────────────────────────────\n"
                f"⌨️ **Command:** `{cmd}`\n"
                "⚡ *Waking up cloud engine to process request...*"
            )

        send_telegram_message(chat_id, message_id, notice)

        # 4. Trigger GitHub Actions Dispatch
        dispatched = dispatch_github_action(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            has_media=has_media,
            text=text,
            file_name=file_name
        )

        self._send_json(200, {
            "status": "ok",
            "dispatched": dispatched,
            "chat_id": chat_id,
            "message_id": message_id
        })

    def log_message(self, format, *args):
        """Silences default HTTP request logging to keep logs clean."""
        pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handles requests in a separate thread for concurrent throughput."""
    daemon_threads = True

# ---------------------------------------------------------------------------
# Server Entrypoint
# ---------------------------------------------------------------------------
def run_server():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadedHTTPServer(server_address, WebhookHandler)

    logger.info("┌" + "─" * 68 + "┐")
    logger.info("│ ⚡ TELEGRAM WEBHOOK DISPATCHER (DOCKER / STANDALONE GATEWAY)    │")
    logger.info("├" + "─" * 68 + "┤")
    logger.info(f"│ • Listening Address: http://0.0.0.0:{PORT:<45} │")
    logger.info(f"│ • GitHub Repository: {GH_REPO:<47} │")
    logger.info(f"│ • GitHub PAT Config: {'Configured ✅' if GH_PAT else 'Missing ❌':<47} │")
    logger.info(f"│ • Telegram Bot Token:{'Configured ✅' if TELEGRAM_BOT_TOKEN else 'Missing ❌':<47} │")
    logger.info(f"│ • Secret Token Auth: {'Enforced 🔒' if TELEGRAM_SECRET_TOKEN else 'Disabled (Open)':<47} │")
    logger.info(f"│ • Authorized Users:  {f'{len(AUTHORIZED_USER_IDS)} configured' if AUTHORIZED_USER_IDS else 'Public':<47} │")
    logger.info("└" + "─" * 68 + "┘")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down cleanly...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
