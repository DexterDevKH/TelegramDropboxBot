"""
Configuration Loader & Validation Module
"""

import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Set, Optional
from dotenv import load_dotenv

# Load local .env if available
load_dotenv()

class ProfessionalFormatter(logging.Formatter):
    """Clean structured log formatter for cloud and local runners."""
    def format(self, record):
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        lvl = record.levelname.ljust(8)
        return f"{ts} │ {lvl} │ {record.name}: {record.getMessage()}"

def setup_logging(level_name: str = "INFO") -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ProfessionalFormatter())
    logging.root.setLevel(level)
    logging.root.handlers = [handler]
    return logging.getLogger("SyncEngine")

@dataclass
class AppConfig:
    # Telegram credentials
    telegram_bot_token: str
    telegram_api_id: int
    telegram_api_hash: str

    # Dropbox credentials
    dropbox_app_key: Optional[str] = None
    dropbox_app_secret: Optional[str] = None
    dropbox_refresh_token: Optional[str] = None
    dropbox_access_token: Optional[str] = None
    dropbox_ipa_folder: str = "/IPA"
    dropbox_deb_folder: str = "/DEB"

    # Access control & limits
    authorized_user_ids: Set[int] = field(default_factory=set)
    max_files_in_folder: int = 2
    max_files_in_deb_folder: Optional[int] = None
    chunk_size_mb: int = 8
    privacy_mode: bool = True
    log_level: str = "INFO"

    # GitHub Actions workflow dispatch & tracking
    gh_pat: str = ""
    gh_repo: str = "DexterDevKH/TelegramDropboxBot"

    # Targeted on-demand execution context
    target_chat_id: Optional[int] = None
    target_message_id: Optional[int] = None
    dispatch_message_id: Optional[int] = None
    build_target_key: Optional[str] = None
    build_run_id: Optional[int] = None
    build_start_time: float = 0.0
    idle_keep_alive_seconds: int = 0
    is_github_actions: bool = False

    # URL & Artifact Ingestion Context
    download_url: Optional[str] = None
    is_artifact: bool = False
    artifact_id: Optional[str] = None
    artifact_repo: Optional[str] = None
    file_name: Optional[str] = None
    file_size: int = 0

    def is_authorized(self, user_id: int) -> bool:
        """Validates if user ID has permission to invoke bot actions."""
        if not self.authorized_user_ids:
            return True
        return user_id in self.authorized_user_ids

    def has_dropbox_credentials(self) -> bool:
        """Checks if minimum required Dropbox credentials exist."""
        return bool(
            (self.dropbox_refresh_token and self.dropbox_app_key and self.dropbox_app_secret)
            or self.dropbox_access_token
        )

    @property
    def dropbox_target_folder(self) -> str:
        """Backward-compatible alias for dropbox_ipa_folder."""
        return self.dropbox_ipa_folder

    def get_max_files_for_folder(self, folder_path: str) -> int:
        """Returns the retention file cap for a given folder path."""
        norm = (folder_path or "").strip().rstrip("/")
        if not norm.startswith("/"):
            norm = "/" + norm
        deb_norm = self.dropbox_deb_folder.strip().rstrip("/")
        if not deb_norm.startswith("/"):
            deb_norm = "/" + deb_norm

        if norm.lower() == deb_norm.lower() and self.max_files_in_deb_folder is not None:
            return self.max_files_in_deb_folder
        return self.max_files_in_folder


def load_config() -> AppConfig:
    """Parses environment variables and validates critical settings."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not bot_token:
        print("CRITICAL CONFIG ERROR: Missing TELEGRAM_BOT_TOKEN environment variable.", file=sys.stderr)
        sys.exit(1)

    if not api_id_raw or not api_hash:
        print("CRITICAL CONFIG ERROR: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH.", file=sys.stderr)
        sys.exit(1)

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("CRITICAL CONFIG ERROR: TELEGRAM_API_ID must be a valid integer.", file=sys.stderr)
        sys.exit(1)

    ipa_folder = (
        os.getenv("DROPBOX_IPA_FOLDER")
        or os.getenv("DROPBOX_TARGET_FOLDER")
        or "/IPA"
    ).strip()
    if not ipa_folder.startswith("/"):
        ipa_folder = "/" + ipa_folder

    deb_folder = os.getenv("DROPBOX_DEB_FOLDER", "/DEB").strip()
    if not deb_folder.startswith("/"):
        deb_folder = "/" + deb_folder

    max_files_global = int(os.getenv("MAX_FILES_IN_FOLDER", "2"))
    max_files_deb_raw = os.getenv("MAX_FILES_IN_DEB_FOLDER", "").strip()
    max_files_deb = int(max_files_deb_raw) if max_files_deb_raw.isdigit() else None

    # Parse Authorized User IDs
    authorized_raw = os.getenv("AUTHORIZED_USER_IDS", "").strip()
    authorized_ids: Set[int] = set()
    if authorized_raw:
        for item in authorized_raw.split(","):
            cleaned = item.strip()
            if cleaned.isdigit():
                authorized_ids.add(int(cleaned))

    # Parse On-Demand Execution Context
    chat_id_raw = os.getenv("TARGET_CHAT_ID", "").strip()
    msg_id_raw = os.getenv("TARGET_MESSAGE_ID", "").strip()
    disp_id_raw = os.getenv("DISPATCH_MESSAGE_ID", "").strip()
    target_chat = int(chat_id_raw) if (chat_id_raw.lstrip("-").isdigit()) else None
    target_msg = int(msg_id_raw) if msg_id_raw.isdigit() else None
    disp_msg = int(disp_id_raw) if disp_id_raw.isdigit() else None

    build_target_key = os.getenv("BUILD_TARGET_KEY", "").strip() or None
    run_id_raw = os.getenv("BUILD_RUN_ID", "").strip()
    build_run_id = int(run_id_raw) if (run_id_raw.isdigit() and int(run_id_raw) > 0) else None

    start_time_raw = os.getenv("BUILD_START_TIME", "").strip()
    build_start_time = float(start_time_raw) / 1000.0 if start_time_raw.isdigit() else 0.0

    gh_pat = os.getenv("GH_PAT") or os.getenv("PAT") or os.getenv("GITHUB_TOKEN") or ""
    gh_repo = os.getenv("GH_REPO", "DexterDevKH/TelegramDropboxBot").strip()

    privacy = os.getenv("PRIVACY_MODE", "true").strip().lower() in ("true", "1", "yes")
    log_level = os.getenv("LOG_LEVEL", "INFO").strip()

    # Parse URL & Artifact Ingestion Context
    download_url = os.getenv("DOWNLOAD_URL", "").strip() or None
    is_artifact = os.getenv("IS_ARTIFACT", "false").strip().lower() in ("true", "1", "yes")
    artifact_id = os.getenv("ARTIFACT_ID", "").strip() or None
    artifact_repo = os.getenv("ARTIFACT_REPO", "").strip() or None
    file_name = os.getenv("FILE_NAME", "").strip() or None
    file_size_raw = os.getenv("FILE_SIZE", "0").strip()
    file_size = int(file_size_raw) if file_size_raw.isdigit() else 0

    return AppConfig(
        telegram_bot_token=bot_token,
        telegram_api_id=api_id,
        telegram_api_hash=api_hash,
        dropbox_app_key=os.getenv("DROPBOX_APP_KEY", "").strip() or None,
        dropbox_app_secret=os.getenv("DROPBOX_APP_SECRET", "").strip() or None,
        dropbox_refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN", "").strip() or None,
        dropbox_access_token=os.getenv("DROPBOX_ACCESS_TOKEN", "").strip() or None,
        dropbox_ipa_folder=ipa_folder,
        dropbox_deb_folder=deb_folder,
        authorized_user_ids=authorized_ids,
        max_files_in_folder=max_files_global,
        max_files_in_deb_folder=max_files_deb,
        chunk_size_mb=int(os.getenv("CHUNK_SIZE_MB", "8")),
        privacy_mode=privacy,
        log_level=log_level,
        gh_pat=gh_pat,
        gh_repo=gh_repo,
        target_chat_id=target_chat,
        target_message_id=target_msg,
        dispatch_message_id=disp_msg,
        build_target_key=build_target_key,
        build_run_id=build_run_id,
        build_start_time=build_start_time,
        idle_keep_alive_seconds=int(os.getenv("IDLE_KEEP_ALIVE_SECONDS", "0")),
        is_github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true",
        download_url=download_url,
        is_artifact=is_artifact,
        artifact_id=artifact_id,
        artifact_repo=artifact_repo,
        file_name=file_name,
        file_size=file_size,
    )

