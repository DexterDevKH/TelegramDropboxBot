"""
Telegram to Dropbox Cloud Sync & iOS IPA Workflow Engine (v3.0.0)
Master Orchestration Module
"""

import os
import re
import sys
import time
import signal
import asyncio
import logging
import tempfile
import zipfile
import shutil
from typing import Optional, Dict, Any

from telethon import events, Button

from src.config import AppConfig, setup_logging
from src.constants import BUILD_TARGETS, get_target, get_extensions
from src.privacy import mask_filename, mask_user_id
from src.formatters import (
    format_size,
    format_eta,
    render_progress_bar,
    sanitize_filename,
    normalize_url,
    decode_bitmask,
    SpeedTracker,
    parse_artifact_url,
    parse_run_url,
    extract_single_file_from_zip,
)
from src.dropbox_service import DropboxService
from src.github_service import GitHubService
from src.telegram_bot import TelegramService
from src.ui import (
    render_main_menu,
    render_dashboard_text,
    render_dashboard_buttons,
    render_extensions_keyboard,
    render_build_tracking_card,
    render_build_completed_card,
    render_build_failed_card,
    apply_native_copy_button,
)

logger = logging.getLogger("SyncEngine")

class SyncApp:
    """Master application controlling on-demand cloud sync and standalone daemon flows."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.tg = TelegramService(config)
        self.dbx = DropboxService(config)
        self.gh = GitHubService(config.gh_pat)

        self.start_timestamp = time.time()
        self.last_activity_timestamp = time.time()
        self.session_transfers_count = 0
        self.session_transfers_bytes = 0
        self.shutdown_event = asyncio.Event()

        # In-Memory State Caches
        self.user_dashboards: Dict[int, Dict[str, Any]] = {}
        self.pending_inputs: Dict[int, Dict[str, Any]] = {}

    def compile_workflow_inputs(self, state: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, str]:
        """Compiles dictionary of inputs for GitHub Actions workflow dispatch."""
        inputs = {
            "ipa_url": state.get("ipa", ""),
            "display_name": state.get("name") or target.get("defaultInputs", {}).get("display_name", "DexTube"),
            "bundle_id": state.get("bundle") or target.get("defaultInputs", {}).get("bundle_id", "com.google.ios.youtube"),
        }
        if target.get("hasExtensions"):
            if state.get("tweak"):
                inputs["custom_tweak"] = "true"
                inputs["tweak_url"] = state["tweak"]
            exts = get_extensions(target["key"])
            mask_hex = state.get("maskHex", "1fff")
            decoded = decode_bitmask(mask_hex, exts)
            for ext in exts:
                inputs[ext["input"]] = "true" if decoded["is_enabled"](ext["key"]) else "false"
        return inputs

    async def track_workflow_progress(
        self, chat_id: int, message_id: int, target: Dict[str, Any], initial_run_id: Optional[int], start_time: float
    ):
        """Background task that tracks GitHub Actions workflow execution until completion."""
        run_id = initial_run_id
        max_checks = 180  # 180 checks * 6s = 18 minutes

        for check_idx in range(max_checks):
            await asyncio.sleep(6)
            try:
                if not run_id:
                    latest = await self.gh.get_latest_workflow_run(target["repo"])
                    if latest:
                        run_id = latest.get("id")

                if not run_id:
                    continue

                details = await self.gh.get_workflow_run_details(target["repo"], run_id)
                if not details:
                    continue

                created_at_str = details.get("created_at")
                if created_at_str:
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        elapsed_secs = max(1.0, time.time() - dt.timestamp())
                    except Exception:
                        elapsed_secs = max(1.0, time.time() - start_time)
                else:
                    elapsed_secs = max(1.0, time.time() - start_time)

                run_url = details.get("html_url") or f"https://github.com/{target['repo']}/actions/runs/{run_id}"
                status = details.get("status")
                conclusion = details.get("conclusion")

                if status == "completed":
                    if conclusion == "success":
                        rel = await self.gh.get_latest_release(target["repo"])
                        ipa_asset = rel.get("asset") if rel else None
                        if not ipa_asset:
                            await asyncio.sleep(3)
                            rel = await self.gh.get_latest_release(target["repo"])
                            ipa_asset = rel.get("asset") if rel else None

                        card, btns, dl_url = render_build_completed_card(target, rel, ipa_asset, elapsed_secs)
                        await self.tg.safe_edit_message(chat_id, card, buttons=btns, message_id=message_id)
                    else:
                        card, btns = render_build_failed_card(target, run_id, conclusion or "failed", elapsed_secs, run_url)
                        await self.tg.safe_edit_message(chat_id, card, buttons=btns, message_id=message_id)
                    break
                else:
                    card, btns = render_build_tracking_card(target, run_id, status, elapsed_secs, run_url)
                    await self.tg.safe_edit_message(chat_id, card, buttons=btns, message_id=message_id)
            except Exception as exc:
                logger.debug(f"Workflow tracking polling error (check #{check_idx}): {exc}")

    async def process_media_message(self, msg: Any, dispatch_msg_id: Optional[int] = None):
        """Ingests incoming media payload from Telegram and streams chunked upload to Dropbox."""
        self.last_activity_timestamp = time.time()

        if not getattr(msg, "is_private", True):
            return

        sender = await msg.get_sender()
        user_id = sender.id if sender else 0

        if not self.config.is_authorized(user_id):
            logger.warning(f"Unauthorized media upload attempt from user_id: {mask_user_id(user_id, self.config.privacy_mode)}")
            return

        if not msg.media:
            return

        file_size = msg.file.size if msg.file else 0
        raw_name = msg.file.name if msg.file and msg.file.name else f"payload_{msg.id}.bin"
        filename = sanitize_filename(raw_name)
        formatted_total_size = format_size(file_size)

        target_chat_id = getattr(msg, "chat_id", getattr(msg, "peer_id", None))
        if hasattr(target_chat_id, "user_id"):
            target_chat_id = target_chat_id.user_id

        status_msg = None
        if dispatch_msg_id and target_chat_id:
            try:
                status_msg = await self.tg.client.get_messages(target_chat_id, ids=dispatch_msg_id)
                if status_msg:
                    logger.info(f"Reusing existing dispatch notice message ID: {dispatch_msg_id}")
            except Exception as e:
                logger.warning(f"Could not fetch dispatch notice message {dispatch_msg_id}: {e}")

        init_card = (
            "⏳ **INGESTING PAYLOAD**\n"
            "──────────────────────────────\n"
            f"📄 **Filename:** `{filename}`\n"
            f"📦 **Filesize:** `{formatted_total_size}`\n"
            "⚡ **Status:** Connecting to Telegram MTProto..."
        )

        if not status_msg:
            status_msg = await msg.reply(init_card)
        else:
            await self.tg.safe_edit_message(status_msg, init_card)

        tmp_dir = tempfile.gettempdir()
        local_target = os.path.join(tmp_dir, f"{int(time.time())}_{filename}")
        cleanup_paths = [local_target]

        last_dl_update_ts = [0.0]
        dl_start_time = time.time()
        dl_speed_tracker = SpeedTracker(alpha=0.3)

        async def download_progress_hook(current_bytes: int, total_bytes: int):
            now = time.time()
            if (now - last_dl_update_ts[0] > 3.0) or (current_bytes >= total_bytes):
                last_dl_update_ts[0] = now
                pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                speed = dl_speed_tracker.update(current_bytes)
                if speed <= 0:
                    elapsed = max(0.1, now - dl_start_time)
                    speed = current_bytes / elapsed
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
                await self.tg.safe_edit_message(status_msg, card)

        try:
            # Phase 1: MTProto Download
            await self.tg.client.download_media(
                msg,
                file=local_target,
                progress_callback=download_progress_hook,
            )
            download_duration = max(0.1, time.time() - dl_start_time)

            # Phase 1.5: If zip archive, unzip it and upload only the file inside
            final_file_path = local_target
            final_filename = filename
            unzipped_from_archive = False

            if filename.lower().endswith(".zip") or (not filename.lower().endswith(".ipa") and zipfile.is_zipfile(local_target)):
                unzip_res = extract_single_file_from_zip(local_target, tmp_dir)
                if unzip_res:
                    final_file_path, extracted_name, extracted_size, ext_dest_dir = unzip_res
                    final_filename = extracted_name
                    file_size = extracted_size
                    formatted_total_size = format_size(file_size)
                    unzipped_from_archive = True
                    cleanup_paths.extend([final_file_path, ext_dest_dir])
                    logger.info(f"Unzipped media archive: extracted '{final_filename}' ({formatted_total_size})")

            await self.tg.safe_edit_message(
                status_msg,
                "☁️ **STREAMING TO DROPBOX**\n"
                "──────────────────────────────\n"
                f"📄 **Filename:** `{final_filename}`\n"
                f"📦 **Filesize:** `{formatted_total_size}`\n"
                f"⏱️ **Ingest Time:** `{download_duration:.1f}s`\n"
                "⚡ **Status:** Initializing cloud transfer...",
            )

            # Phase 2: Chunked Upload to Dropbox
            dropbox_target_path = f"{self.config.dropbox_target_folder.rstrip('/')}/{final_filename}"
            loop = asyncio.get_running_loop()
            upload_start_time = time.time()
            last_ul_update_ts = [0.0]
            ul_speed_tracker = SpeedTracker(alpha=0.3)

            def dropbox_progress_hook(current_bytes: int, total_bytes: int):
                now = time.time()
                if (now - last_ul_update_ts[0] > 3.0) or (current_bytes >= total_bytes):
                    last_ul_update_ts[0] = now
                    pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                    speed = ul_speed_tracker.update(current_bytes)
                    if speed <= 0:
                        elapsed = max(0.1, now - upload_start_time)
                        speed = current_bytes / elapsed
                    remaining_bytes = max(0, total_bytes - current_bytes)
                    eta = (remaining_bytes / speed) if speed > 0 else 0

                    card = (
                        "☁️ **STREAMING TO DROPBOX**\n"
                        "──────────────────────────────\n"
                        f"📄 **Filename:** `{final_filename}`\n"
                        f"📦 **Uploaded:** `{format_size(current_bytes)}` / `{formatted_total_size}`\n"
                        f"⚡ **Speed:** `{format_size(int(speed))}/s`  •  ⏳ **ETA:** `{format_eta(eta)}`\n"
                        f"📊 **Progress:** `{render_progress_bar(pct)}`"
                    )
                    asyncio.run_coroutine_threadsafe(
                        self.tg.safe_edit_message(status_msg, card), loop
                    )

            shared_url, pruned_items = await asyncio.to_thread(
                self.dbx.upload_file_chunked,
                final_file_path,
                dropbox_target_path,
                self.config.dropbox_target_folder,
                self.config.chunk_size_mb,
                dropbox_progress_hook,
            )

            upload_duration = max(0.1, time.time() - upload_start_time)
            total_duration = time.time() - dl_start_time

            dl_speed = file_size / download_duration if download_duration > 0 else 0
            ul_speed = file_size / upload_duration if upload_duration > 0 else 0

            completion_card = (
                "✅ **TRANSFER COMPLETE**\n"
                "──────────────────────────────\n"
                f"📄 **Filename:** `{final_filename}`\n"
                f"📦 **Payload Size:** `{formatted_total_size}`\n"
                f"📂 **Cloud Vault:** `{self.config.dropbox_target_folder}`\n"
            )
            if unzipped_from_archive:
                completion_card += "📦 *Unzipped from archive: only the extracted file was uploaded.*\n"

            completion_card += (
                "\n⏱️ **Performance Metrics**\n"
                f"• ⬇️ **Telegram Ingest:** `{download_duration:.1f}s` (`{format_size(int(dl_speed))}/s`)\n"
                f"• ☁️ **Dropbox Push:** `{upload_duration:.1f}s` (`{format_size(int(ul_speed))}/s`)\n"
                f"• ⏱️ **Total Elapsed:** `{total_duration:.1f}s`\n"
            )

            if pruned_items:
                pruned_str = ", ".join([f"`{name}`" for name in pruned_items])
                completion_card += (
                    f"\n♻️ **Retention Auto-Rotation (Cap: {self.config.max_files_in_folder})**\n"
                    f"• Pruned oldest: {pruned_str}\n"
                )

            if shared_url:
                await self.tg.safe_edit_message(
                    status_msg,
                    completion_card,
                    buttons=[[Button.url("🌐 Open in Dropbox", shared_url)]],
                    link_preview=False,
                )

                # Direct 1-tap clipboard copy via Telegram Bot API v7.0+
                await asyncio.to_thread(
                    apply_native_copy_button,
                    self.config.telegram_bot_token,
                    target_chat_id,
                    status_msg.id,
                    shared_url,
                )
            else:
                completion_card += "\nℹ️ *Payload securely archived in Dropbox vault.*"
                await self.tg.safe_edit_message(status_msg, completion_card, buttons=None, link_preview=False)

            self.session_transfers_count += 1
            self.session_transfers_bytes += file_size
            log_file = mask_filename(filename, self.config.privacy_mode)
            logger.info(f"Sync complete: '{log_file}' ({formatted_total_size}) in {total_duration:.1f}s")

        except Exception as exc:
            log_file = mask_filename(filename, self.config.privacy_mode)
            logger.error(f"Pipeline Failure for '{log_file}': {exc}", exc_info=True)
            failure_card = (
                "❌ **TRANSFER FAILED**\n"
                "──────────────────────────────\n"
                f"📄 **Target File:** `{filename}`\n"
                f"📦 **Payload Size:** `{formatted_total_size}`\n"
                f"⚠️ **Error Details:** `{str(exc)}`\n"
                "──────────────────────────────\n"
                "💡 *Verify runner credentials, cloud quota, or retry with smaller files.*"
            )
            await self.tg.safe_edit_message(status_msg, failure_card)
        finally:
            for p in cleanup_paths:
                if os.path.exists(p):
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass

    async def process_url_payload(
        self,
        url: str,
        msg: Any,
        dispatch_msg_id: Optional[int] = None,
        is_artifact: bool = False,
        artifact_id: Optional[str] = None,
        artifact_repo: Optional[str] = None,
        file_name_override: Optional[str] = None,
        file_size_override: int = 0,
    ):
        """Downloads a remote URL or GitHub Actions artifact and streams chunked upload to Dropbox."""
        self.last_activity_timestamp = time.time()

        if not getattr(msg, "is_private", True):
            return

        sender = await msg.get_sender()
        user_id = sender.id if sender else 0

        if not self.config.is_authorized(user_id):
            logger.warning(f"Unauthorized URL download attempt from user_id: {mask_user_id(user_id, self.config.privacy_mode)}")
            return

        target_chat_id = getattr(msg, "chat_id", getattr(msg, "peer_id", None))
        if hasattr(target_chat_id, "user_id"):
            target_chat_id = target_chat_id.user_id

        status_msg = None
        if dispatch_msg_id and target_chat_id:
            try:
                status_msg = await self.tg.client.get_messages(target_chat_id, ids=dispatch_msg_id)
                if status_msg:
                    logger.info(f"Reusing existing dispatch notice message ID: {dispatch_msg_id}")
            except Exception as e:
                logger.warning(f"Could not fetch dispatch notice message {dispatch_msg_id}: {e}")

        # URL Pattern Matching: GitHub Artifact or Run
        if not is_artifact:
            art_info = parse_artifact_url(url)
            if art_info:
                is_artifact = True
                artifact_repo = art_info["repo_full_name"]
                artifact_id = art_info["artifact_id"]
            else:
                run_info = parse_run_url(url)
                if run_info:
                    run_artifacts = await self.gh.get_run_artifacts(run_info["repo_full_name"], run_info["run_id"])
                    if run_artifacts:
                        is_artifact = True
                        artifact_repo = run_info["repo_full_name"]
                        artifact_id = str(run_artifacts[0].get("id"))
                        if not file_name_override:
                            file_name_override = run_artifacts[0].get("name")
                        if not file_size_override:
                            file_size_override = run_artifacts[0].get("size_in_bytes", 0)

        # Inspect artifact metadata
        artifact_name_from_meta = None
        if is_artifact and artifact_repo and artifact_id:
            meta = await self.gh.get_artifact_metadata(artifact_repo, artifact_id)
            if meta:
                if meta.get("expired"):
                    expired_card = (
                        "⚠️ **ARTIFACT EXPIRED**\n"
                        "──────────────────────────────\n"
                        f"📦 **Artifact:** `{meta.get('name')}`\n"
                        f"📁 **Repository:** `{artifact_repo}`\n"
                        f"📅 **Expired At:** `{meta.get('expires_at', 'Unknown')}`\n\n"
                        "💡 *This GitHub Actions artifact has expired and can no longer be downloaded.*"
                    )
                    if status_msg:
                        await self.tg.safe_edit_message(status_msg, expired_card)
                    else:
                        await msg.reply(expired_card)
                    return
                artifact_name_from_meta = meta.get("name")
                if not file_name_override and artifact_name_from_meta:
                    file_name_override = artifact_name_from_meta
                if not file_size_override and meta.get("size_in_bytes"):
                    file_size_override = meta["size_in_bytes"]

        initial_name = file_name_override or "downloaded_file.bin"
        source_label = f"GitHub Artifact ({artifact_repo})" if is_artifact else normalize_url(url)
        formatted_initial_size = format_size(file_size_override) if file_size_override > 0 else "Querying size..."

        init_card = (
            "⏳ **INGESTING URL PAYLOAD**\n"
            "──────────────────────────────\n"
            f"🔗 **Source:** `{source_label}`\n"
            f"📄 **Target:** `{initial_name}`\n"
            f"📦 **Filesize:** `{formatted_initial_size}`\n"
            "⚡ **Status:** Connecting to remote server..."
        )

        if not status_msg:
            status_msg = await msg.reply(init_card)
        else:
            await self.tg.safe_edit_message(status_msg, init_card)

        tmp_dir = tempfile.gettempdir()
        temp_download_target = os.path.join(tmp_dir, f"dl_{int(time.time())}_{sanitize_filename(initial_name)}")
        final_file_path = temp_download_target
        cleanup_paths = [temp_download_target]

        last_dl_update_ts = [0.0]
        dl_start_time = time.time()
        dl_speed_tracker = SpeedTracker(alpha=0.3)
        loop = asyncio.get_running_loop()

        def download_progress_hook(current_bytes: int, total_bytes: int):
            now = time.time()
            if (now - last_dl_update_ts[0] > 3.0) or (total_bytes > 0 and current_bytes >= total_bytes):
                last_dl_update_ts[0] = now
                pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                speed = dl_speed_tracker.update(current_bytes)
                if speed <= 0:
                    elapsed = max(0.1, now - dl_start_time)
                    speed = current_bytes / elapsed
                remaining_bytes = max(0, total_bytes - current_bytes) if total_bytes > 0 else 0
                eta = (remaining_bytes / speed) if speed > 0 and total_bytes > 0 else 0

                total_str = format_size(total_bytes) if total_bytes > 0 else "Unknown size"
                source_title = "GITHUB ARTIFACT" if is_artifact else "REMOTE URL"
                card = (
                    f"⬇️ **DOWNLOADING FROM {source_title}**\n"
                    "──────────────────────────────\n"
                    f"📄 **File:** `{initial_name}`\n"
                    f"📦 **Received:** `{format_size(current_bytes)}` / `{total_str}`\n"
                    f"⚡ **Speed:** `{format_size(int(speed))}/s`  •  ⏳ **ETA:** `{format_eta(eta)}`\n"
                    f"📊 **Progress:** `{render_progress_bar(pct)}`"
                )
                asyncio.run_coroutine_threadsafe(
                    self.tg.safe_edit_message(status_msg, card), loop
                )

        try:
            # Phase 1: Download Ingestion
            final_filename = initial_name
            extracted_single_file = False

            if is_artifact:
                if not temp_download_target.lower().endswith(".zip"):
                    temp_download_target += ".zip"
                    cleanup_paths.append(temp_download_target)

                success, err_msg = await self.gh.download_artifact_zip(
                    artifact_repo, artifact_id, temp_download_target, download_progress_hook
                )
                if not success:
                    raise RuntimeError(f"Artifact download failed: {err_msg}")

                # Unzip artifact archive and upload only the file inside
                unzip_res = extract_single_file_from_zip(temp_download_target, tmp_dir)
                if unzip_res:
                    final_file_path, extracted_name, extracted_size, ext_dest_dir = unzip_res
                    final_filename = extracted_name
                    file_size = extracted_size
                    cleanup_paths.extend([final_file_path, ext_dest_dir])
                    extracted_single_file = True
                    logger.info(f"Unzipped artifact archive: extracted '{final_filename}' ({format_size(file_size)})")
                else:
                    raise RuntimeError("Failed to unzip artifact: archive contains no valid files.")

            else:
                # Generic HTTP/HTTPS URL
                success, err_msg, detected_name, total_bytes = await self.gh.download_stream_url(
                    url, temp_download_target, download_progress_hook
                )
                if not success:
                    raise RuntimeError(f"URL download failed: {err_msg}")

                downloaded_name = sanitize_filename(detected_name or file_name_override or "downloaded_file.bin")
                final_file_path = temp_download_target
                final_filename = downloaded_name

                # If zip archive, unzip it and upload only the file inside
                if downloaded_name.lower().endswith(".zip") or (not downloaded_name.lower().endswith(".ipa") and zipfile.is_zipfile(temp_download_target)):
                    unzip_res = extract_single_file_from_zip(temp_download_target, tmp_dir)
                    if unzip_res:
                        final_file_path, extracted_name, extracted_size, ext_dest_dir = unzip_res
                        final_filename = extracted_name
                        file_size = extracted_size
                        cleanup_paths.extend([final_file_path, ext_dest_dir])
                        extracted_single_file = True
                        logger.info(f"Unzipped URL payload: extracted '{final_filename}' ({format_size(file_size)})")

            if not os.path.exists(final_file_path):
                raise RuntimeError("Downloaded payload not found on disk.")

            file_size = os.path.getsize(final_file_path)
            formatted_total_size = format_size(file_size)
            download_duration = max(0.1, time.time() - dl_start_time)

            await self.tg.safe_edit_message(
                status_msg,
                "☁️ **STREAMING TO DROPBOX**\n"
                "──────────────────────────────\n"
                f"📄 **Filename:** `{final_filename}`\n"
                f"📦 **Filesize:** `{formatted_total_size}`\n"
                f"⏱️ **Download Time:** `{download_duration:.1f}s`\n"
                "⚡ **Status:** Initializing cloud transfer...",
            )

            # Phase 2: Chunked Upload to Dropbox
            dropbox_target_path = f"{self.config.dropbox_target_folder.rstrip('/')}/{final_filename}"
            upload_start_time = time.time()
            last_ul_update_ts = [0.0]
            ul_speed_tracker = SpeedTracker(alpha=0.3)

            def dropbox_progress_hook(current_bytes: int, total_bytes: int):
                now = time.time()
                if (now - last_ul_update_ts[0] > 3.0) or (current_bytes >= total_bytes):
                    last_ul_update_ts[0] = now
                    pct = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                    speed = ul_speed_tracker.update(current_bytes)
                    if speed <= 0:
                        elapsed = max(0.1, now - upload_start_time)
                        speed = current_bytes / elapsed
                    remaining_bytes = max(0, total_bytes - current_bytes)
                    eta = (remaining_bytes / speed) if speed > 0 else 0

                    card = (
                        "☁️ **STREAMING TO DROPBOX**\n"
                        "──────────────────────────────\n"
                        f"📄 **Filename:** `{final_filename}`\n"
                        f"📦 **Uploaded:** `{format_size(current_bytes)}` / `{formatted_total_size}`\n"
                        f"⚡ **Speed:** `{format_size(int(speed))}/s`  •  ⏳ **ETA:** `{format_eta(eta)}`\n"
                        f"📊 **Progress:** `{render_progress_bar(pct)}`"
                    )
                    asyncio.run_coroutine_threadsafe(
                        self.tg.safe_edit_message(status_msg, card), loop
                    )

            shared_url, pruned_items = await asyncio.to_thread(
                self.dbx.upload_file_chunked,
                final_file_path,
                dropbox_target_path,
                self.config.dropbox_target_folder,
                self.config.chunk_size_mb,
                dropbox_progress_hook,
            )

            upload_duration = max(0.1, time.time() - upload_start_time)
            total_duration = time.time() - dl_start_time

            dl_speed = file_size / download_duration if download_duration > 0 else 0
            ul_speed = file_size / upload_duration if upload_duration > 0 else 0

            completion_card = (
                "✅ **TRANSFER COMPLETE**\n"
                "──────────────────────────────\n"
                f"📄 **Filename:** `{final_filename}`\n"
                f"📦 **Payload Size:** `{formatted_total_size}`\n"
                f"📂 **Cloud Vault:** `{self.config.dropbox_target_folder}`\n"
            )
            if is_artifact:
                completion_card += f"🔗 **Source:** GitHub Actions Artifact (`{artifact_repo}`)\n"
                if extracted_single_file:
                    completion_card += "📦 *Extracted single binary from artifact zip archive.*\n"
                completion_card += "\n"
            else:
                completion_card += f"🔗 **Source:** Remote Web Link\n\n"

            completion_card += (
                "⏱️ **Performance Metrics**\n"
                f"• ⬇️ **Ingest Time:** `{download_duration:.1f}s` (`{format_size(int(dl_speed))}/s`)\n"
                f"• ☁️ **Dropbox Push:** `{upload_duration:.1f}s` (`{format_size(int(ul_speed))}/s`)\n"
                f"• ⏱️ **Total Elapsed:** `{total_duration:.1f}s`\n"
            )

            if pruned_items:
                pruned_str = ", ".join([f"`{name}`" for name in pruned_items])
                completion_card += (
                    f"\n♻️ **Retention Auto-Rotation (Cap: {self.config.max_files_in_folder})**\n"
                    f"• Pruned oldest: {pruned_str}\n"
                )

            if shared_url:
                await self.tg.safe_edit_message(
                    status_msg,
                    completion_card,
                    buttons=[[Button.url("🌐 Open in Dropbox", shared_url)]],
                    link_preview=False,
                )

                # Direct 1-tap clipboard copy via Telegram Bot API v7.0+
                await asyncio.to_thread(
                    apply_native_copy_button,
                    self.config.telegram_bot_token,
                    target_chat_id,
                    status_msg.id,
                    shared_url,
                )
            else:
                completion_card += "\nℹ️ *Payload securely archived in Dropbox vault.*"
                await self.tg.safe_edit_message(status_msg, completion_card, buttons=None, link_preview=False)

            self.session_transfers_count += 1
            self.session_transfers_bytes += file_size
            log_file = mask_filename(final_filename, self.config.privacy_mode)
            logger.info(f"URL sync complete: '{log_file}' ({formatted_total_size}) in {total_duration:.1f}s")

        except Exception as exc:
            log_file = mask_filename(initial_name, self.config.privacy_mode)
            logger.error(f"URL Pipeline Failure for '{log_file}': {exc}", exc_info=True)
            failure_card = (
                "❌ **TRANSFER FAILED**\n"
                "──────────────────────────────\n"
                f"📄 **Target:** `{initial_name}`\n"
                f"⚠️ **Error Details:** `{str(exc)}`\n"
                "──────────────────────────────\n"
                "💡 *Verify the link is active, credentials/tokens are valid, or retry.*"
            )
            await self.tg.safe_edit_message(status_msg, failure_card)
        finally:
            for p in cleanup_paths:
                if os.path.exists(p):
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass

    def register_event_handlers(self):
        """Registers all Telethon event handlers for commands, interactive build flow, and media."""

        @self.tg.client.on(events.CallbackQuery)
        async def on_callback_query(event):
            sender = await event.get_sender()
            user_id = sender.id if sender else 0
            if not self.config.is_authorized(user_id):
                await event.answer("Unauthorized Access", alert=True)
                return

            data = event.data.decode("utf-8")
            msg = await event.get_message()
            chat_id = event.chat_id or (msg.chat_id if msg else user_id)

            # 1. Action: Cancel
            if data in ["cancel", "build_cancel"]:
                await event.answer("Build cancelled.")
                self.user_dashboards.pop(user_id, None)
                self.pending_inputs.pop(user_id, None)
                await event.edit(
                    "🚫 **BUILD REQUEST CANCELLED**\n──────────────────────────────\nNo workflow dispatch was initiated.",
                    buttons=None,
                )
                return

            # 2. Action: Return to Main Menu
            if data in ["menu", "build_menu"]:
                await event.answer()
                menu_text, menu_buttons = render_main_menu()
                await event.edit(menu_text, buttons=menu_buttons)
                return

            # 3. Action: Select Target from Main Menu
            if data.startswith("sel:") or data.startswith("build_select:"):
                target_key = data.split(":")[1]
                target = get_target(target_key)
                if not target:
                    await event.answer("Unknown target.")
                    return

                await event.answer(f"Selected {target['name']}")
                exts = get_extensions(target_key)
                default_mask_hex = hex((1 << len(exts)) - 1)[2:]

                initial_state = {
                    "targetKey": target_key,
                    "dashMsgId": msg.id,
                    "chatId": chat_id,
                    "ipa": "",
                    "name": target.get("defaultInputs", {}).get("display_name", "DexTube"),
                    "bundle": target.get("defaultInputs", {}).get("bundle_id", "com.google.ios.youtube"),
                    "tweak": "",
                    "maskHex": default_mask_hex,
                }
                self.user_dashboards[user_id] = initial_state

                await event.edit(
                    render_dashboard_text(initial_state),
                    buttons=render_dashboard_buttons(initial_state),
                )
                return

            # 4. Action: Open Extensions Toggle Menu
            if data.startswith("ext:") or data.startswith("open_exts:"):
                parts = data.split(":")
                target_key = parts[1]
                target = get_target(target_key)
                if not target or not target.get("hasExtensions"):
                    await event.answer("No extensions available.")
                    return

                await event.answer(f"Editing {target['name']} extensions")
                state = self.user_dashboards.get(user_id) or {"targetKey": target_key, "maskHex": "1fff"}
                mask_hex = state.get("maskHex", "1fff")
                kb = render_extensions_keyboard(target_key, mask_hex)

                card = (
                    f"⚙️ **CONFIGURE EXTENSIONS: {target['name']}**\n"
                    f"──────────────────────────────\n"
                    f"📦 **Repository:** `{target['repo']}`\n"
                    f"• 🏷️ **App Name:** `{state.get('name', 'DexTube')}`\n"
                    f"• 🆔 **Bundle ID:** `{state.get('bundle', 'com.google.ios.youtube')}`\n"
                    f"──────────────────────────────\n"
                    f"Tap any extension below to toggle it **On (✅)** or **Off (❌)**.\n"
                    f"When satisfied, tap **[ 💾 Save & Back ]** below:"
                )
                await event.edit(card, buttons=kb)
                return

            # 5. Action: Toggle Individual Extension
            if data.startswith("tgl:"):
                parts = data.split(":")
                target_key = parts[1]
                # support both tgl:target:extIdx:mask and tgl:target:dashMsgId:extIdx:mask
                if len(parts) == 5:
                    ext_idx = int(parts[3])
                    mask_hex = parts[4]
                else:
                    ext_idx = int(parts[2])
                    mask_hex = parts[3] if len(parts) > 3 else "1fff"

                exts = get_extensions(target_key)
                current_mask = int(mask_hex, 16)
                new_mask = current_mask ^ (1 << ext_idx)
                new_mask_hex = hex(new_mask)[2:]

                state = self.user_dashboards.get(user_id) or {"targetKey": target_key}
                state["maskHex"] = new_mask_hex
                self.user_dashboards[user_id] = state

                new_kb = render_extensions_keyboard(target_key, new_mask_hex)
                await event.edit(buttons=new_kb)

                ext_name = exts[ext_idx]["name"] if ext_idx < len(exts) else f"Ext #{ext_idx}"
                is_on = (new_mask & (1 << ext_idx)) != 0
                await event.answer(f"{ext_name}: {'Enabled ✅' if is_on else 'Disabled ❌'}")
                return

            # 6. Action: Toggle All
            if data.startswith("tgl_all:"):
                parts = data.split(":")
                target_key = parts[1]
                mask_hex = parts[-1]
                exts = get_extensions(target_key)
                full_mask = (1 << len(exts)) - 1
                current_mask = int(mask_hex, 16)

                new_mask = full_mask if current_mask == 0 else 0
                new_mask_hex = hex(new_mask)[2:]

                state = self.user_dashboards.get(user_id) or {"targetKey": target_key}
                state["maskHex"] = new_mask_hex
                self.user_dashboards[user_id] = state

                new_kb = render_extensions_keyboard(target_key, new_mask_hex)
                await event.edit(buttons=new_kb)
                await event.answer("All extensions enabled ✅" if new_mask > 0 else "All extensions disabled ❌")
                return

            # 7. Action: Reset Extensions
            if data.startswith("tgl_rst:") or data.startswith("tgl_reset:"):
                target_key = data.split(":")[1]
                exts = get_extensions(target_key)
                full_mask_hex = hex((1 << len(exts)) - 1)[2:]

                state = self.user_dashboards.get(user_id) or {"targetKey": target_key}
                state["maskHex"] = full_mask_hex
                self.user_dashboards[user_id] = state

                new_kb = render_extensions_keyboard(target_key, full_mask_hex)
                await event.edit(buttons=new_kb)
                await event.answer("Reset: All extensions enabled ✅")
                return

            # 8. Action: Extensions Done / Return to Dashboard
            if data.startswith("ext_done:"):
                parts = data.split(":")
                target_key = parts[1]
                mask_hex = parts[-1]
                state = self.user_dashboards.get(user_id) or {"targetKey": target_key}
                state["maskHex"] = mask_hex
                self.user_dashboards[user_id] = state

                exts = get_extensions(target_key)
                decoded = decode_bitmask(mask_hex, exts)

                await event.answer(f"Extensions saved ({decoded['enabled_count']}/{decoded['total_count']})")
                await event.edit(
                    render_dashboard_text(state),
                    buttons=render_dashboard_buttons(state),
                )
                return

            # 9. Action: Ask for Input (IPA, Name, Bundle, Tweak)
            if data.startswith("ask:") or data.startswith("input_ask:"):
                parts = data.split(":")
                field = parts[1]
                target_key = parts[2]
                target = get_target(target_key) or BUILD_TARGETS["dtkace"]
                state = self.user_dashboards.get(user_id) or {
                    "targetKey": target_key,
                    "dashMsgId": msg.id,
                    "chatId": chat_id,
                    "ipa": "",
                    "name": target.get("defaultInputs", {}).get("display_name", "DexTube"),
                    "bundle": target.get("defaultInputs", {}).get("bundle_id", "com.google.ios.youtube"),
                    "tweak": "",
                    "maskHex": "1fff",
                }

                if field == "ipa":
                    prompt_label = (
                        f"🔗 **INPUT: DECRYPTED IPA URL**\n──────────────────────────────\n"
                        f"Target: `{target['name']}`\n\n"
                        f"Please reply with the direct download URL for the decrypted IPA file."
                    )
                    placeholder = "Paste direct IPA download URL..."
                elif field == "name":
                    prompt_label = (
                        f"🏷️ **INPUT: APP DISPLAY NAME**\n──────────────────────────────\n"
                        f"Target: `{target['name']}`\nCurrent: `{state.get('name')}`\n\n"
                        f"Please reply with your desired app name (e.g. `My YouTube`)."
                    )
                    placeholder = "e.g. My YouTube"
                elif field == "bundle":
                    prompt_label = (
                        f"🆔 **INPUT: BUNDLE IDENTIFIER**\n──────────────────────────────\n"
                        f"Target: `{target['name']}`\nCurrent: `{state.get('bundle')}`\n\n"
                        f"Please reply with your desired bundle identifier (e.g. `com.my.youtube`)."
                    )
                    placeholder = "e.g. com.my.youtube"
                elif field == "tweak":
                    prompt_label = (
                        f"💉 **INPUT: CUSTOM TWEAK URL**\n──────────────────────────────\n"
                        f"Target: `{target['name']}`\nCurrent: `{state.get('tweak') or 'Default (built-in)'}`\n\n"
                        f"Please reply with a direct link to your custom deb/dylib, or type `default` to clear."
                    )
                    placeholder = "Paste custom tweak URL or type default"
                else:
                    return

                await event.answer(f"Enter {field.upper()}...")
                prompt_msg = await event.respond(
                    f"{prompt_label}\n\n👉 *Reply directly with your value (or type /cancel to abort):*",
                    reply_to=msg.id,
                    buttons=Button.force_reply(single_use=True, selective=True, placeholder=placeholder),
                )

                state["dashMsgId"] = msg.id
                self.user_dashboards[user_id] = state

                self.pending_inputs[user_id] = {
                    "field": field,
                    "targetKey": target_key,
                    "dashMsgId": msg.id,
                    "promptMsgId": prompt_msg.id,
                    "chatId": chat_id,
                }
                return

            # 10. Action: Trigger Build Now
            if data.startswith("trig:") or data.startswith("input_trigger:"):
                target_key = data.split(":")[1]
                target = get_target(target_key) or BUILD_TARGETS["dtkace"]
                state = self.user_dashboards.get(user_id) or {"targetKey": target_key}

                if not state.get("ipa"):
                    await event.answer("⚠️ Please set the IPA URL first by tapping [ 🔗 Set IPA URL ]!", alert=True)
                    return

                await event.answer("🚀 Dispatching GitHub Actions...")
                try:
                    await event.edit(
                        f"⏳ **DISPATCHING WORKFLOW...**\n──────────────────────────────\n"
                        f"📦 **Target:** `{target['name']}`\n"
                        f"🛰️ **Repository:** `{target['repo']}`\n"
                        f"📄 **Workflow:** `{target['workflow']}`\n"
                        f"🔗 **IPA URL:** `{state.get('ipa')}`\n\n"
                        f"*Connecting to GitHub Actions API...*",
                        buttons=None,
                    )
                except Exception:
                    pass

                inputs = self.compile_workflow_inputs(state, target)
                success, status_code, err_msg = await self.gh.trigger_workflow_dispatch(
                    target["repo"], target["workflow"], inputs
                )

                if success:
                    self.user_dashboards.pop(user_id, None)
                    start_time = time.time()

                    await asyncio.sleep(2.5)
                    latest = await self.gh.get_latest_workflow_run(target["repo"])
                    run_id = latest.get("id") if latest else None
                    run_url = latest.get("html_url") if latest else f"https://github.com/{target['repo']}/actions"

                    card, btns = render_build_tracking_card(target, run_id, "queued", 3.0, run_url)
                    await event.edit(card, buttons=btns)

                    # Engage background tracking loop
                    asyncio.create_task(self.track_workflow_progress(chat_id, msg.id, target, run_id, start_time))
                else:
                    fail_card = (
                        f"❌ **WORKFLOW DISPATCH FAILED**\n"
                        f"──────────────────────────────\n"
                        f"📦 **Repository:** `{target['repo']}`\n"
                        f"📄 **Workflow:** `{target['workflow']}`\n"
                        f"⚠️ **Status Code:** HTTP `{status_code}`\n"
                        f"📝 **Error Details:** `{err_msg}`\n"
                        f"──────────────────────────────\n"
                        f"💡 *Please verify that your GH_PAT secret has 'repo' or 'actions:write' permissions.*"
                    )
                    await event.edit(fail_card)
                return

            # 11. Action: Build from Detected URL Card
            if data.startswith("url_build:"):
                target_key = data.split(":")[1]
                target = get_target(target_key) or BUILD_TARGETS["dtkace"]
                raw_url = ""
                if msg and msg.raw_text:
                    m = re.search(r"URL:\s*`([^`]+)`", msg.raw_text)
                    if m:
                        raw_url = m.group(1).strip()

                exts = get_extensions(target_key)
                initial_state = {
                    "targetKey": target_key,
                    "dashMsgId": msg.id,
                    "chatId": chat_id,
                    "ipa": raw_url,
                    "name": target.get("defaultInputs", {}).get("display_name", "DexTube"),
                    "bundle": target.get("defaultInputs", {}).get("bundle_id", "com.google.ios.youtube"),
                    "tweak": "",
                    "maskHex": hex((1 << len(exts)) - 1)[2:],
                }
                self.user_dashboards[user_id] = initial_state
                await event.answer(f"Configuring {target['name']}")
                await event.edit(
                    render_dashboard_text(initial_state),
                    buttons=render_dashboard_buttons(initial_state),
                )
                return

        @self.tg.client.on(events.NewMessage)
        async def on_new_message(event):
            msg = event.message
            if not getattr(msg, "is_private", True):
                return

            sender = await msg.get_sender()
            user_id = sender.id if sender else 0
            chat_id = msg.chat_id or user_id

            if not self.config.is_authorized(user_id):
                return

            raw_text = (getattr(msg, "raw_text", "") or "").strip()
            raw_lower = raw_text.lower()
            reply_msg = await msg.get_reply_message()

            # 1. /cancel command
            if raw_lower in ["/cancel", "cancel"]:
                pending = self.pending_inputs.pop(user_id, None)
                try:
                    await msg.delete()
                except Exception:
                    pass

                prompt_id = pending.get("promptMsgId") if pending else (reply_msg.id if reply_msg else None)
                if prompt_id:
                    try:
                        await self.tg.client.delete_messages(chat_id, prompt_id)
                    except Exception:
                        pass
                return

            # 2. Reply to Input Prompt
            pending = self.pending_inputs.get(user_id)
            if pending and not msg.media and not raw_text.startswith("/"):
                field = pending["field"]
                target_key = pending["targetKey"]
                dash_msg_id = pending["dashMsgId"]
                prompt_msg_id = pending["promptMsgId"]
                clean_val = raw_text.strip()

                state = self.user_dashboards.get(user_id) or {
                    "targetKey": target_key,
                    "dashMsgId": dash_msg_id,
                    "chatId": chat_id,
                    "ipa": "",
                    "name": "DexTube",
                    "bundle": "com.google.ios.youtube",
                    "tweak": "",
                    "maskHex": "1fff",
                }

                if field == "ipa":
                    url_match = re.search(r"https?://[^\s<>\"]+", clean_val)
                    if not url_match:
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        warn = await msg.respond("⚠️ **INVALID URL**: Please provide a valid `http://` or `https://` link.")
                        await asyncio.sleep(4)
                        try:
                            await warn.delete()
                        except Exception:
                            pass
                        return
                    state["ipa"] = normalize_url(url_match.group(0))
                elif field == "name":
                    state["name"] = clean_val
                elif field == "bundle":
                    state["bundle"] = clean_val
                elif field == "tweak":
                    if clean_val.lower() in ["default", "none", "clear"]:
                        state["tweak"] = ""
                    else:
                        url_match = re.search(r"https?://[^\s<>\"]+", clean_val)
                        state["tweak"] = normalize_url(url_match.group(0)) if url_match else clean_val

                self.user_dashboards[user_id] = state
                self.pending_inputs.pop(user_id, None)

                # Clean chat: Delete user reply and prompt
                try:
                    await msg.delete()
                except Exception:
                    pass
                if prompt_msg_id:
                    try:
                        await self.tg.client.delete_messages(chat_id, prompt_msg_id)
                    except Exception:
                        pass

                # Update dashboard in-place
                if dash_msg_id:
                    try:
                        dash_msg = await self.tg.client.get_messages(chat_id, ids=dash_msg_id)
                        if dash_msg:
                            await dash_msg.edit(
                                render_dashboard_text(state),
                                buttons=render_dashboard_buttons(state),
                            )
                    except Exception as e:
                        logger.warning(f"Could not edit dashboard message {dash_msg_id}: {e}")
                return

            # 3. Direct bare IPA link detected in chat
            if not msg.media and not raw_text.startswith("/"):
                url_match = re.search(r"https?://[^\s<>\"]+", raw_text)
                if url_match:
                    raw_url = normalize_url(url_match.group(0))
                    prompt_buttons = [
                        [
                            Button.inline("🚀 Build DTKACE Plus", b"url_build:dtkace"),
                            Button.inline("✨ Build DTLite Plus", b"url_build:dtlite"),
                        ],
                        [
                            Button.inline("🎵 Build DTMusicUltimate", b"url_build:dtmusic"),
                        ],
                        [
                            Button.inline("❌ Dismiss", b"cancel"),
                        ],
                    ]
                    await msg.reply(
                        f"🔗 **IPA LINK DETECTED**\n──────────────────────────────\n"
                        f"URL: `{raw_url}`\n\n"
                        f"Choose which app you want to build with this link:",
                        buttons=prompt_buttons,
                    )
                    return

            # 4. Command: /build
            if raw_text.startswith("/build"):
                args = raw_text.strip().split()
                if len(args) >= 3 and get_target(args[1]):
                    target = get_target(args[1])
                    ipa_url = normalize_url(args[2])
                    exts = get_extensions(target["key"])
                    state = {
                        "targetKey": target["key"],
                        "ipa": ipa_url,
                        "name": target.get("defaultInputs", {}).get("display_name", "DexTube"),
                        "bundle": target.get("defaultInputs", {}).get("bundle_id", "com.google.ios.youtube"),
                        "tweak": "",
                        "maskHex": hex((1 << len(exts)) - 1)[2:],
                    }
                    status_msg = await msg.reply(
                        f"⏳ **DISPATCHING WORKFLOW...**\n──────────────────────────────\n"
                        f"📦 **Target:** `{target['name']}`\n"
                        f"📄 **Workflow:** `{target['workflow']}`\n"
                        f"🔗 **IPA URL:** `{ipa_url}`"
                    )
                    inputs = self.compile_workflow_inputs(state, target)
                    success, status_code, err_msg = await self.gh.trigger_workflow_dispatch(
                        target["repo"], target["workflow"], inputs
                    )
                    if success:
                        card = (
                            f"✅ **GITHUB ACTION TRIGGERED!**\n"
                            f"──────────────────────────────\n"
                            f"🚀 **Target:** `{target['name']}`\n"
                            f"📦 **Repository:** `{target['repo']}`\n"
                            f"📄 **Workflow:** `{target['workflow']}`\n"
                            f"🔗 **IPA URL:** `{ipa_url}`\n"
                            f"──────────────────────────────\n"
                            f"⚡ **Runner State:** Queued on macOS runner"
                        )
                        btn = [[Button.url("🌐 View Workflow on GitHub", f"https://github.com/{target['repo']}/actions")]]
                        await status_msg.edit(card, buttons=btn)
                    else:
                        await status_msg.edit(f"❌ **DISPATCH FAILED** (HTTP {status_code}): `{err_msg}`")
                    return

                # Interactive App Selection Menu
                menu_text, menu_buttons = render_main_menu()
                sent_dash = await msg.reply(menu_text, buttons=menu_buttons)
                self.user_dashboards[user_id] = {
                    "dashMsgId": sent_dash.id,
                    "chatId": chat_id,
                    "targetKey": "dtkace",
                    "ipa": "",
                    "maskHex": "1fff",
                }
                return

            # 5. Command: /ping
            if raw_text in ["/ping"]:
                t0 = time.time()
                sent = await msg.reply("⚡ `Pinging host runner...`")
                latency_ms = max(1, int((time.time() - t0) * 1000))
                ping_card = (
                    "⚡ **GATEWAY PONG**\n"
                    "──────────────────────────────\n"
                    f"⏱️ **Round-Trip Latency:** `{latency_ms} ms`\n"
                    "🛰️ **Compute Host:** `Active Runner (Python 3.11)`\n"
                    "🟢 **Engine Health:** `Operational (100%)`\n"
                    f"🤖 **Bot Client:** `@{self.tg.bot_username}`"
                )
                await self.tg.safe_edit_message(sent, ping_card)
                return

            # 6. Command: /status, /info
            if raw_text in ["/status", "/info"]:
                elapsed = int(time.time() - self.start_timestamp)
                status_card = (
                    "📊 **SYSTEM & CLOUD HEALTH MONITOR**\n"
                    "──────────────────────────────\n"
                    "🟢 **Daemon State:** `Online & Operational`\n"
                    f"⏱️ **Session Uptime:** `{format_eta(elapsed)}`\n"
                    f"📁 **Dropbox Target:** `{self.config.dropbox_target_folder}`\n"
                    f"📦 **Retention Cap:** `{self.config.max_files_in_folder} files max`\n"
                    f"🚀 **Workflow Builder:** Active (`/build`)\n"
                    f"📈 **Transfers Completed:** `{self.session_transfers_count} files` (`{format_size(self.session_transfers_bytes)}`)"
                )
                await msg.reply(status_card)
                return

            # 7. Command: /start, /help
            if raw_text in ["/start", "/help"]:
                help_card = (
                    "⚡ **TELEGRAM TO DROPBOX SYNC & BUILD ENGINE**\n"
                    "──────────────────────────────\n"
                    "📥 **Quick Transfer:** Forward or upload any media file up to 2.0 GB.\n"
                    "🚀 **iOS Workflow Builder:** Use `/build` to configure tweaks & trigger builds.\n\n"
                    "✨ **Available Commands:**\n"
                    "• `/build` — Configure parameters & trigger GitHub Actions builds\n"
                    "• `/status` — View real-time runner status & health\n"
                    "• `/ping` — Measure network round-trip latency\n"
                    "• `/stop` — Safely disconnect runner\n"
                    "• `/cancel` — Cancel active input prompt\n"
                    "• `/help` — Display this guide\n"
                    "──────────────────────────────\n"
                    "🟢 **Status:** Armed and ready."
                )
                await msg.reply(help_card)
                return

            # 8. Command: /stop, /shutdown, /kill
            if raw_text in ["/stop", "/shutdown", "/kill"]:
                elapsed = int(time.time() - self.start_timestamp)
                stop_card = (
                    "🛑 **RUNNER SHUTDOWN INITIATED**\n"
                    "──────────────────────────────\n"
                    f"⏱️ **Session Duration:** `{format_eta(elapsed)}`\n"
                    f"📦 **Transfers Completed:** `{self.session_transfers_count} files` (`{format_size(self.session_transfers_bytes)}`)\n"
                    "──────────────────────────────\n"
                    "✅ Daemon disconnecting and terminating cleanly."
                )
                await msg.reply(stop_card)
                self.shutdown_event.set()
                await self.tg.disconnect()
                return

            # 8.5 Handle Dropped Links / URLs in Daemon Mode
            if not msg.media and raw_text:
                url_match = re.search(r"https?://[^\s<>\"]+", raw_text)
                if url_match:
                    raw_url = normalize_url(url_match.group(0))
                    await self.process_url_payload(raw_url, msg)
                    return

            # 9. Handle Media Uploads
            if msg.media:
                await self.process_media_message(msg)

    async def run_on_demand(self, chat_id: int, message_id: int, dispatch_msg_id: Optional[int] = None):
        """Executes targeted on-demand sync dispatched by Cloudflare Worker."""
        await self.tg.start()
        self.dbx.initialize()

        bot_display = "@[PROTECTED]" if self.config.privacy_mode else f"@{self.tg.bot_username}"
        dbx_display = "[PROTECTED/MASKED]" if self.config.privacy_mode else self.dbx.account_name
        folder_display = "[PROTECTED_VAULT]" if self.config.privacy_mode else self.config.dropbox_target_folder

        logger.info("┌" + "─" * 68 + "┐")
        logger.info("│ ⚡ ON-DEMAND DISPATCH ENGINE (SERVERLESS RUNNER)                │")
        logger.info("├" + "─" * 68 + "┤")
        logger.info(f"│ • Telegram Bot:      {bot_display:<46} │")
        logger.info(f"│ • Dropbox Account:   {dbx_display:<46} │")
        logger.info(f"│ • Target Directory:  {folder_display:<46} │")
        logger.info(f"│ • Target Chat ID:    {str(chat_id):<46} │")
        logger.info(f"│ • Target Message ID: {str(message_id):<46} │")
        logger.info("└" + "─" * 68 + "┘")

        try:
            target_msg = await self.tg.client.get_messages(chat_id, ids=message_id)
            if target_msg:
                logger.info("Target payload acquired. Commencing ingestion...")
                if self.config.download_url:
                    await self.process_url_payload(
                        self.config.download_url,
                        target_msg,
                        dispatch_msg_id=dispatch_msg_id,
                        is_artifact=self.config.is_artifact,
                        artifact_id=self.config.artifact_id,
                        artifact_repo=self.config.artifact_repo,
                        file_name_override=self.config.file_name,
                        file_size_override=self.config.file_size,
                    )
                elif target_msg.media:
                    await self.process_media_message(target_msg, dispatch_msg_id=dispatch_msg_id)
                else:
                    url_match = re.search(r"https?://[^\s<>\"]+", target_msg.text or "")
                    if url_match:
                        raw_url = normalize_url(url_match.group(0))
                        await self.process_url_payload(raw_url, target_msg, dispatch_msg_id=dispatch_msg_id)
                    else:
                        logger.warning(f"Target message {message_id} in chat {chat_id} has neither media nor URL.")
            else:
                logger.warning(f"Target message {message_id} not found in chat {chat_id}.")
        except Exception as err:
            logger.error(f"Failed to fetch/process targeted message: {err}", exc_info=True)

        if self.config.idle_keep_alive_seconds > 0:
            logger.info(f"Keep-alive active: Monitoring for {self.config.idle_keep_alive_seconds}s...")
            while not self.shutdown_event.is_set():
                if (time.time() - self.last_activity_timestamp) >= self.config.idle_keep_alive_seconds:
                    break
                await asyncio.sleep(2)

        await self.tg.disconnect()
        logger.info("On-demand session finished. Disconnected cleanly.")

    async def run_tracker(self, chat_id: int, message_id: int, target_key: str, run_id: Optional[int], start_time: float):
        """Runs dedicated build tracking mode in CI."""
        await self.tg.start()
        target = get_target(target_key) or BUILD_TARGETS["dtkace"]

        logger.info("┌" + "─" * 68 + "┐")
        logger.info("│ ⚡ GITHUB ACTIONS BUILD TRACKER RUNNER ACTIVATED                 │")
        logger.info("├" + "─" * 68 + "┤")
        logger.info(f"│ • Target Repo:       {target['repo']:<46} │")
        logger.info(f"│ • Target Name:       {target['name']:<46} │")
        logger.info(f"│ • Workflow Run ID:   {str(run_id or 'Auto-detect'):<46} │")
        logger.info(f"│ • Target Chat ID:    {str(chat_id):<46} │")
        logger.info(f"│ • Target Message ID: {str(message_id):<46} │")
        logger.info("└" + "─" * 68 + "┘")

        await self.track_workflow_progress(chat_id, message_id, target, run_id, start_time)
        await self.tg.disconnect()
        logger.info("Build Tracker Runner completed cleanly.")

    async def run_daemon(self):
        """Runs client continuously in daemon mode for local development or VPS."""
        await self.tg.start()
        self.dbx.initialize()
        self.register_event_handlers()

        logger.info("┌" + "─" * 68 + "┐")
        logger.info("│ ⚡ STANDALONE DAEMON MODE (LOCAL / PERSISTENT)                   │")
        logger.info("├" + "─" * 68 + "┤")
        logger.info(f"│ • Telegram Bot:      @{self.tg.bot_username:<45} │")
        logger.info(f"│ • Dropbox Folder:    {self.config.dropbox_target_folder:<46} │")
        logger.info(f"│ • Retention Cap:     {self.config.max_files_in_folder} files maximum{' ':<31} │")
        logger.info(f"│ • Workflow Builder:  Active (/build){' ':<33} │")
        logger.info("└" + "─" * 68 + "┘")

        await self.tg.client.run_until_disconnected()


def main():
    """Main entrypoint for CLI & CI invocation."""
    from src.config import load_config
    config = load_config()
    setup_logging(config.log_level)

    app = SyncApp(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal():
        logger.info("Shutdown signal received.")
        app.shutdown_event.set()
        loop.create_task(app.tg.disconnect())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        if config.build_target_key and config.target_chat_id and config.target_message_id:
            loop.run_until_complete(
                app.run_tracker(
                    config.target_chat_id,
                    config.target_message_id,
                    config.build_target_key,
                    config.build_run_id,
                    config.build_start_time or time.time(),
                )
            )
        elif config.target_chat_id and config.target_message_id:
            loop.run_until_complete(
                app.run_on_demand(
                    config.target_chat_id,
                    config.target_message_id,
                    dispatch_msg_id=config.dispatch_message_id,
                )
            )
        elif config.is_github_actions:
            logger.info("GitHub Actions triggered without target payload. Exiting cleanly.")
            sys.exit(0)
        else:
            loop.run_until_complete(app.run_daemon())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        logger.error(f"Terminated with error: {exc}", exc_info=True)
    finally:
        loop.close()
