import os
import sys
import time
import asyncio
import logging
import tempfile
from telethon import TelegramClient, events
import dropbox
from dropbox.files import WriteMode, CommitInfo
from dropbox.exceptions import ApiError, AuthError

# Configure logging
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Credentials from environment variables
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

# Validate Telegram credentials
if not TELEGRAM_BOT_TOKEN:
    logger.error("Missing TELEGRAM_BOT_TOKEN.")
    sys.exit(1)

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    logger.error("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH. Get them at https://my.telegram.org")
    sys.exit(1)

# Validate Dropbox credentials
if not ((DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN) or DROPBOX_ACCESS_TOKEN):
    logger.error("Missing Dropbox credentials (App Key, App Secret, and Refresh Token).")
    sys.exit(1)

# Parse authorized user IDs
AUTHORIZED_USER_IDS = set()
if AUTHORIZED_USER_IDS_RAW:
    for uid in AUTHORIZED_USER_IDS_RAW.split(","):
        uid = uid.strip()
        if uid.isdigit():
            AUTHORIZED_USER_IDS.add(int(uid))

# Ensure target folder starts with '/'
if not DROPBOX_TARGET_FOLDER.startswith("/"):
    DROPBOX_TARGET_FOLDER = "/" + DROPBOX_TARGET_FOLDER

# Initialize Dropbox client
def get_dropbox_client():
    if DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY and DROPBOX_APP_SECRET:
        return dropbox.Dropbox(
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN
        )
    return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

try:
    dbx = get_dropbox_client()
    account_info = dbx.users_get_current_account()
    logger.info(f"Connected to Dropbox: {account_info.name.display_name} ({account_info.email})")
except Exception as e:
    logger.error(f"Failed to authenticate with Dropbox: {e}")
    sys.exit(1)

# Helper function to check user authorization
def is_authorized(user_id: int) -> bool:
    if not AUTHORIZED_USER_IDS:
        return True
    return user_id in AUTHORIZED_USER_IDS

# Format bytes to human-readable size
def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

# Chunked upload to Dropbox (supports files up to multiple gigabytes)
def upload_file_to_dropbox(local_file_path: str, dropbox_dest_path: str, chunk_size_mb: int = 8) -> str:
    file_size = os.path.getsize(local_file_path)
    chunk_size = chunk_size_mb * 1024 * 1024

    with open(local_file_path, "rb") as f:
        if file_size <= chunk_size:
            dbx.files_upload(f.read(), dropbox_dest_path, mode=WriteMode.overwrite)
        else:
            upload_session_start_result = dbx.files_upload_session_start(f.read(chunk_size))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=upload_session_start_result.session_id,
                offset=f.tell()
            )
            commit = CommitInfo(path=dropbox_dest_path, mode=WriteMode.overwrite)

            while f.tell() < file_size:
                if (file_size - f.tell()) <= chunk_size:
                    dbx.files_upload_session_finish(f.read(chunk_size), cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(f.read(chunk_size), cursor)
                    cursor.offset = f.tell()

    # Generate or retrieve a shared link
    try:
        shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_dest_path)
        return shared_link_metadata.url
    except ApiError as err:
        if err.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=dropbox_dest_path, direct_only=True).links
            if links:
                return links[0].url
        logger.warning(f"Could not generate shared link: {err}")
        return ""

# Initialize Telethon Client with Bot Token
client = TelegramClient("bot_session", int(TELEGRAM_API_ID), TELEGRAM_API_HASH)

@client.on(events.NewMessage)
async def message_handler(event):
    if not event.is_private:
        return

    sender = await event.get_sender()
    user_id = sender.id if sender else 0

    if not is_authorized(user_id):
        await event.reply(
            f"⛔ **Access Denied**: You are not authorized to use this bot.\n"
            f"Your Telegram ID: `{user_id}`"
        )
        return

    # Handle /start or /help commands
    if event.raw_text in ["/start", "/help"]:
        auth_status = "✅ Authorized" if is_authorized(user_id) else "⛔ Not Authorized"
        welcome_text = (
            "👋 **Welcome to Telegram ➔ Dropbox Sync Bot (2 GB MTProto Edition)!**\n\n"
            f"👤 **Your Telegram ID:** `{user_id}`\n"
            f"🔒 **Access Status:** {auth_status}\n"
            f"📁 **Dropbox Destination:** `{DROPBOX_TARGET_FOLDER}`\n"
            "⚡ **Max File Size:** `2,000 MB (2 GB)`\n\n"
            "📥 **How to use:**\n"
            "Send or forward any file, video, image, document, or audio to this bot. "
            "It will automatically download it without the 20MB limit and upload it directly to Dropbox!"
        )
        await event.reply(welcome_text)
        return

    # Check if message contains downloadable media
    if not event.message.media:
        return

    # Extract file details
    file_size = event.message.file.size if event.message.file else 0
    filename = event.message.file.name if event.message.file and event.message.file.name else f"telegram_file_{event.message.id}.bin"
    formatted_size = format_size(file_size)

    status_msg = await event.reply(
        f"⏳ **Starting download from Telegram...**\n"
        f"📄 `{filename}` ({formatted_size})"
    )

    tmp_dir = tempfile.gettempdir()
    local_path = os.path.join(tmp_dir, f"{int(time.time())}_{filename}")

    last_edit = [0]

    async def download_progress(current, total):
        # Throttle progress updates to avoid Telegram rate limits
        now = time.time()
        if now - last_edit[0] > 4:
            percent = (current / total) * 100 if total > 0 else 0
            try:
                await status_msg.edit(
                    f"⏳ **Downloading from Telegram... {percent:.1f}%**\n"
                    f"📄 `{filename}`\n"
                    f"📦 `{format_size(current)} / {format_size(total)}`"
                )
                last_edit[0] = now
            except Exception:
                pass

    try:
        # Download media up to 2GB via MTProto
        await client.download_media(
            event.message,
            file=local_path,
            progress_callback=download_progress
        )

        await status_msg.edit(
            f"☁️ **Uploading to Dropbox...**\n"
            f"📄 `{filename}` ({formatted_size})"
        )

        dropbox_path = f"{DROPBOX_TARGET_FOLDER.rstrip('/')}/{filename}"

        # Execute Dropbox upload in thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        shared_url = await loop.run_in_executor(
            None, upload_file_to_dropbox, local_path, dropbox_path
        )

        # Upload complete notification
        reply_text = (
            "✅ **Upload Complete!**\n\n"
            f"📁 **Folder:** `{DROPBOX_TARGET_FOLDER}`\n"
            f"📄 **File:** `{filename}`\n"
            f"📦 **Size:** `{formatted_size}`\n"
        )
        if shared_url:
            reply_text += f"\n🔗 [Open in Dropbox]({shared_url})"

        await status_msg.edit(reply_text, link_preview=False)
        logger.info(f"Successfully processed: {filename} ({formatted_size})")

    except Exception as e:
        logger.error(f"Failed processing {filename}: {e}", exc_info=True)
        await status_msg.edit(f"❌ **Upload Failed**\n\nError: `{str(e)}`")
    finally:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass

# Graceful runner loop with GitHub Actions timeout
async def main():
    await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    me = await client.get_me()
    logger.info(f"Bot online as @{me.username} via Telethon MTProto engine.")
    logger.info(f"Target Dropbox Folder: {DROPBOX_TARGET_FOLDER}")
    logger.info(f"Max execution time: {MAX_RUN_TIME_MINUTES} minutes")

    async def timeout_guard():
        await asyncio.sleep(MAX_RUN_TIME_MINUTES * 60)
        logger.info("Maximum run duration reached. Gracefully disconnecting...")
        await client.disconnect()

    asyncio.create_task(timeout_guard())
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())