#!/usr/bin/env python3
"""
Telegram to Dropbox Auto-Sync Engine (Production MTProto Edition)
Author: Automated Cloud Solutions
Description: High-performance Telegram-to-Dropbox sync bot supporting files up to 2 GB,
             chunked cloud uploads with live progress updates, automatic FIFO folder
             retention, one-tap native CopyTextButton, and instant /stop controls.
"""

import os
import sys
import time
import signal
import asyncio
import logging
import tempfile
import requests
from typing import Tuple, List, Optional, Set

from telethon import TelegramClient, events, Button
from telethon.tl import types
from telethon.errors import MessageNotModifiedError, FloodWaitError
import dropbox
from dropbox.files import WriteMode, CommitInfo, FileMetadata
from dropbox.exceptions import ApiError, AuthError, BadInputError, DropboxException

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)

class ProfessionalFormatter(logging.Formatter):
    """High-visibility structured log formatter for cloud runners."""
    def format(self, record):
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        lvl = record.levelname.ljust(8)
        return f"{ts} │ {lvl} │ {record.name}: {record.getMessage()}"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ProfessionalFormatter())
logging.root.setLevel(LOG_LEVEL)
logging.root.handlers = [handler]

logger = logging.getLogger("SyncEngine")

# ---------------------------------------------------------------------------
# Configuration & Credentials
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
DROPBOX_TARGET_FOLDER = os.getenv("DROPBOX_TARGET_FOLDER", "/Telegram_Uploads").strip()

AUTHORIZED_USER_IDS_RAW = os.getenv("AUTHORIZED_USER_IDS", "").strip()
MAX_RUN_TIME_MINUTES = int(os.getenv("MAX_RUN_TIME_MINUTES", "340"))
MAX_FILES_IN_FOLDER = int(os.getenv("MAX_FILES_IN_FOLDER", "2"))
CHUNK_SIZE_MB = int(os.getenv("CHUNK_SIZE_MB", "8"))

START_TIMESTAMP = time.time()
SESSION_TRANSFERS_COUNT = 0
SESSION_TRANSFERS_BYTES = 0

# Validate Telegram Environment
if not TELEGRAM_BOT_TOKEN:
    logger.critical("Configuration Error: Missing TELEGRAM_BOT_TOKEN secret.")
    sys.exit(1)

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    logger.critical("Configuration Error: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH (Obtain from https://my.telegram.org).")
    sys.exit(1)

# Validate Dropbox Environment
if not ((DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN) or DROPBOX_ACCESS_TOKEN):
    logger.critical("Configuration Error: Missing Dropbox OAuth credentials (Key, Secret, and Refresh Token).")
    sys.exit(1)

# Ensure Target Folder Syntax
if not DROPBOX_TARGET_FOLDER.startswith("/"):
    DROPBOX_TARGET_FOLDER = "/" + DROPBOX_TARGET_FOLDER

# Parse Authorized Users
AUTHORIZED_USER_IDS: Set[int] = set()
if AUTHORIZED_USER_IDS_RAW:
    for item in AUTHORIZED_USER_IDS_RAW.split(","):
        item = item.strip()
        if item.isdigit():
            AUTHORIZED_USER_IDS.add(int(item))

# ---------------------------------------------------------------------------
# Dropbox Client Initialization
# ---------------------------------------------------------------------------
DBX_ACCOUNT_NAME = "Connected Cloud Account"
DBX_ACCOUNT_EMAIL = ""

def init_dropbox() -> dropbox.Dropbox:
    """Initializes and verifies the Dropbox connection."""
    global DBX_ACCOUNT_NAME, DBX_ACCOUNT_EMAIL
    if DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY and DROPBOX_APP_SECRET:
        client = dropbox.Dropbox(
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN
        )
    else:
        client = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

    try:
        acc = client.users_get_current_account()
        DBX_ACCOUNT_NAME = acc.name.display_name
        DBX_ACCOUNT_EMAIL = acc.email
        logger.info(f"Authenticated Dropbox Account: {DBX_ACCOUNT_NAME} ({DBX_ACCOUNT_EMAIL})")
        return client
    except Exception as exc:
        logger.critical(f"Dropbox Authentication Failure: {exc}")
        sys.exit(1)

dbx = init_dropbox()

# ---------------------------------------------------------------------------
# Formatting & Metric Utilities
# ---------------------------------------------------------------------------
def is_authorized(user_id: int) -> bool:
    """Validates if user ID has permission to invoke bot actions."""
    if not AUTHORIZED_USER_IDS:
        return True
    return user_id in AUTHORIZED_USER_IDS

def format_size(size_bytes: int) -> str:
    """Converts raw byte counts into clean human-readable formatted strings."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def format_eta(seconds: float) -> str:
    """Converts duration in seconds into human-readable ETA."""
    if seconds < 0 or seconds > 86400:
        return "Calculating..."
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60}s"
    else:
        return f"{s // 3600}h {(s % 3600) // 60}m"

def render_progress_bar(percent: float, bar_length: int = 12) -> str:
    """Renders a sleek visual block progress bar."""
    filled = int(round(bar_length * (percent / 100.0)))
    filled = max(0, min(bar_length, filled))
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {percent:.1f}%"

def sanitize_filename(name: str) -> str:
    """Sanitizes filename for cross-platform cloud storage safety."""
    clean = "".join(c for c in name if c not in '\\:*?"<>|').strip()
    return clean if clean else f"payload_{int(time.time())}.bin"

async def safe_edit_message(msg, text: str, buttons=None, link_preview: bool = False):
    """Safely edits message with error suppression for unchanged text or rate limits."""
    try:
        await msg.edit(text, buttons=buttons, link_preview=link_preview)
    except MessageNotModifiedError:
        pass
    except FloodWaitError as e:
        logger.warning(f"Telegram FloodWait hit ({e.seconds}s) during message edit.")
    except Exception as exc:
        logger.debug(f"Non-critical error editing message: {exc}")

def apply_native_copy_buttons(chat_id: int, message_id: int, shared_url: str) -> bool:
    """
    Applies Telegram's official client-side CopyTextButton via HTTP Bot API.
    When tapped, the Telegram app directly copies shared_url into the OS clipboard.
    No extra messages or callback spinners are produced.
    """
    api_endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "📋 Copy Direct Link",
                        "copy_text": {
                            "text": shared_url
                        }
                    },
                    {
                        "text": "🌐 Open in Dropbox",
                        "url": shared_url
                    }
                ]
            ]
        }
    }
    try:
        resp = requests.post(api_endpoint, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Direct CopyTextButton successfully attached via Telegram Bot API.")
            return True
        else:
            logger.warning(f"Telegram Bot API rejected CopyTextButton ({resp.status_code}): {resp.text}")
            return False
    except Exception as exc:
        logger.error(f"Error calling Telegram Bot API for CopyTextButton: {exc}")
        return False

# ---------------------------------------------------------------------------
# Dropbox Operations: Upload, Retention & Shared Links
# ---------------------------------------------------------------------------
def enforce_folder_retention(folder_path: str, max_files: int = 2) -> List[str]:
    """
    Enforces FIFO file retention on the target Dropbox directory.
    If file count exceeds max_files, deletes oldest files by server modification time.
    """
    deleted_files = []
    try:
        files: List[FileMetadata] = []
        result = dbx.files_list_folder(folder_path)
        while True:
            for entry in result.entries:
                if isinstance(entry, FileMetadata):
                    files.append(entry)
            if not result.has_more:
                break
            result = dbx.files_list_folder_continue(result.cursor)

        if len(files) > max_files:
            files.sort(key=lambda item: item.server_modified)
            overflow_count = len(files) - max_files
            for old_file in files[:overflow_count]:
                try:
                    dbx.files_delete_v2(old_file.path_lower)
                    deleted_files.append(old_file.name)
                    logger.info(f"Retention Policy: Pruned oldest file '{old_file.name}' from {folder_path}")
                except Exception as del_err:
                    logger.error(f"Failed to prune '{old_file.name}': {del_err}")

    except ApiError as api_err:
        logger.warning(f"Retention scan skipped for '{folder_path}': {api_err}")
    except Exception as exc:
        logger.error(f"Unexpected error during retention enforcement: {exc}")

    return deleted_files

def execute_dropbox_upload(
    local_path: str,
    dest_path: str,
    target_folder: str,
    chunk_size_mb: int = 8,
    progress_callback = None
) -> Tuple[str, List[str]]:
    """
    Uploads file to Dropbox using streaming chunk sessions for maximum reliability.
    Dispatches progress_callback(uploaded_bytes, total_bytes) on each chunk.
    Returns (shared_url, deleted_files_list).
    """
    file_size = os.path.getsize(local_path)
    chunk_bytes = chunk_size_mb * 1024 * 1024

    with open(local_path, "rb") as stream:
        if file_size <= chunk_bytes:
            dbx.files_upload(stream.read(), dest_path, mode=WriteMode.overwrite)
            if progress_callback:
                progress_callback(file_size, file_size)
        else:
            session_start = dbx.files_upload_session_start(stream.read(chunk_bytes))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=session_start.session_id,
                offset=stream.tell()
            )
            commit = CommitInfo(path=dest_path, mode=WriteMode.overwrite)

            if progress_callback:
                progress_callback(stream.tell(), file_size)

            while stream.tell() < file_size:
                remaining = file_size - stream.tell()
                if remaining <= chunk_bytes:
                    dbx.files_upload_session_finish(stream.read(chunk_bytes), cursor, commit)
                    if progress_callback:
                        progress_callback(file_size, file_size)
                else:
                    dbx.files_upload_session_append_v2(stream.read(chunk_bytes), cursor)
                    cursor.offset = stream.tell()
                    if progress_callback:
                        progress_callback(stream.tell(), file_size)

    logger.info(f"Successfully committed file to Dropbox: {dest_path}")

    # Enforce retention policy (keep newest N files)
    pruned_files = enforce_folder_retention(target_folder, max_files=MAX_FILES_IN_FOLDER)

    # Generate or fetch existing shared link safely
    shared_link = ""
    try:
        metadata = dbx.sharing_create_shared_link_with_settings(dest_path)
        shared_link = metadata.url
    except ApiError as err:
        if err.error.is_shared_link_already_exists():
            try:
                existing = dbx.sharing_list_shared_links(path=dest_path, direct_only=True).links
                if existing:
                    shared_link = existing[0].url
            except Exception:
                pass
        else:
            logger.warning(f"Shared link generation failed (ApiError): {err}")
    except (BadInputError, DropboxException, Exception) as exc:
        logger.warning(f"Shared link generation skipped: {exc}")

    return shared_link, pruned_files

# ---------------------------------------------------------------------------
# Telethon Client Initialization
# ---------------------------------------------------------------------------
client = TelegramClient("bot_session", int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
shutdown_event = asyncio.Event()
BOT_USERNAME = "Unknown"

# ---------------------------------------------------------------------------
# Primary Message & Media Ingestion Handler
# ---------------------------------------------------------------------------
@client.on(events.NewMessage)
async def handle_incoming_message(event):
    """Primary handler for direct messages, media ingestion, and remote controls."""
    global SESSION_TRANSFERS_COUNT, SESSION_TRANSFERS_BYTES
    if not event.is_private:
        return

    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    sender_name = getattr(sender, "first_name", "Authorized User") or "Authorized User"

    # Authorization Check
    if not is_authorized(user_id):
        denied_card = (
            "🔒 **ACCESS RESTRICTED**\n"
            "──────────────────────────────\n"
            "You are not authorized to access this sync pipeline.\n\n"
            f"👤 **Your Telegram ID:** `{user_id}`\n"
            "⚠️ **Policy:** Unauthorized requests and payloads are discarded.\n"
            "──────────────────────────────\n"
            "💡 *To authorize, add your Telegram ID to `AUTHORIZED_USER_IDS` in GitHub Secrets.*"
        )
        await event.reply(denied_card)
        logger.warning(f"Unauthorized access attempt from user_id: {user_id}")
        return

    # Command: /stop, /shutdown, /kill (Gracefully stops the runner)
    if event.raw_text in ["/stop", "/shutdown", "/kill"]:
        elapsed = int(time.time() - START_TIMESTAMP)
        stop_card = (
            "🛑 **RUNNER SHUTDOWN INITIATED**\n"
            "──────────────────────────────\n"
            f"⏱️ **Session Duration:** `{format_eta(elapsed)}`\n"
            f"📦 **Transfers Completed:** `{SESSION_TRANSFERS_COUNT} files` (`{format_size(SESSION_TRANSFERS_BYTES)}`)\n"
            f"👤 **Requested By:** {sender_name} (`{user_id}`)\n"
            "──────────────────────────────\n"
            "✅ Daemon disconnecting and terminating GitHub Actions runner with Exit Code 0."
        )
        await event.reply(stop_card)
        logger.info(f"Stop command received from user {user_id} ({sender_name}). Terminating...")
        shutdown_event.set()
        await client.disconnect()
        return

    # Command: /ping (Measures gateway round-trip latency)
    if event.raw_text in ["/ping"]:
        t0 = time.time()
        sent = await event.reply("⚡ `Pinging host runner...`")
        latency_ms = max(1, int((time.time() - t0) * 1000))
        ping_card = (
            "⚡ **GATEWAY PONG**\n"
            "──────────────────────────────\n"
            f"⏱️ **Round-Trip Latency:** `{latency_ms} ms`\n"
            "🛰️ **Compute Host:** `GitHub Actions CI Runner`\n"
            "🟢 **Engine Health:** `Operational (100%)`\n"
            f"🤖 **Bot Client:** `@{BOT_USERNAME}`"
        )
        await safe_edit_message(sent, ping_card)
        return

    # Command: /status, /info (Real-time system & cloud storage status)
    if event.raw_text in ["/status", "/info"]:
        elapsed = int(time.time() - START_TIMESTAMP)
        remaining_secs = max(0, (MAX_RUN_TIME_MINUTES * 60) - elapsed)

        # Dropbox Folder File Count
        file_count_display = "Scanning..."
        try:
            res = dbx.files_list_folder(DROPBOX_TARGET_FOLDER)
            count = len([e for e in res.entries if isinstance(e, FileMetadata)])
            file_count_display = f"`{count}` / `{MAX_FILES_IN_FOLDER}` (Retention cap)"
        except Exception:
            file_count_display = f"`{MAX_FILES_IN_FOLDER} max` (Retention cap)"

        # Dropbox Space Usage
        space_str = None
        try:
            usage = dbx.users_get_space_usage()
            used_b = usage.used
            if usage.allocation.is_individual():
                alloc_b = usage.allocation.get_individual().allocated
                pct = (used_b / alloc_b * 100.0) if alloc_b > 0 else 0
                space_str = f"`{format_size(used_b)}` / `{format_size(alloc_b)}` ({pct:.1f}%)"
            elif usage.allocation.is_team():
                alloc_b = usage.allocation.get_team().allocated
                pct = (used_b / alloc_b * 100.0) if alloc_b > 0 else 0
                space_str = f"`{format_size(used_b)}` / `{format_size(alloc_b)}` ({pct:.1f}%)"
        except Exception:
            pass

        account_display = DBX_ACCOUNT_NAME
        if DBX_ACCOUNT_EMAIL:
            account_display += f" (`{DBX_ACCOUNT_EMAIL}`)"

        status_card = (
            "📊 **SYSTEM & CLOUD HEALTH MONITOR**\n"
            "──────────────────────────────\n"
            "🟢 **Daemon State:** `Online & Operational`\n"
            f"⏱️ **Session Uptime:** `{format_eta(elapsed)}` / `{MAX_RUN_TIME_MINUTES}m`\n"
            f"⏳ **Window Remaining:** `{format_eta(remaining_secs)}`\n\n"
            "☁️ **Dropbox Cloud Storage**\n"
            f"• **Account:** {account_display}\n"
            f"• **Target Vault:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"• **File Count:** {file_count_display}\n"
        )
        if space_str:
            status_card += f"• **Cloud Quota:** {space_str}\n"

        status_card += (
            f"\n📈 **Session Sync Volume**\n"
            f"• **Transferred:** `{SESSION_TRANSFERS_COUNT} files` (`{format_size(SESSION_TRANSFERS_BYTES)}`)\n"
            "──────────────────────────────\n"
            "💡 *Send /stop anytime to safely terminate runner before scheduled cycle.*"
        )
        await event.reply(status_card)
        return

    # Command: /start, /help (Operational manual)
    if event.raw_text in ["/start", "/help"]:
        status_label = "Authorized ✅" if is_authorized(user_id) else "Unauthorized ❌"
        help_card = (
            "⚡ **TELEGRAM TO DROPBOX SYNC ENGINE**\n"
            "──────────────────────────────\n"
            f"👤 **Requester:** `{user_id}` ({status_label})\n"
            f"📁 **Destination:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"📦 **Folder Retention:** `{MAX_FILES_IN_FOLDER} files` (FIFO Auto-rotated)\n"
            "⚡ **Max Transfer Size:** `2,000 MB (2.0 GB)`\n"
            "──────────────────────────────\n"
            "📥 **Operational Commands:**\n"
            "• `/status` — View real-time runner uptime, file quota & health\n"
            "• `/ping` — Measure network round-trip latency\n"
            "• `/stop` — Gracefully terminate active GitHub Actions runner\n"
            "• `/help` — Display this command guide\n"
            "──────────────────────────────\n"
            "💡 **Quick Transfer:** Simply forward or upload any document, video, or archive. "
            "You will receive live download and upload progress, followed by a one-tap direct copy button."
        )
        await event.reply(help_card)
        return

    # Check for Media Attachment
    if not event.message.media:
        return

    # Extract Metadata
    file_size = event.message.file.size if event.message.file else 0
    raw_name = (
        event.message.file.name
        if event.message.file and event.message.file.name
        else f"payload_{event.message.id}.bin"
    )
    filename = sanitize_filename(raw_name)
    formatted_total_size = format_size(file_size)

    # Initial Dispatch Message
    init_card = (
        "⏳ **INGESTING PAYLOAD**\n"
        "──────────────────────────────\n"
        f"📄 **Filename:** `{filename}`\n"
        f"📦 **Filesize:** `{formatted_total_size}`\n"
        "⚡ **Status:** Connecting to Telegram..."
    )
    status_msg = await event.reply(init_card)

    tmp_dir = tempfile.gettempdir()
    local_target = os.path.join(tmp_dir, f"{int(time.time())}_{filename}")

    last_dl_update_ts = [0.0]
    dl_start_time = time.time()

    async def download_progress_hook(current_bytes: int, total_bytes: int):
        """Throttled progress updater for MTProto download phase."""
        now = time.time()
        if (now - last_dl_update_ts[0] > 3.5) or (current_bytes >= total_bytes):
            last_dl_update_ts[0] = now
            pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
            elapsed = now - dl_start_time
            speed = current_bytes / elapsed if elapsed > 0 else 0
            remaining_bytes = max(0, total_bytes - current_bytes)
            eta = (remaining_bytes / speed) if speed > 0 else 0

            card = (
                "⬇️ **DOWNLOADING FROM TELEGRAM**\n"
                "──────────────────────────────\n"
                f"📄 **Filename:** `{filename}`\n"
                f"📦 **Received:** `{format_size(current_bytes)}` / `{formatted_total_size}`\n"
                f"⚡ **Speed:** `{format_size(int(speed))}/s`  •  ⏳ **ETA:** `{format_eta(eta)}`\n"
                f"📊 **Progress:** `{render_progress_bar(pct)}`"
            )
            await safe_edit_message(status_msg, card)

    try:
        # Step 1: MTProto Download
        await client.download_media(
            event.message,
            file=local_target,
            progress_callback=download_progress_hook
        )
        download_duration = max(0.1, time.time() - dl_start_time)

        # Step 2: Initialize Dropbox Upload Card
        await safe_edit_message(
            status_msg,
            "☁️ **STREAMING TO DROPBOX**\n"
            "──────────────────────────────\n"
            f"📄 **Filename:** `{filename}`\n"
            f"📦 **Filesize:** `{formatted_total_size}`\n"
            f"⏱️ **Ingest Time:** `{download_duration:.1f}s`\n"
            "⚡ **Status:** Initializing cloud transfer..."
        )

        dropbox_target_path = f"{DROPBOX_TARGET_FOLDER.rstrip('/')}/{filename}"
        loop = asyncio.get_running_loop()
        upload_start_time = time.time()
        last_ul_update_ts = [0.0]

        def dropbox_progress_hook(current_bytes: int, total_bytes: int):
            """Thread-safe progress callback during chunked Dropbox upload."""
            now = time.time()
            if (now - last_ul_update_ts[0] > 3.5) or (current_bytes >= total_bytes):
                last_ul_update_ts[0] = now
                pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                elapsed = now - upload_start_time
                speed = current_bytes / elapsed if elapsed > 0 else 0
                remaining_bytes = max(0, total_bytes - current_bytes)
                eta = (remaining_bytes / speed) if speed > 0 else 0

                card = (
                    "☁️ **STREAMING TO DROPBOX**\n"
                    "──────────────────────────────\n"
                    f"📄 **Filename:** `{filename}`\n"
                    f"📦 **Uploaded:** `{format_size(current_bytes)}` / `{formatted_total_size}`\n"
                    f"⚡ **Speed:** `{format_size(int(speed))}/s`  •  ⏳ **ETA:** `{format_eta(eta)}`\n"
                    f"📊 **Progress:** `{render_progress_bar(pct)}`"
                )
                asyncio.run_coroutine_threadsafe(
                    safe_edit_message(status_msg, card),
                    loop
                )

        # Step 3: Dropbox Upload Execution
        shared_url, pruned_items = await loop.run_in_executor(
            None,
            execute_dropbox_upload,
            local_target,
            dropbox_target_path,
            DROPBOX_TARGET_FOLDER,
            CHUNK_SIZE_MB,
            dropbox_progress_hook
        )
        upload_duration = max(0.1, time.time() - upload_start_time)
        total_duration = time.time() - dl_start_time

        dl_speed = file_size / download_duration if download_duration > 0 else 0
        ul_speed = file_size / upload_duration if upload_duration > 0 else 0

        # Step 4: Final Presentation Card
        completion_card = (
            "✅ **TRANSFER COMPLETE**\n"
            "──────────────────────────────\n"
            f"📄 **Filename:** `{filename}`\n"
            f"📦 **Payload Size:** `{formatted_total_size}`\n"
            f"📂 **Cloud Vault:** `{DROPBOX_TARGET_FOLDER}`\n\n"
            "⏱️ **Performance Metrics**\n"
            f"• ⬇️ **Telegram Ingest:** `{download_duration:.1f}s` (`{format_size(int(dl_speed))}/s`)\n"
            f"• ☁️ **Dropbox Push:** `{upload_duration:.1f}s` (`{format_size(int(ul_speed))}/s`)\n"
            f"• ⏱️ **Total Elapsed:** `{total_duration:.1f}s`\n"
        )

        if pruned_items:
            pruned_str = ", ".join([f"`{name}`" for name in pruned_items])
            completion_card += (
                f"\n♻️ **Retention Auto-Rotation (Cap: {MAX_FILES_IN_FOLDER})**\n"
                f"• Pruned oldest: {pruned_str}\n"
            )

        if shared_url:
            # Edit text first with base Open in Dropbox button
            await safe_edit_message(
                status_msg,
                completion_card,
                buttons=[[Button.url("🌐 Open in Dropbox", shared_url)]],
                link_preview=False
            )

            # Attach official client-side CopyTextButton via Telegram Bot API
            # This directly attaches [ 📋 Copy Direct Link ] next to [ 🌐 Open in Dropbox ]
            applied = await loop.run_in_executor(
                None,
                apply_native_copy_buttons,
                event.chat_id,
                status_msg.id,
                shared_url
            )
            if not applied:
                logger.info("Retained standard URL button fallback.")
        else:
            completion_card += "\nℹ️ *Payload securely archived in Dropbox vault.*"
            await safe_edit_message(
                status_msg,
                completion_card,
                buttons=None,
                link_preview=False
            )

        # Update Session Metrics
        SESSION_TRANSFERS_COUNT += 1
        SESSION_TRANSFERS_BYTES += file_size
        logger.info(f"Sync complete: '{filename}' ({formatted_total_size}) in {total_duration:.1f}s")

    except Exception as exc:
        logger.error(f"Pipeline Failure for '{filename}': {exc}", exc_info=True)
        failure_card = (
            "❌ **TRANSFER FAILED**\n"
            "──────────────────────────────\n"
            f"📄 **Target File:** `{filename}`\n"
            f"📦 **Payload Size:** `{formatted_total_size}`\n"
            f"⚠️ **Error Details:** `{str(exc)}`\n"
            "──────────────────────────────\n"
            "💡 *Verify runner credentials, cloud quota, or retry with smaller files.*"
        )
        await safe_edit_message(status_msg, failure_card)
    finally:
        if os.path.exists(local_target):
            try:
                os.remove(local_target)
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Runner Entrypoint with Fast Signal Handlers and Timeout
# ---------------------------------------------------------------------------
async def run_daemon():
    """Starts the client daemon with fast signal handling and CI timeouts."""
    global BOT_USERNAME
    loop = asyncio.get_running_loop()

    def instant_signal_exit():
        logger.info("Signal received (SIGTERM/SIGINT). Initiating immediate disconnect...")
        shutdown_event.set()
        asyncio.create_task(client.disconnect())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, instant_signal_exit)
        except (NotImplementedError, RuntimeError):
            pass

    await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    me = await client.get_me()
    BOT_USERNAME = me.username or "Bot"

    auth_summary = (
        f"{len(AUTHORIZED_USER_IDS)} configured user(s)"
        if AUTHORIZED_USER_IDS
        else "Public (All users permitted)"
    )

    logger.info("┌" + "─" * 68 + "┐")
    logger.info("│ ⚡ TELEGRAM TO DROPBOX SYNC PIPELINE (ENTERPRISE MTPROTO)       │")
    logger.info("├" + "─" * 68 + "┤")
    logger.info(f"│ • Telegram Bot:      @{BOT_USERNAME:<46} │")
    logger.info(f"│ • Dropbox Account:   {DBX_ACCOUNT_NAME:<46} │")
    logger.info(f"│ • Target Directory:  {DROPBOX_TARGET_FOLDER:<46} │")
    logger.info(f"│ • FIFO Retention:    {MAX_FILES_IN_FOLDER} files maximum{' ':<31} │")
    logger.info(f"│ • Chunk Streaming:   {CHUNK_SIZE_MB} MB chunks{' ':<34} │")
    logger.info(f"│ • Session Window:    {MAX_RUN_TIME_MINUTES} minutes{' ':<33} │")
    logger.info(f"│ • Access Control:    {auth_summary:<46} │")
    logger.info(f"│ • Direct Copy API:   Armed (Telegram Bot API v7.0+){' ':<17} │")
    logger.info("└" + "─" * 68 + "┘")

    async def lifecycle_timeout():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=MAX_RUN_TIME_MINUTES * 60)
        except asyncio.TimeoutError:
            logger.info(f"Execution window reached ({MAX_RUN_TIME_MINUTES} min). Cycling runner cleanly...")
            await client.disconnect()

    timeout_task = asyncio.create_task(lifecycle_timeout())

    try:
        await client.run_until_disconnected()
    finally:
        timeout_task.cancel()
        logger.info("Sync engine stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(run_daemon())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.error(f"Terminated with error: {e}")
    sys.exit(0)