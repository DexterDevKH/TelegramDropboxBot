"""
Dropbox Cloud Storage Client & Streaming Operations
"""

import os
import logging
from typing import Tuple, List, Optional, Callable
import dropbox
from dropbox.files import WriteMode, CommitInfo, FileMetadata
from dropbox.exceptions import ApiError, AuthError, BadInputError, DropboxException

from src.config import AppConfig
from src.privacy import mask_filename, register_github_mask
from src.formatters import normalize_url

logger = logging.getLogger("SyncEngine.Dropbox")

class DropboxService:
    """Manages authenticated operations and streaming chunk uploads to Dropbox."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.client: Optional[dropbox.Dropbox] = None
        self.account_name: str = "Connected Cloud Account"
        self.account_email: str = ""

    def initialize(self) -> bool:
        """Initializes and verifies the Dropbox connection."""
        if not self.config.has_dropbox_credentials():
            logger.warning("No Dropbox credentials provided in environment.")
            return False

        try:
            if self.config.dropbox_refresh_token and self.config.dropbox_app_key and self.config.dropbox_app_secret:
                self.client = dropbox.Dropbox(
                    app_key=self.config.dropbox_app_key,
                    app_secret=self.config.dropbox_app_secret,
                    oauth2_refresh_token=self.config.dropbox_refresh_token,
                )
            elif self.config.dropbox_access_token:
                self.client = dropbox.Dropbox(self.config.dropbox_access_token)

            if not self.client:
                return False

            acc = self.client.users_get_current_account()
            self.account_name = acc.name.display_name
            self.account_email = acc.email

            if self.config.is_github_actions:
                register_github_mask(self.account_email)
                register_github_mask(self.account_name)

            if self.config.privacy_mode:
                logger.info("Authenticated Dropbox Account: [PROTECTED/MASKED]")
            else:
                logger.info(f"Authenticated Dropbox Account: {self.account_name} ({self.account_email})")

            return True
        except Exception as exc:
            logger.critical(f"Dropbox Authentication Failure: {exc}")
            return False

    def enforce_folder_retention(self, folder_path: str, max_files: int) -> List[str]:
        """
        Enforces FIFO file retention on target Dropbox directory.
        Deletes oldest files by server modification time if total exceeds max_files.
        """
        deleted_files: List[str] = []
        if not self.client:
            return deleted_files

        if not folder_path or folder_path.strip("/") == "":
            return deleted_files

        try:
            files: List[FileMetadata] = []
            result = self.client.files_list_folder(folder_path)
            while True:
                for entry in result.entries:
                    if isinstance(entry, FileMetadata):
                        files.append(entry)
                if not result.has_more:
                    break
                result = self.client.files_list_folder_continue(result.cursor)

            if len(files) > max_files:
                files.sort(key=lambda item: item.server_modified)
                overflow_count = len(files) - max_files
                for old_file in files[:overflow_count]:
                    try:
                        self.client.files_delete_v2(old_file.path_lower)
                        deleted_files.append(old_file.name)
                        log_file = mask_filename(old_file.name, self.config.privacy_mode)
                        log_folder = "[PROTECTED_VAULT]" if self.config.privacy_mode else folder_path
                        logger.info(f"Retention Policy: Pruned oldest file '{log_file}' from {log_folder}")
                    except Exception as del_err:
                        log_file = mask_filename(old_file.name, self.config.privacy_mode)
                        logger.error(f"Failed to prune '{log_file}': {del_err}")

        except ApiError as api_err:
            log_folder = "[PROTECTED_VAULT]" if self.config.privacy_mode else folder_path
            logger.warning(f"Retention scan skipped for '{log_folder}': {api_err}")
        except Exception as exc:
            logger.error(f"Unexpected error during retention enforcement: {exc}")

        return deleted_files

    def upload_file_chunked(
        self,
        local_path: str,
        dest_path: str,
        target_folder: str,
        chunk_size_mb: int = 8,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Uploads file to Dropbox using streaming chunk sessions for maximum reliability.
        Returns (shared_url, deleted_files_list).
        """
        if not self.client:
            raise RuntimeError("Dropbox client is not initialized.")

        file_size = os.path.getsize(local_path)
        chunk_bytes = chunk_size_mb * 1024 * 1024

        with open(local_path, "rb") as stream:
            if file_size <= chunk_bytes:
                self.client.files_upload(stream.read(), dest_path, mode=WriteMode.overwrite)
                if progress_callback:
                    progress_callback(file_size, file_size)
            else:
                session_start = self.client.files_upload_session_start(stream.read(chunk_bytes))
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=session_start.session_id,
                    offset=stream.tell(),
                )
                commit = CommitInfo(path=dest_path, mode=WriteMode.overwrite)

                if progress_callback:
                    progress_callback(stream.tell(), file_size)

                while stream.tell() < file_size:
                    remaining = file_size - stream.tell()
                    if remaining <= chunk_bytes:
                        self.client.files_upload_session_finish(stream.read(chunk_bytes), cursor, commit)
                        if progress_callback:
                            progress_callback(file_size, file_size)
                    else:
                        self.client.files_upload_session_append_v2(stream.read(chunk_bytes), cursor)
                        cursor.offset = stream.tell()
                        if progress_callback:
                            progress_callback(stream.tell(), file_size)

        log_dest = (
            f"[PROTECTED_VAULT]/{mask_filename(os.path.basename(dest_path), self.config.privacy_mode)}"
            if self.config.privacy_mode
            else dest_path
        )
        logger.info(f"Successfully committed file to Dropbox: {log_dest}")

        # Enforce FIFO Retention only on configured subfolders (never on root)
        pruned_files: List[str] = []
        if target_folder and target_folder.strip("/") != "":
            pruned_files = self.enforce_folder_retention(target_folder, max_files=self.config.max_files_in_folder)

        # Generate direct download shared link
        shared_link = ""
        try:
            metadata = self.client.sharing_create_shared_link_with_settings(dest_path)
            shared_link = metadata.url
        except ApiError as err:
            if err.error.is_shared_link_already_exists():
                try:
                    existing = self.client.sharing_list_shared_links(path=dest_path, direct_only=True).links
                    if existing:
                        shared_link = existing[0].url
                except Exception:
                    pass
            else:
                logger.warning(f"Shared link generation error: {err}")
        except Exception as exc:
            logger.warning(f"Shared link generation skipped: {exc}")

        return normalize_url(shared_link), pruned_files

