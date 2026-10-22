#!/usr/bin/env python3
"""
Telegram to Dropbox Auto-Sync Engine (Production MTProto Edition)
Author: Automated Cloud Solutions
Description: High-performance Telegram-to-Dropbox sync bot supporting files up to 2 GB,
             chunked cloud uploads, automatic FIFO folder retention, direct native
             clipboard copy buttons, and instant stop controls via Telegram /stop command.
"""

import os
import sys
import time
import signal
import asyncio
import logging
import tempfile
from typing import Tuple, List, Optional, Set

from telethon import TelegramClient, events, Button
from telethon.tl import types
import dropbox
from dropbox.files import WriteMode, CommitInfo, FileMetadata
from dropbox.exceptions import ApiError, AuthError, BadInputError, DropboxException

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO
)
logger = logging.getLogger("TelegramDropboxSync")

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

# Validate Telegram Environment
if not TELEGRAM_BOT_TOKEN:
    logger.critical("Configuration Error: Missing TELEGRAM_BOT_TOKEN.")
    sys.exit(1)

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    logger.critical("Configuration Error: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH (Get from https://my.telegram.org).")
    sys.exit(1)

# Validate Dropbox Environment
if not ((DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN) or DROPBOX_ACCESS_TOKEN):
    logger.critical("Configuration Error: Missing Dropbox OAuth credentials (Key, Secret, and Refresh Token).")
    sys.exit(1)

# Ensure Folder Syntax
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
# Dropbox Client Factory
# ---------------------------------------------------------------------------
def init_dropbox() -> dropbox.Dropbox:
    """Initializes and verifies the Dropbox connection."""
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
        logger.info(f"Authenticated Dropbox Account: {acc.name.display_name} ({acc.email})")
        return client
    except Exception as exc:
        logger.critical(f"Dropbox Authentication Failure: {exc}")
        sys.exit(1)

dbx = init_dropbox()

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def is_authorized(user_id: int) -> bool:
    """Validates if user ID has permission to invoke bot actions."""
    if not AUTHORIZED_USER_IDS:
        return True
    return user_id in AUTHORIZED_USER_IDS

def format_size(size_bytes: int) -> str:
    """Converts raw byte counts into human-readable formatted strings."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def render_progress_bar(percent: float, bar_length: int = 12) -> str:
    """Renders a clean visual block progress bar."""
    filled = int(round(bar_length * (percent / 100.0)))
    filled = max(0, min(bar_length, filled))
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {percent:.1f}%"

# ---------------------------------------------------------------------------
# Dropbox Operations: Upload, Retention & Shared Links
# ---------------------------------------------------------------------------
def enforce_folder_retention(folder_path: str, max_files: int = 2) -> List[str]:
    """
    Enforces FIFO file retention on the target Dropbox directory.
    If file count exceeds max_files, deletes the oldest files by server modification time.
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
            # Sort chronologically by server_modified ascending (oldest first)
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
    chunk_size_mb: int = 8
) -> Tuple[str, List[str]]:
    """
    Uploads file to Dropbox using streaming chunk sessions for efficiency.
    Returns (shared_url, deleted_files_list).
    """
    file_size = os.path.getsize(local_path)
    chunk_bytes = chunk_size_mb * 1024 * 1024

    with open(local_path, "rb") as stream:
        if file_size <= chunk_bytes:
            dbx.files_upload(stream.read(), dest_path, mode=WriteMode.overwrite)
        else:
            session_start = dbx.files_upload_session_start(stream.read(chunk_bytes))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=session_start.session_id,
                offset=stream.tell()
            )
            commit = CommitInfo(path=dest_path, mode=WriteMode.overwrite)

            while stream.tell() < file_size:
                remaining = file_size - stream.tell()
                if remaining <= chunk_bytes:
                    dbx.files_upload_session_finish(stream.read(chunk_bytes), cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(stream.read(chunk_bytes), cursor)
                    cursor.offset = stream.tell()

    logger.info(f"Successfully committed file to Dropbox: {dest_path}")

    # Enforce retention policy (keep only the newest N files)
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
        logger.warning(f"Shared link generation skipped (scope or permission limit): {exc}")

    return shared_link, pruned_files

# ---------------------------------------------------------------------------
# Telethon Client Initialization
# ---------------------------------------------------------------------------
client = TelegramClient("bot_session", int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
shutdown_event = asyncio.Event()

# ---------------------------------------------------------------------------
# Primary Message & Media Ingestion Handler
# ---------------------------------------------------------------------------
@client.on(events.NewMessage)
async def handle_incoming_message(event):
    """Primary handler for direct messages, media ingestion, and remote controls."""
    if not event.is_private:
        return

    sender = await event.get_sender()
    user_id = sender.id if sender else 0

    # Authorization Check
    if not is_authorized(user_id):
        await event.reply(
            "⛔ **Access Denied**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "You are not authorized to use this sync service.\n"
            f"👤 **Your Telegram ID:** `{user_id}`"
        )
        return

    # Command: /stop or /shutdown (Instantly kills the GitHub Action runner)
    if event.raw_text in ["/stop", "/shutdown", "/kill"]:
        elapsed = int(time.time() - START_TIMESTAMP)
        await event.reply(
            "🛑 **STOPPING GITHUB ACTIONS RUNNER**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ **Session Uptime:** `{elapsed // 60}m {elapsed % 60}s`\n"
            "✅ Daemon disconnecting and terminating runner cleanly with exit code 0."
        )
        logger.info(f"Stop command received from authorized user {user_id}. Terminating...")
        shutdown_event.set()
        await client.disconnect()
        return

    # Command: /status (Health and current Dropbox inventory)
    if event.raw_text in ["/status", "/info"]:
        elapsed = int(time.time() - START_TIMESTAMP)
        file_count = 0
        try:
            res = dbx.files_list_folder(DROPBOX_TARGET_FOLDER)
            file_count = len([e for e in res.entries if isinstance(e, FileMetadata)])
        except Exception:
            pass

        status_msg = (
            "📊 **RUNNER STATUS & HEALTH**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 **State:** Online & Listening\n"
            f"⏱️ **Uptime:** `{elapsed // 60}m {elapsed % 60}s` / `{MAX_RUN_TIME_MINUTES}m`\n"
            f"📁 **Dropbox Target:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"📦 **Current Files:** `{file_count}` / `{MAX_FILES_IN_FOLDER}` (Retention cap)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Send /stop anytime to shut down the GitHub Action runner.*"
        )
        await event.reply(status_msg)
        return

    # Command: /start or /help
    if event.raw_text in ["/start", "/help"]:
        status_label = "Authorized" if is_authorized(user_id) else "Unauthorized"
        help_card = (
            "🚀 **Cloud Sync Bot (Enterprise MTProto)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **User ID:** `{user_id}` ({status_label})\n"
            f"📁 **Destination:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"📦 **Folder Capacity:** Max `{MAX_FILES_IN_FOLDER}` files (Oldest auto-rotated)\n"
            "⚡ **Max Transfer Size:** `2,000 MB (2 GB)`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📥 **Commands & Usage:**\n"
            "• Send any document, IPA, video, or archive to sync to Dropbox.\n"
            "• Click `[ 📋 Copy Link ]` to copy the link directly to your clipboard.\n"
            "• `/status` - View runner uptime and Dropbox file count.\n"
            "• `/stop` - Instantly stop the GitHub Actions runner."
        )
        await event.reply(help_card)
        return

    # Check for Media
    if not event.message.media:
        return

    # Extract Metadata
    file_size = event.message.file.size if event.message.file else 0
    filename = (
        event.message.file.name
        if event.message.file and event.message.file.name
        else f"telegram_payload_{event.message.id}.bin"
    )
    formatted_total_size = format_size(file_size)

    # Initial Dispatch Message
    status_card = (
        "⏳ **INGESTING MEDIA STREAM**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 **File:** `{filename}`\n"
        f"📦 **Size:** `{formatted_total_size}`\n"
        "🔄 **Status:** Initializing MTProto download..."
    )
    status_msg = await event.reply(status_card)

    tmp_dir = tempfile.gettempdir()
    local_target = os.path.join(tmp_dir, f"{int(time.time())}_{filename}")

    last_update_ts = [0.0]
    start_time = time.time()

    async def progress_hook(current_bytes: int, total_bytes: int):
        """Throttled progress updater to maintain responsive UI while avoiding FloodWait."""
        now = time.time()
        if now - last_update_ts[0] > 3.5:
            pct = (current_bytes / total_bytes) * 100.0 if total_bytes > 0 else 0.0
            elapsed = now - start_time
            speed = current_bytes / elapsed if elapsed > 0 else 0
            card = (
                "📥 **RECEIVING PAYLOAD (Telegram)**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📄 **File:** `{filename}`\n"
                f"📦 **Volume:** `{format_size(current_bytes)}` / `{formatted_total_size}`\n"
                f"⚡ **Speed:** `{format_size(int(speed))}/s`\n"
                f"📊 **Progress:** `{render_progress_bar(pct)}`"
            )
            try:
                await status_msg.edit(card)
                last_update_ts[0] = now
            except Exception:
                pass

    try:
        # Step 1: MTProto Download
        await client.download_media(
            event.message,
            file=local_target,
            progress_callback=progress_hook
        )
        download_duration = time.time() - start_time

        # Step 2: Upload Status Card
        await status_msg.edit(
            "☁️ **SYNCHRONIZING WITH DROPBOX**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 **File:** `{filename}`\n"
            f"📦 **Size:** `{formatted_total_size}`\n"
            f"⏱️ **Download Time:** `{download_duration:.1f}s`\n"
            "🔄 **Status:** Streaming chunked sessions & checking retention..."
        )

        dropbox_target_path = f"{DROPBOX_TARGET_FOLDER.rstrip('/')}/{filename}"

        # Step 3: Dropbox Upload Execution
        loop = asyncio.get_event_loop()
        upload_start = time.time()
        shared_url, pruned_items = await loop.run_in_executor(
            None,
            execute_dropbox_upload,
            local_target,
            dropbox_target_path,
            DROPBOX_TARGET_FOLDER,
            CHUNK_SIZE_MB
        )
        total_duration = time.time() - start_time

        # Step 4: Final Presentation Card
        completion_card = (
            "✅ **UPLOAD COMPLETED**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 **File:** `{filename}`\n"
            f"📦 **Size:** `{formatted_total_size}`\n"
            f"📁 **Destination:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"⏱️ **Total Elapsed:** `{total_duration:.1f}s`\n"
        )

        if pruned_items:
            pruned_str = ", ".join([f"`{name}`" for name in pruned_items])
            completion_card += f"\n🗑️ **Retention (Max {MAX_FILES_IN_FOLDER}):** Rotated out {pruned_str}\n"

        buttons = None
        if shared_url:
            completion_card += f"\n🔗 **Direct Link:**\n`{shared_url}`"

            # DIRECT CLIPBOARD BUTTON:
            # Uses Telegram's native KeyboardButtonCopy (Bot API CopyTextButton).
            # When tapped, the Telegram client directly copies the URL to the OS clipboard!
            try:
                copy_button = types.KeyboardButtonCopy(text="📋 Copy Link", copy_text=shared_url)
                open_button = types.KeyboardButtonUrl(text="🌐 Open in Dropbox", url=shared_url)
                buttons = types.ReplyInlineMarkup(
                    rows=[types.KeyboardButtonRow(buttons=[copy_button, open_button])]
                )
            except Exception as btn_err:
                logger.warning(f"Fallback button creation: {btn_err}")
                buttons = [[Button.url("🌐 Open in Dropbox", shared_url)]]
        else:
            completion_card += "\nℹ️ *Payload secured in Dropbox.*"

        await status_msg.edit(
            completion_card,
            buttons=buttons,
            link_preview=False
        )
        logger.info(f"Sync complete: '{filename}' ({formatted_total_size}) in {total_duration:.1f}s")

    except Exception as exc:
        logger.error(f"Pipeline Failure for '{filename}': {exc}", exc_info=True)
        failure_card = (
            "❌ **TRANSFER FAILED**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 **Target:** `{filename}`\n"
            f"⚠️ **Error Details:** `{str(exc)}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Please verify runner credentials and cloud storage quota."
        )
        await status_msg.edit(failure_card)
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
    logger.info("=" * 60)
    logger.info(f"TELEGRAM ➔ DROPBOX SYNC ACTIVE (@{me.username})")
    logger.info(f"Target Directory: {DROPBOX_TARGET_FOLDER} (Retention: {MAX_FILES_IN_FOLDER} files)")
    logger.info(f"Session Window: {MAX_RUN_TIME_MINUTES} minutes")
    logger.info("Direct clipboard button active: types.KeyboardButtonCopy")
    logger.info("=" * 60)

    async def lifecycle_timeout():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=MAX_RUN_TIME_MINUTES * 60)
        except asyncio.TimeoutError:
            logger.info(f"Execution window reached ({MAX_RUN_TIME_MINUTES} min). Cycling runner...")
            await client.disconnect()

    timeout_task = asyncio.create_task(lifecycle_timeout())

    try:
        await client.run_until_disconnected()
    finally:
        timeout_task.cancel()
        logger.info("Sync service stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(run_daemon())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.error(f"Terminated with error: {e}")
    sys.exit(0)