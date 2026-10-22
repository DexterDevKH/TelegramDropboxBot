import os
import sys
import time
import logging
import threading
import tempfile
import telebot
import dropbox
from dropbox.files import WriteMode, CommitInfo
from dropbox.exceptions import ApiError, AuthError

# Configure logging
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load configurations from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
DROPBOX_TARGET_FOLDER = os.getenv("DROPBOX_TARGET_FOLDER", "/Telegram_Uploads").strip()
AUTHORIZED_USER_IDS_RAW = os.getenv("AUTHORIZED_USER_IDS", "").strip()
MAX_RUN_TIME_MINUTES = int(os.getenv("MAX_RUN_TIME_MINUTES", "340"))

# Parse authorized user IDs
AUTHORIZED_USER_IDS = set()
if AUTHORIZED_USER_IDS_RAW:
    for uid in AUTHORIZED_USER_IDS_RAW.split(","):
        uid = uid.strip()
        if uid.isdigit():
            AUTHORIZED_USER_IDS.add(int(uid))

# Validate mandatory configuration
if not TELEGRAM_BOT_TOKEN:
    logger.error("Missing TELEGRAM_BOT_TOKEN environment variable.")
    sys.exit(1)

if not ((DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN) or DROPBOX_ACCESS_TOKEN):
    logger.error(
        "Missing Dropbox credentials. Provide either (DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN) "
        "or DROPBOX_ACCESS_TOKEN."
    )
    sys.exit(1)

# Ensure target folder starts with '/'
if not DROPBOX_TARGET_FOLDER.startswith("/"):
    DROPBOX_TARGET_FOLDER = "/" + DROPBOX_TARGET_FOLDER

# Initialize Telegram Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="Markdown")

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
    logger.info(f"Connected to Dropbox account: {account_info.name.display_name} ({account_info.email})")
except Exception as e:
    logger.error(f"Failed to authenticate with Dropbox: {e}")
    sys.exit(1)

# Helper function to check user authorization
def is_authorized(user_id: int) -> bool:
    if not AUTHORIZED_USER_IDS:
        return True
    return user_id in AUTHORIZED_USER_IDS

# Helper to format file sizes
def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

# Chunked upload to Dropbox
def upload_file_to_dropbox(local_file_path: str, dropbox_dest_path: str, chunk_size_mb: int = 4) -> str:
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

# Common download and upload handler
def process_media_upload(message, file_id: str, original_filename: str):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        bot.reply_to(
            message,
            "⛔ *Access Denied*: You are not authorized to use this bot.\n"
            f"Your Telegram ID: `{user_id}`"
        )
        return

    status_msg = bot.reply_to(message, "⏳ *Downloading file from Telegram...*")

    tmp_dir = tempfile.gettempdir()
    local_path = os.path.join(tmp_dir, f"{int(time.time())}_{original_filename}")

    try:
        file_info = bot.get_file(file_id)
        downloaded_data = bot.download_file(file_info.file_path)

        with open(local_path, "wb") as f:
            f.write(downloaded_data)

        file_size = os.path.getsize(local_path)
        formatted_size = format_size(file_size)

        bot.edit_message_text(
            f"☁️ *Uploading to Dropbox...*\n"
            f"📄 *File:* `{original_filename}`\n"
            f"📦 *Size:* `{formatted_size}`",
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id
        )

        dropbox_path = f"{DROPBOX_TARGET_FOLDER.rstrip('/')}/{original_filename}"
        shared_url = upload_file_to_dropbox(local_path, dropbox_path)

        reply_text = (
            "✅ *Upload Complete!*\n\n"
            f"📁 *Folder:* `{DROPBOX_TARGET_FOLDER}`\n"
            f"📄 *File Name:* `{original_filename}`\n"
            f"📦 *File Size:* `{formatted_size}`\n"
        )
        if shared_url:
            reply_text += f"\n🔗 [Open in Dropbox]({shared_url})"

        bot.edit_message_text(
            reply_text,
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id,
            disable_web_page_preview=False
        )
        logger.info(f"Successfully uploaded: {original_filename} ({formatted_size})")

    except Exception as e:
        logger.error(f"Error handling file {original_filename}: {e}", exc_info=True)
        bot.edit_message_text(
            f"❌ *Upload Failed*\n\nError: `{str(e)}`",
            chat_id=status_msg.chat.id,
            message_id=status_msg.message_id
        )
    finally:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass

# Bot Command: /start and /help
@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    user_id = message.from_user.id
    auth_status = "✅ Authorized" if is_authorized(user_id) else "⛔ Not Authorized"
    welcome_text = (
        "👋 *Welcome to the Telegram ➔ Dropbox Auto-Uploader Bot!*\n\n"
        f"👤 *Your Telegram ID:* `{user_id}`\n"
        f"🔒 *Access Status:* {auth_status}\n"
        f"📁 *Dropbox Destination:* `{DROPBOX_TARGET_FOLDER}`\n\n"
        "📥 *How to use:*\n"
        "Send or forward any document, photo, video, or audio file to this chat. "
        "It will automatically upload to your Dropbox!"
    )
    bot.reply_to(message, welcome_text)

# Content Type Handlers
@bot.message_handler(content_types=["document"])
def handle_document(message):
    doc = message.document
    filename = doc.file_name or f"document_{doc.file_id}.bin"
    process_media_upload(message, doc.file_id, filename)

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    photo = message.photo[-1]
    filename = f"photo_{photo.file_unique_id}_{int(time.time())}.jpg"
    process_media_upload(message, photo.file_id, filename)

@bot.message_handler(content_types=["video"])
def handle_video(message):
    vid = message.video
    filename = vid.file_name or f"video_{vid.file_unique_id}_{int(time.time())}.mp4"
    process_media_upload(message, vid.file_id, filename)

@bot.message_handler(content_types=["audio"])
def handle_audio(message):
    aud = message.audio
    filename = aud.file_name or f"audio_{aud.file_unique_id}_{int(time.time())}.mp3"
    process_media_upload(message, aud.file_id, filename)

@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    voice = message.voice
    filename = f"voice_{voice.file_unique_id}_{int(time.time())}.ogg"
    process_media_upload(message, voice.file_id, filename)

# Runner Loop with graceful termination
def main():
    logger.info("Starting Telegram Bot listener...")
    logger.info(f"Target Dropbox Folder: {DROPBOX_TARGET_FOLDER}")
    logger.info(f"Max run time limit set to: {MAX_RUN_TIME_MINUTES} minutes")

    def stop_timer():
        time.sleep(MAX_RUN_TIME_MINUTES * 60)
        logger.info("Maximum execution time reached. Gracefully stopping bot polling.")
        bot.stop_polling()

    timer_thread = threading.Thread(target=stop_timer, daemon=True)
    timer_thread.start()

    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        logger.error(f"Polling encountered an error: {e}")
    finally:
        logger.info("Bot execution cycle ended cleanly.")

if __name__ == "__main__":
    main()