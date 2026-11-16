//! Master Sync Engine, CI Dispatch Runner & Interactive Daemon

use std::collections::HashMap;
use std::fs::File;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tokio::sync::Mutex;
use tracing::{debug, info, warn};

use crate::config::AppConfig;
use crate::constants::{get_extensions, get_target, TARGET_DTKACE};
use crate::dropbox::DropboxService;
use crate::formatters::{
    decode_bitmask, extract_single_file_from_zip, format_eta, format_size, match_rotation_family,
    parse_artifact_url, parse_run_url, render_progress_bar, resolve_dropbox_destination,
    sanitize_filename, SpeedTracker,
};
use crate::github::GitHubService;
use crate::privacy::{mask_filename, mask_user_id};
use crate::telegram::TelegramService;
use crate::ui::{
    render_dashboard_buttons, render_dashboard_text, render_extensions_keyboard, render_help_card,
    render_main_menu, render_ping_card, render_status_card, DashboardState,
};
use crate::version_checker::{
    check_all_ios_versions, format_version_alert_text, format_version_status_text,
    get_version_alert_buttons, get_version_status_buttons, send_telegram_alert,
};

struct ProgressReporter {
    token: String,
    chat_id: i64,
    status_msg_id: i64,
    title: String,
    file_name: String,
    tracker: SpeedTracker,
    last_edit: Instant,
}

impl ProgressReporter {
    fn new(token: String, chat_id: i64, status_msg_id: i64, title: &str, file_name: &str) -> Self {
        Self {
            token,
            chat_id,
            status_msg_id,
            title: title.to_string(),
            file_name: file_name.to_string(),
            tracker: SpeedTracker::new(0.3),
            last_edit: Instant::now() - Duration::from_secs(5),
        }
    }

    fn update(&mut self, current: u64, total: u64) {
        let now = Instant::now();
        if now.duration_since(self.last_edit).as_secs_f64() < 3.0 && total > 0 && current < total {
            return;
        }
        self.last_edit = now;

        let pct = if total > 0 {
            (current as f64 / total as f64) * 100.0
        } else {
            0.0
        };
        let speed = self.tracker.update(current);
        let remaining = total.saturating_sub(current) as f64;
        let eta = if speed > 0.0 && total > 0 {
            remaining / speed
        } else {
            0.0
        };

        let card = format!(
            "⬇️ **{}**\n\
             ──────────────────────────────\n\
             • 📄 **File:**    `{}`\n\
             • 📦 **Volume:**  `{}` / `{}`\n\
             • ⚡ **Speed:**   `{}/s`  •  ⏳ **ETA:** `{}`\n\
             • 📊 **Progress:** {}",
            self.title,
            self.file_name,
            format_size(current),
            if total > 0 {
                format_size(total)
            } else {
                "Unknown".to_string()
            },
            format_size(speed as u64),
            format_eta(eta),
            render_progress_bar(pct, 12)
        );

        let token = self.token.clone();
        let chat_id = self.chat_id;
        let status_msg_id = self.status_msg_id;
        tokio::spawn(async move {
            let tg_client = TelegramService::new(token);
            let _ = tg_client
                .edit_message_text(chat_id, status_msg_id, &card, None)
                .await;
        });
    }
}

/// Request parameters for on-demand or background URL payload ingestion.
#[derive(Debug, Clone, Default)]
pub struct ProcessPayloadRequest<'a> {
    pub raw_url: &'a str,
    pub chat_id: i64,
    pub message_id: i64,
    pub dispatch_msg_id: Option<i64>,
    pub is_artifact: bool,
    pub artifact_id: Option<&'a str>,
    pub artifact_repo: Option<&'a str>,
    pub file_name_override: Option<&'a str>,
    pub file_size_override: u64,
    pub telegram_file_id: Option<&'a str>,
}

#[derive(Debug, Clone)]
pub struct PendingInputPrompt {
    pub field: String,
    pub target_key: String,
    pub dash_msg_id: i64,
}

pub struct SyncApp {
    pub config: AppConfig,
    pub tg: TelegramService,
    pub dbx: DropboxService,
    pub gh: GitHubService,
    user_dashboards: Arc<Mutex<HashMap<i64, DashboardState>>>,
    pending_inputs: Arc<Mutex<HashMap<i64, PendingInputPrompt>>>,
    last_activity: Arc<AtomicU64>,
}

impl SyncApp {
    pub fn new(config: AppConfig) -> Self {
        let tg = TelegramService::new(config.telegram_bot_token.clone());
        let dbx = DropboxService::new(config.clone());
        let gh = GitHubService::new(config.gh_pat.clone());
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        Self {
            config,
            tg,
            dbx,
            gh,
            user_dashboards: Arc::new(Mutex::new(HashMap::new())),
            pending_inputs: Arc::new(Mutex::new(HashMap::new())),
            last_activity: Arc::new(AtomicU64::new(now_sec)),
        }
    }

    fn touch_activity(&self) {
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        self.last_activity.store(now_sec, Ordering::Relaxed);
    }

    pub async fn run_on_demand(
        &mut self,
        chat_id: i64,
        message_id: i64,
        dispatch_msg_id: Option<i64>,
    ) -> Result<(), String> {
        let _ = self.tg.get_me().await;
        let _ = self.dbx.initialize().await;

        let bot_display = if self.config.privacy_mode {
            "@[PROTECTED]".to_string()
        } else {
            format!("@{}", self.tg.bot_username)
        };
        let dbx_display = if self.config.privacy_mode {
            "[PROTECTED/MASKED]".to_string()
        } else {
            self.dbx.account_name.clone()
        };
        let ipa_display = if self.config.privacy_mode {
            "[PROTECTED_VAULT]".to_string()
        } else {
            self.config.dropbox_ipa_folder.clone()
        };
        let deb_display = if self.config.privacy_mode {
            "[PROTECTED_VAULT]".to_string()
        } else {
            self.config.dropbox_deb_folder.clone()
        };

        info!("====================================================================");
        info!("⚡ ON-DEMAND DISPATCH ENGINE (NATIVE RUST CORE)");
        info!("====================================================================");
        info!("• Telegram Bot:      {}", bot_display);
        info!("• Dropbox Account:   {}", dbx_display);
        info!("• IPA Directory:     {}", ipa_display);
        info!("• DEB Directory:     {}", deb_display);
        info!("• Target Chat ID:    {}", chat_id);
        info!("• Target Message ID: {}", message_id);
        info!("====================================================================");

        if let Some(ref raw_url) = self.config.download_url {
            self.process_url_payload(ProcessPayloadRequest {
                raw_url,
                chat_id,
                message_id,
                dispatch_msg_id,
                is_artifact: self.config.is_artifact,
                artifact_id: self.config.artifact_id.as_deref(),
                artifact_repo: self.config.artifact_repo.as_deref(),
                file_name_override: self.config.file_name.as_deref(),
                file_size_override: self.config.file_size,
                ..Default::default()
            })
            .await?;
        } else if let Some(ref file_id) = self.config.telegram_file_id {
            self.process_url_payload(ProcessPayloadRequest {
                raw_url: "",
                chat_id,
                message_id,
                dispatch_msg_id,
                telegram_file_id: Some(file_id),
                file_name_override: self.config.file_name.as_deref(),
                file_size_override: self.config.file_size,
                ..Default::default()
            })
            .await?;
        } else {
            warn!("On-demand invoked without direct URL or Telegram file payload. Awaiting URL or file.");
        }

        Ok(())
    }

    pub async fn process_url_payload(&self, req: ProcessPayloadRequest<'_>) -> Result<(), String> {
        self.touch_activity();

        let chat_id = req.chat_id;
        let message_id = req.message_id;
        let raw_url = req.raw_url;
        let mut is_artifact = req.is_artifact;
        let file_name_override = req.file_name_override;
        let file_size_override = req.file_size_override;

        let status_msg_id = if let Some(disp_id) = req.dispatch_msg_id {
            disp_id
        } else {
            let initial_card = "⏳ **INITIALIZING CLOUD ENGINE**\n\
                                ──────────────────────────────\n\
                                ⚡ *Connecting to runner & pipelines...*";
            self.tg
                .send_message(chat_id, initial_card, Some(message_id), None)
                .await
                .map_err(|e| format!("Failed to create status notice: {}", e))?
        };

        let mut final_artifact_id = req.artifact_id.map(|s| s.to_string());
        let mut final_artifact_repo = req.artifact_repo.map(|s| s.to_string());

        // Pattern matching: GitHub Artifact or Run URL
        if !is_artifact {
            if let Some(art_info) = parse_artifact_url(raw_url) {
                is_artifact = true;
                final_artifact_repo = Some(art_info.repo_full_name);
                final_artifact_id = Some(art_info.artifact_id);
            } else if let Some(run_info) = parse_run_url(raw_url) {
                if let Ok(run_id) = run_info.run_id.parse::<i64>() {
                    let artifacts = self
                        .gh
                        .get_run_artifacts(&run_info.repo_full_name, run_id)
                        .await;
                    if let Some(first_art) = artifacts.first() {
                        is_artifact = true;
                        final_artifact_repo = Some(run_info.repo_full_name);
                        final_artifact_id = Some(first_art.id.to_string());
                    }
                }
            }
        }

        let mut initial_name = file_name_override
            .unwrap_or("downloaded_file.bin")
            .to_string();
        let mut known_size = file_size_override;

        if is_artifact {
            if let (Some(ref repo), Some(ref art_id)) = (&final_artifact_repo, &final_artifact_id) {
                if let Some(meta) = self.gh.get_artifact_metadata(repo, art_id).await {
                    if meta.expired {
                        let expired_card = format!(
                            "⚠️ **ARTIFACT EXPIRED**\n\
                             ──────────────────────────────\n\
                             • 📦 **Artifact:**   `{}`\n\
                             • 📁 **Repository:** `{}`\n\
                             • 📅 **Expired At:** `{}`\n\n\
                             💡 *This GitHub Actions artifact has expired and can no longer be downloaded.*",
                            meta.name,
                            repo,
                            meta.expires_at.unwrap_or_else(|| "Unknown".to_string())
                        );
                        let _ = self
                            .tg
                            .edit_message_text(chat_id, status_msg_id, &expired_card, None)
                            .await;
                        return Ok(());
                    }
                    if file_name_override.is_none() {
                        initial_name = meta.name;
                    }
                    if known_size == 0 {
                        known_size = meta.size_in_bytes;
                    }
                }
            }
        }

        let formatted_size = if known_size > 0 {
            format_size(known_size)
        } else {
            "Querying size...".to_string()
        };

        let source_display = if is_artifact {
            "GitHub Actions Artifact"
        } else if req.telegram_file_id.is_some() {
            "Telegram Direct Upload"
        } else {
            raw_url
        };

        let init_card = format!(
            "📥 **INGESTING PAYLOAD**\n\
             ──────────────────────────────\n\
             • 🔗 **Source:**   `{}`\n\
             • 📄 **Target:**   `{}`\n\
             • 📦 **Filesize:** `{}`\n\n\
             ⚡ *Connecting and preparing stream...*",
            source_display, initial_name, formatted_size
        );
        let _ = self
            .tg
            .edit_message_text(chat_id, status_msg_id, &init_card, None)
            .await;

        let tmp_dir = std::env::temp_dir();
        let now_ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let mut download_target = tmp_dir.join(format!(
            "dl_{}_{}",
            now_ts,
            sanitize_filename(&initial_name)
        ));
        let mut cleanup_paths = vec![download_target.clone()];

        let dl_start = Instant::now();
        let dl_title = if is_artifact {
            "DOWNLOADING FROM GITHUB ARTIFACT"
        } else if req.telegram_file_id.is_some() {
            "DOWNLOADING FROM TELEGRAM"
        } else {
            "DOWNLOADING FROM REMOTE URL"
        };
        let mut dl_reporter = ProgressReporter::new(
            self.config.telegram_bot_token.clone(),
            chat_id,
            status_msg_id,
            dl_title,
            &initial_name,
        );

        // Phase 1: Ingestion
        let mut final_file_path = download_target.clone();
        let mut final_filename = initial_name.clone();
        let mut extracted_from_zip = false;

        if is_artifact {
            if !download_target
                .to_string_lossy()
                .to_lowercase()
                .ends_with(".zip")
            {
                download_target.set_extension("zip");
                cleanup_paths.push(download_target.clone());
            }

            let repo = final_artifact_repo
                .as_deref()
                .ok_or_else(|| "Missing artifact repository".to_string())?;
            let art_id = final_artifact_id
                .as_deref()
                .ok_or_else(|| "Missing artifact ID".to_string())?;

            self.gh
                .download_artifact_zip(repo, art_id, &download_target, |c, t| {
                    dl_reporter.update(c, t);
                })
                .await?;

            if let Some(unzip_res) = extract_single_file_from_zip(&download_target, &tmp_dir) {
                final_file_path = unzip_res.final_file_path.clone();
                final_filename = unzip_res.extracted_name;
                cleanup_paths.push(final_file_path.clone());
                cleanup_paths.push(unzip_res.extract_dest_dir);
                extracted_from_zip = true;
                info!(
                    "Unzipped artifact archive: extracted '{}' ({})",
                    final_filename,
                    format_size(unzip_res.file_size)
                );
            } else {
                return Err(
                    "Failed to unzip artifact: archive contains no valid files.".to_string()
                );
            }
        } else if let Some(fid) = req.telegram_file_id {
            self.tg
                .download_file_by_id(fid, &download_target, |c, t| {
                    dl_reporter.update(c, t);
                })
                .await?;

            if final_filename.to_lowercase().ends_with(".zip")
                || (!final_filename.to_lowercase().ends_with(".ipa")
                    && File::open(&download_target)
                        .ok()
                        .and_then(|f| zip::ZipArchive::new(f).ok())
                        .is_some())
            {
                if let Some(unzip_res) = extract_single_file_from_zip(&download_target, &tmp_dir) {
                    final_file_path = unzip_res.final_file_path.clone();
                    final_filename = unzip_res.extracted_name;
                    cleanup_paths.push(final_file_path.clone());
                    cleanup_paths.push(unzip_res.extract_dest_dir);
                    extracted_from_zip = true;
                    info!(
                        "Unzipped uploaded archive: extracted '{}' ({})",
                        final_filename,
                        format_size(unzip_res.file_size)
                    );
                }
            }
        } else {
            let (detected_name, _downloaded_bytes) = self
                .gh
                .download_stream_url(raw_url, &download_target, |c, t| {
                    dl_reporter.update(c, t);
                })
                .await?;

            if let Some(dname) = detected_name {
                final_filename = dname;
            }

            if final_filename.to_lowercase().ends_with(".zip")
                || (!final_filename.to_lowercase().ends_with(".ipa")
                    && File::open(&download_target)
                        .ok()
                        .and_then(|f| zip::ZipArchive::new(f).ok())
                        .is_some())
            {
                if let Some(unzip_res) = extract_single_file_from_zip(&download_target, &tmp_dir) {
                    final_file_path = unzip_res.final_file_path.clone();
                    final_filename = unzip_res.extracted_name;
                    cleanup_paths.push(final_file_path.clone());
                    cleanup_paths.push(unzip_res.extract_dest_dir);
                    extracted_from_zip = true;
                    info!(
                        "Unzipped downloaded archive: extracted '{}' ({})",
                        final_filename,
                        format_size(unzip_res.file_size)
                    );
                }
            }
        }

        let dl_duration = dl_start.elapsed().as_secs_f64().max(0.1);
        let file_meta = std::fs::metadata(&final_file_path)
            .map_err(|e| format!("Payload not found on disk: {}", e))?;
        let final_file_size = file_meta.len();
        let formatted_total_size = format_size(final_file_size);

        let ul_prep_card = format!(
            "☁️ **STREAMING TO DROPBOX**\n\
             ──────────────────────────────\n\
             • 📄 **Filename:** `{}`\n\
             • 📦 **Filesize:** `{}`\n\
             • ⏱️ **Ingest:** `{:.1}s`\n\n\
             ⚡ *Initializing chunked upload session...*",
            final_filename, formatted_total_size, dl_duration
        );
        let _ = self
            .tg
            .edit_message_text(chat_id, status_msg_id, &ul_prep_card, None)
            .await;

        // Phase 2: Dropbox Chunked Upload & Retention Auto-Rotation
        let (dest_path, retention_folder, vault_display) = resolve_dropbox_destination(
            &final_filename,
            &self.config.dropbox_ipa_folder,
            &self.config.dropbox_deb_folder,
        );

        let ul_start = Instant::now();
        let mut ul_reporter = ProgressReporter::new(
            self.config.telegram_bot_token.clone(),
            chat_id,
            status_msg_id,
            "STREAMING TO DROPBOX",
            &final_filename,
        );

        let (shared_url, pruned_items) = self
            .dbx
            .upload_file_chunked(
                &final_file_path,
                &dest_path,
                &retention_folder,
                self.config.chunk_size_mb,
                |curr, tot| {
                    ul_reporter.update(curr, tot);
                },
            )
            .await?;

        let ul_duration = ul_start.elapsed().as_secs_f64().max(0.1);
        let total_duration = dl_start.elapsed().as_secs_f64();
        let dl_speed = final_file_size as f64 / dl_duration;
        let ul_speed = final_file_size as f64 / ul_duration;

        let mut completion_card = format!(
            "💎 **TRANSFER COMPLETE**\n\
             ──────────────────────────────\n\
             • 📄 **Filename:** `{}`\n\
             • 📦 **Size:** `{}`\n\
             • 📂 **Vault:** `{}`\n",
            final_filename, formatted_total_size, vault_display
        );

        if is_artifact {
            completion_card.push_str(&format!(
                "• 🔗 **Source:** GitHub Actions Artifact (`{}`)\n",
                final_artifact_repo.as_deref().unwrap_or("Actions")
            ));
            if extracted_from_zip {
                completion_card
                    .push_str("  ℹ️ *Extracted single binary from artifact zip archive.*\n");
            }
        } else if req.telegram_file_id.is_some() {
            completion_card.push_str("• 🔗 **Source:** Telegram Direct Upload\n");
            if extracted_from_zip {
                completion_card
                    .push_str("  ℹ️ *Extracted single binary from uploaded zip archive.*\n");
            }
        } else {
            completion_card.push_str("• 🔗 **Source:** Remote Web Link\n");
            if extracted_from_zip {
                completion_card
                    .push_str("  ℹ️ *Extracted single binary from downloaded zip archive.*\n");
            }
        }

        completion_card.push_str(&format!(
            "\n⏱️ **Benchmarks**\n\
             • ⬇️ Ingest: `{:.1}s` (`{}/s`)\n\
             • ☁️ Cloud: `{:.1}s` (`{}/s`)\n\
             • ⏱️ Total: `{:.1}s` elapsed\n",
            dl_duration,
            format_size(dl_speed as u64),
            ul_duration,
            format_size(ul_speed as u64),
            total_duration
        ));

        if !pruned_items.is_empty() {
            let pruned_str = pruned_items
                .iter()
                .map(|name| format!("`{}`", name))
                .collect::<Vec<_>>()
                .join(", ");

            let detected_family = match_rotation_family(&final_filename);
            if let Some(family) = detected_family {
                completion_card.push_str(&format!(
                    "\n♻️ **Auto-Rotation (`{}`)**\n\
                     • Replaced matching `{}`:\n\
                       {}\n",
                    vault_display, family, pruned_str
                ));
            } else {
                let cap = self.config.get_max_files_for_folder(&retention_folder);
                completion_card.push_str(&format!(
                    "\n♻️ **Auto-Rotation (Cap: {} in `{}`)**\n\
                     • Pruned oldest:\n\
                       {}\n",
                    cap, vault_display, pruned_str
                ));
            }
        }

        completion_card.push_str("\n🔗 *Direct download ready via button below:*");

        if !shared_url.is_empty() {
            let _ = self
                .tg
                .edit_message_text(chat_id, status_msg_id, &completion_card, None)
                .await;

            // Direct 1-tap clipboard copy via Telegram Bot API v7.0+
            let _ = self
                .tg
                .apply_native_copy_button(chat_id, status_msg_id, &shared_url)
                .await;
        } else {
            completion_card.push_str("\nℹ️ *Payload securely archived in Dropbox vault.*");
            let _ = self
                .tg
                .edit_message_text(chat_id, status_msg_id, &completion_card, None)
                .await;
        }

        // Cleanup temp files
        for p in cleanup_paths {
            if p.is_dir() {
                let _ = std::fs::remove_dir_all(p);
            } else {
                let _ = std::fs::remove_file(p);
            }
        }

        let log_file = mask_filename(&final_filename, self.config.privacy_mode);
        info!(
            "URL sync complete: '{}' ({}) in {:.1}s",
            log_file, formatted_total_size, total_duration
        );

        Ok(())
    }

    pub async fn run_tracker(
        &mut self,
        chat_id: i64,
        message_id: i64,
        target_key: &str,
        initial_run_id: Option<i64>,
        _start_time: f64,
    ) -> Result<(), String> {
        let _ = self.tg.get_me().await;
        let target = get_target(target_key).unwrap_or(&TARGET_DTKACE);

        info!("====================================================================");
        info!("🛰️ WORKFLOW BUILD TRACKER ENGINE (NATIVE RUST CORE)");
        info!("====================================================================");
        info!("• Target Repository: {}", target.repo);
        info!("• Workflow File:     {}", target.workflow);
        info!("• Chat ID:           {}", chat_id);
        info!("• Message ID:        {}", message_id);
        info!("====================================================================");

        let mut run_id = initial_run_id;
        let max_checks = 180; // 180 * 6s = 18 minutes

        for check_idx in 0..max_checks {
            tokio::time::sleep(Duration::from_secs(6)).await;

            if run_id.is_none() {
                if let Some(latest) = self.gh.get_latest_workflow_run(target.repo).await {
                    run_id = Some(latest.id);
                }
            }

            if let Some(rid) = run_id {
                if let Some(details) = self.gh.get_workflow_run_details(target.repo, rid).await {
                    let status = details.status.unwrap_or_else(|| "in_progress".to_string());
                    let conclusion = details.conclusion.clone();

                    if status == "completed" {
                        if conclusion.as_deref() == Some("success") {
                            let success_card = format!(
                                "🎉 **BUILD COMPLETED SUCCESSFULLY!**\n\
                                 ──────────────────────────────\n\
                                 • 📦 **Target:** `{}`\n\
                                 • 🏷️ **Run ID:** `{}`\n\
                                 • ⚡ **Status:** `Compiled & Verified`\n\n\
                                 📦 *Fetching compiled IPA artifact for automatic Dropbox archiving...*",
                                target.name, rid
                            );
                            let _ = self
                                .tg
                                .edit_message_text(chat_id, message_id, &success_card, None)
                                .await;

                            let artifacts = self.gh.get_run_artifacts(target.repo, rid).await;
                            if let Some(art) = artifacts.first() {
                                let _ = self.dbx.initialize().await;
                                let art_id_str = art.id.to_string();
                                self.process_url_payload(ProcessPayloadRequest {
                                    raw_url: "",
                                    chat_id,
                                    message_id,
                                    dispatch_msg_id: Some(message_id),
                                    is_artifact: true,
                                    artifact_id: Some(&art_id_str),
                                    artifact_repo: Some(target.repo),
                                    file_name_override: Some(&art.name),
                                    file_size_override: art.size_in_bytes,
                                    ..Default::default()
                                })
                                .await?;
                            }
                        } else {
                            let fail_card = format!(
                                "❌ **BUILD FAILED**\n\
                                 ──────────────────────────────\n\
                                 • 📦 **Target:** `{}`\n\
                                 • 🏷️ **Run ID:** `{}`\n\
                                 • ⚠️ **Conclusion:** `{}`\n\n\
                                 💡 *Check repository Actions logs for compilation error details.*",
                                target.name,
                                rid,
                                conclusion.unwrap_or_else(|| "failed".to_string())
                            );
                            let _ = self
                                .tg
                                .edit_message_text(chat_id, message_id, &fail_card, None)
                                .await;
                        }
                        return Ok(());
                    } else {
                        let tracking_card = format!(
                            "⚙️ **BUILD IN PROGRESS: {}**\n\
                             ──────────────────────────────\n\
                             • 📦 **Target:** `{}`\n\
                             • 🏷️ **Run ID:** `{}`\n\
                             • ⚡ **Status:** `{}` (Poll {}/{})\n\n\
                             ☕ *Compilation actively executing on GitHub macOS runner...*",
                            target.name,
                            target.name,
                            rid,
                            status,
                            check_idx + 1,
                            max_checks
                        );
                        let _ = self
                            .tg
                            .edit_message_text(chat_id, message_id, &tracking_card, None)
                            .await;
                    }
                }
            }
        }

        Ok(())
    }

    pub async fn run_version_monitor(&self) -> Result<(), String> {
        info!("Checking iOS App Store versions for YouTube and YouTube Music...");
        let (apps, alerts) = check_all_ios_versions(None).await;
        println!("{}", format_version_status_text(&apps));

        if !alerts.is_empty() {
            println!("\nFound {} new version alert(s)!", alerts.len());
            let mut recipients: Vec<i64> =
                self.config.authorized_user_ids.iter().copied().collect();
            if recipients.is_empty() {
                if let Some(cid) = self.config.target_chat_id {
                    recipients.push(cid);
                }
            }

            for (app_info, prev_ver) in &alerts {
                let alert_text = format_version_alert_text(app_info, prev_ver.as_deref());
                let buttons = get_version_alert_buttons(app_info);
                println!("\n{}", alert_text);

                if !recipients.is_empty() {
                    let _ = send_telegram_alert(
                        &self.config.telegram_bot_token,
                        &recipients,
                        &alert_text,
                        Some(buttons),
                    )
                    .await;
                    info!("Alert dispatched to {} recipient(s).", recipients.len());
                }
            }
        } else {
            println!("\nAll tracked iOS apps are up to date.");
        }

        Ok(())
    }

    pub async fn run_daemon(&mut self) -> Result<(), String> {
        let _ = self.tg.get_me().await;
        let _ = self.dbx.initialize().await;

        info!("====================================================================");
        info!("🚀 TELEGRAM TO DROPBOX BOT DAEMON (NATIVE RUST CORE)");
        info!("====================================================================");
        info!("• Bot Username: @{}", self.tg.bot_username);
        info!("• Mode:         Persistent Interactive Polling");
        info!("====================================================================");

        let mut offset: i64 = 0;
        loop {
            match self.tg.get_updates(offset, 25).await {
                Ok(updates) => {
                    for update in updates {
                        offset = update.update_id + 1;
                        if let Some(msg) = update.message {
                            self.handle_message(msg).await;
                        } else if let Some(cb) = update.callback_query {
                            self.handle_callback(cb).await;
                        }
                    }
                }
                Err(err) => {
                    debug!("getUpdates poll error: {}", err);
                    tokio::time::sleep(Duration::from_secs(3)).await;
                }
            }
        }
    }

    async fn handle_message(&self, msg: crate::telegram::TelegramMessage) {
        let chat_id = msg.chat.id;
        let user_id = msg.from.as_ref().map(|u| u.id).unwrap_or(0);

        if !self.config.is_authorized(user_id) {
            warn!(
                "Unauthorized message attempt from user_id: {}",
                mask_user_id(user_id, self.config.privacy_mode)
            );
            return;
        }

        // Direct media payload uploads (Document, Video, Audio)
        if let Some(ref doc) = msg.document {
            let doc_name = doc.file_name.as_deref().unwrap_or("document.bin");
            let doc_size = doc.file_size.unwrap_or(0);
            let _ = self
                .process_url_payload(ProcessPayloadRequest {
                    raw_url: "",
                    chat_id,
                    message_id: msg.message_id,
                    file_name_override: Some(doc_name),
                    file_size_override: doc_size,
                    telegram_file_id: Some(&doc.file_id),
                    ..Default::default()
                })
                .await;
            return;
        }

        if let Some(ref vid) = msg.video {
            let vid_name = vid.file_name.as_deref().unwrap_or("video.mp4");
            let vid_size = vid.file_size.unwrap_or(0);
            let _ = self
                .process_url_payload(ProcessPayloadRequest {
                    raw_url: "",
                    chat_id,
                    message_id: msg.message_id,
                    file_name_override: Some(vid_name),
                    file_size_override: vid_size,
                    telegram_file_id: Some(&vid.file_id),
                    ..Default::default()
                })
                .await;
            return;
        }

        if let Some(ref aud) = msg.audio {
            let aud_name = aud.file_name.as_deref().unwrap_or("audio.mp3");
            let aud_size = aud.file_size.unwrap_or(0);
            let _ = self
                .process_url_payload(ProcessPayloadRequest {
                    raw_url: "",
                    chat_id,
                    message_id: msg.message_id,
                    file_name_override: Some(aud_name),
                    file_size_override: aud_size,
                    telegram_file_id: Some(&aud.file_id),
                    ..Default::default()
                })
                .await;
            return;
        }

        let text = msg.text.as_deref().unwrap_or("").trim();

        // Check if there is an active parameter input prompt for this user
        {
            let mut pending = self.pending_inputs.lock().await;
            if let Some(prompt) = pending.remove(&chat_id) {
                if text == "/cancel" || text.eq_ignore_ascii_case("cancel") {
                    let _ = self
                        .tg
                        .send_message(
                            chat_id,
                            "🚫 Input prompt cancelled.",
                            Some(msg.message_id),
                            None,
                        )
                        .await;
                    return;
                }

                let mut dashboards = self.user_dashboards.lock().await;
                let state = dashboards.entry(chat_id).or_insert_with(|| DashboardState {
                    target_key: prompt.target_key.clone(),
                    ..Default::default()
                });

                match prompt.field.as_str() {
                    "ipa" => state.ipa = Some(text.to_string()),
                    "name" => state.name = Some(text.to_string()),
                    "bundle" => state.bundle = Some(text.to_string()),
                    "tweak" => {
                        if text.eq_ignore_ascii_case("default") || text.is_empty() {
                            state.tweak = None;
                        } else {
                            state.tweak = Some(text.to_string());
                        }
                    }
                    _ => {}
                }

                let card_text = render_dashboard_text(state);
                let buttons = render_dashboard_buttons(state);
                let _ = self
                    .tg
                    .edit_message_text(chat_id, prompt.dash_msg_id, &card_text, Some(buttons))
                    .await;
                let _ = self
                    .tg
                    .send_message(
                        chat_id,
                        "✅ Value updated successfully!",
                        Some(msg.message_id),
                        None,
                    )
                    .await;
                return;
            }
        }

        if text == "/start" || text == "/help" {
            let help_card = render_help_card();
            let _ = self
                .tg
                .send_message(chat_id, &help_card, Some(msg.message_id), None)
                .await;
        } else if text == "/ping" {
            let ping_card = render_ping_card();
            let _ = self
                .tg
                .send_message(chat_id, &ping_card, Some(msg.message_id), None)
                .await;
        } else if text == "/cancel" {
            let _ = self
                .tg
                .send_message(
                    chat_id,
                    "🚫 No active operation to cancel.",
                    Some(msg.message_id),
                    None,
                )
                .await;
        } else if text == "/build" {
            let (menu_text, buttons) = render_main_menu();
            let _ = self
                .tg
                .send_message(chat_id, &menu_text, Some(msg.message_id), Some(buttons))
                .await;
        } else if text == "/checkversion" || text == "/version" {
            let (apps, _) = check_all_ios_versions(None).await;
            let status_text = format_version_status_text(&apps);
            let buttons = get_version_status_buttons();
            let _ = self
                .tg
                .send_message(chat_id, &status_text, Some(msg.message_id), Some(buttons))
                .await;
        } else if text.starts_with("/settweak") || text.starts_with("/secret") {
            let parts: Vec<&str> = text.split_whitespace().collect();
            if parts.len() >= 3 {
                let target_key = parts[1].to_lowercase();
                let tweak_url = parts[2].trim();
                let repo = match target_key.as_str() {
                    "dtkace" => "DexterDevKH/DTKACE",
                    "dtlite" => "DexterDevKH/DTLite",
                    _ => {
                        let _ = self
                            .tg
                            .send_message(
                                chat_id,
                                "⚠️ Invalid target. Choose `dtkace` or `dtlite`.",
                                Some(msg.message_id),
                                None,
                            )
                            .await;
                        return;
                    }
                };

                let notice = format!(
                    "⏳ Encrypting & updating `TWEAK_URL` for `{}`...",
                    target_key
                );
                let _ = self
                    .tg
                    .send_message(chat_id, &notice, Some(msg.message_id), None)
                    .await;

                match self
                    .gh
                    .update_repository_secret(repo, "TWEAK_URL", tweak_url)
                    .await
                {
                    Ok(_) => {
                        let succ = format!(
                            "✅ **SECRET UPDATED SUCCESSFULLY**\n\
                             ──────────────────────────────\n\
                             • 📦 **Repository:** `{}`\n\
                             • 🔐 **Secret Name:** `TWEAK_URL`\n\
                             • 🔗 **Tweak URL:** `{}`\n\
                             • 🛡️ **Encryption:** Libsodium SealedBox (X25519)\n\n\
                             💡 *Subsequent workflow runs will compile with this tweak.*",
                            repo, tweak_url
                        );
                        let _ = self
                            .tg
                            .send_message(chat_id, &succ, Some(msg.message_id), None)
                            .await;
                    }
                    Err(err) => {
                        let err_card = format!(
                            "❌ **SECRET UPDATE FAILED**\n\
                             ──────────────────────────────\n\
                             • ⚠️ **Details:** `{}`\n\n\
                             💡 *Verify that your GH_PAT has repo/secrets:write permissions.*",
                            err
                        );
                        let _ = self
                            .tg
                            .send_message(chat_id, &err_card, Some(msg.message_id), None)
                            .await;
                    }
                }
            } else {
                let usage = "ℹ️ **SET TWEAK SECRET COMMAND**\n\
                             ──────────────────────────────\n\
                             • **Usage:** `/settweak <dtkace|dtlite> <DEB_URL>`\n\n\
                             **Example:**\n\
                             `/settweak dtkace https://github.com/repo/releases/download/v1.0/tweak.deb`\n\n\
                             🔐 *Updates GitHub Actions encrypted secret TWEAK_URL.*";
                let _ = self
                    .tg
                    .send_message(chat_id, usage, Some(msg.message_id), None)
                    .await;
            }
        } else if text == "/status" || text == "/info" {
            let status_text = render_status_card(&self.config, &self.dbx.account_name);
            let _ = self
                .tg
                .send_message(chat_id, &status_text, Some(msg.message_id), None)
                .await;
        } else if text.starts_with("http://") || text.starts_with("https://") {
            let _ = self
                .process_url_payload(ProcessPayloadRequest {
                    raw_url: text,
                    chat_id,
                    message_id: msg.message_id,
                    ..Default::default()
                })
                .await;
        }
    }

    async fn handle_callback(&self, cb: crate::telegram::TelegramCallbackQuery) {
        let _ = self.tg.answer_callback_query(&cb.id, None).await;
        let data = cb.data.as_deref().unwrap_or("");
        let Some(ref msg) = cb.message else { return };
        let chat_id = msg.chat.id;
        let msg_id = msg.message_id;

        if data.starts_with("sel:") {
            let target_key = data.trim_start_matches("sel:");
            let state = DashboardState {
                target_key: target_key.to_string(),
                ..Default::default()
            };
            let text = render_dashboard_text(&state);
            let buttons = render_dashboard_buttons(&state);
            let _ = self
                .tg
                .edit_message_text(chat_id, msg_id, &text, Some(buttons))
                .await;
            let mut dashboards = self.user_dashboards.lock().await;
            dashboards.insert(chat_id, state);
        } else if data == "nav:main" {
            let (menu_text, buttons) = render_main_menu();
            let _ = self
                .tg
                .edit_message_text(chat_id, msg_id, &menu_text, Some(buttons))
                .await;
        } else if data == "cancel" {
            let cancel_text = "❌ **ACTION CANCELLED**\n──────────────────────────────\nBuild or operation cancelled.";
            let _ = self
                .tg
                .edit_message_text(chat_id, msg_id, cancel_text, None)
                .await;
            let mut pending = self.pending_inputs.lock().await;
            pending.remove(&chat_id);
        } else if data == "check_versions" {
            let (apps, _) = check_all_ios_versions(None).await;
            let status_text = format_version_status_text(&apps);
            let buttons = get_version_status_buttons();
            let _ = self
                .tg
                .edit_message_text(chat_id, msg_id, &status_text, Some(buttons))
                .await;
        } else if data.starts_with("exts:") {
            let parts: Vec<&str> = data.split(':').collect();
            if parts.len() >= 3 {
                let target_key = parts[1];
                let mask_hex = parts[2];
                let kb = render_extensions_keyboard(target_key, mask_hex);
                let text = format!(
                    "⚙️ **CONFIGURE EXTENSIONS: {}**\n\
                     ──────────────────────────────\n\
                     Tap any extension below to toggle On (✅) or Off (❌).\n\
                     Current state is saved automatically in a stateless bitmask.\n\n\
                     💾 *Tap [ Save & Return ] when finished:*",
                    target_key.to_uppercase()
                );
                let _ = self
                    .tg
                    .edit_message_text(chat_id, msg_id, &text, Some(kb))
                    .await;
            }
        } else if data.starts_with("tgl:") {
            let parts: Vec<&str> = data.split(':').collect();
            if parts.len() >= 4 {
                let target_key = parts[1];
                let idx: usize = parts[2].parse().unwrap_or(0);
                let mask_hex = parts[3];
                let exts = get_extensions(target_key);
                let default_mask = (1u64 << exts.len()) - 1;
                let current_mask = u64::from_str_radix(mask_hex, 16).unwrap_or(default_mask);
                let new_mask = current_mask ^ (1u64 << idx);
                let new_mask_hex = format!("{:x}", new_mask);

                let kb = render_extensions_keyboard(target_key, &new_mask_hex);
                let text = format!(
                    "⚙️ **CONFIGURE EXTENSIONS: {}**\n\
                     ──────────────────────────────\n\
                     Tap any extension below to toggle On (✅) or Off (❌).\n\
                     Current state is saved automatically in a stateless bitmask.\n\n\
                     💾 *Tap [ Save & Return ] when finished:*",
                    target_key.to_uppercase()
                );
                let _ = self
                    .tg
                    .edit_message_text(chat_id, msg_id, &text, Some(kb))
                    .await;
            }
        } else if data.starts_with("tgl_all:") {
            let parts: Vec<&str> = data.split(':').collect();
            if parts.len() >= 3 {
                let target_key = parts[1];
                let mask_hex = parts[2];
                let exts = get_extensions(target_key);
                let decoded = decode_bitmask(mask_hex, exts);
                let new_mask_hex = if decoded.enabled_count == 0 {
                    format!("{:x}", (1u64 << exts.len()) - 1)
                } else {
                    "0".to_string()
                };
                let kb = render_extensions_keyboard(target_key, &new_mask_hex);
                let text = format!(
                    "⚙️ **CONFIGURE EXTENSIONS: {}**\n\
                     ──────────────────────────────\n\
                     Tap any extension below to toggle On (✅) or Off (❌).\n\
                     Current state is saved automatically in a stateless bitmask.\n\n\
                     💾 *Tap [ Save & Return ] when finished:*",
                    target_key.to_uppercase()
                );
                let _ = self
                    .tg
                    .edit_message_text(chat_id, msg_id, &text, Some(kb))
                    .await;
            }
        } else if data.starts_with("tgl_rst:") {
            let target_key = data.trim_start_matches("tgl_rst:");
            let exts = get_extensions(target_key);
            let default_mask_hex = format!("{:x}", (1u64 << exts.len()) - 1);
            let kb = render_extensions_keyboard(target_key, &default_mask_hex);
            let text = format!(
                "⚙️ **CONFIGURE EXTENSIONS: {}**\n\
                 ──────────────────────────────\n\
                 Tap any extension below to toggle On (✅) or Off (❌).\n\
                 Current state is saved automatically in a stateless bitmask.\n\n\
                 💾 *Tap [ Save & Return ] when finished:*",
                target_key.to_uppercase()
            );
            let _ = self
                .tg
                .edit_message_text(chat_id, msg_id, &text, Some(kb))
                .await;
        } else if data.starts_with("ext_done:") {
            let parts: Vec<&str> = data.split(':').collect();
            if parts.len() >= 3 {
                let target_key = parts[1];
                let mask_hex = parts[2];
                let mut dashboards = self.user_dashboards.lock().await;
                let state = dashboards.entry(chat_id).or_insert_with(|| DashboardState {
                    target_key: target_key.to_string(),
                    ..Default::default()
                });
                state.mask_hex = mask_hex.to_string();
                let text = render_dashboard_text(state);
                let buttons = render_dashboard_buttons(state);
                let _ = self
                    .tg
                    .edit_message_text(chat_id, msg_id, &text, Some(buttons))
                    .await;
            }
        } else if data.starts_with("ask:") {
            let parts: Vec<&str> = data.split(':').collect();
            if parts.len() >= 3 {
                let field = parts[1];
                let target_key = parts[2];
                let mut pending = self.pending_inputs.lock().await;
                pending.insert(
                    chat_id,
                    PendingInputPrompt {
                        field: field.to_string(),
                        target_key: target_key.to_string(),
                        dash_msg_id: msg_id,
                    },
                );

                let prompt_text = match field {
                    "ipa" => format!(
                        "🔗 **INPUT: DECRYPTED IPA URL**\n\
                         ──────────────────────────────\n\
                         • 📦 **Target:** `{}`\n\n\
                         Reply with the direct download URL for the decrypted IPA file.\n\n\
                         💡 *Type /cancel to abort.*",
                        target_key.to_uppercase()
                    ),
                    "name" => format!(
                        "🏷️ **INPUT: APP DISPLAY NAME**\n\
                         ──────────────────────────────\n\
                         • 📦 **Target:** `{}`\n\n\
                         Reply with your desired app name (e.g. `My YouTube`).\n\n\
                         💡 *Type /cancel to abort.*",
                        target_key.to_uppercase()
                    ),
                    "bundle" => format!(
                        "🆔 **INPUT: BUNDLE IDENTIFIER**\n\
                         ──────────────────────────────\n\
                         • 📦 **Target:** `{}`\n\n\
                         Reply with your desired bundle identifier (e.g. `com.my.youtube`).\n\n\
                         💡 *Type /cancel to abort.*",
                        target_key.to_uppercase()
                    ),
                    "tweak" => format!(
                        "💉 **INPUT: CUSTOM TWEAK URL**\n\
                         ──────────────────────────────\n\
                         • 📦 **Target:** `{}`\n\n\
                         Reply with a direct link to custom .deb, or type `default` to reset.\n\n\
                         💡 *Type /cancel to abort.*",
                        target_key.to_uppercase()
                    ),
                    _ => "Reply with the updated value:".to_string(),
                };
                let _ = self
                    .tg
                    .send_message(chat_id, &prompt_text, Some(msg_id), None)
                    .await;
            }
        } else if data.starts_with("trig:") {
            let target_key = data.trim_start_matches("trig:");
            let target = get_target(target_key).unwrap_or(&TARGET_DTKACE);
            let dashboards = self.user_dashboards.lock().await;
            if let Some(state) = dashboards.get(&chat_id) {
                if let Some(ref ipa_url) = state.ipa {
                    let mut inputs = serde_json::Map::new();
                    inputs.insert("decrypted_ipa_url".to_string(), serde_json::json!(ipa_url));
                    if let Some(ref n) = state.name {
                        inputs.insert("app_name".to_string(), serde_json::json!(n));
                    }
                    if let Some(ref b) = state.bundle {
                        inputs.insert("bundle_id".to_string(), serde_json::json!(b));
                    }
                    if let Some(ref t) = state.tweak {
                        if !t.is_empty() {
                            inputs.insert("custom_tweak_url".to_string(), serde_json::json!(t));
                        }
                    }
                    if target.has_extensions {
                        let exts = get_extensions(target_key);
                        let decoded = decode_bitmask(&state.mask_hex, exts);
                        for dis in &decoded.disabled {
                            let input_key = format!("include_{}", dis);
                            inputs.insert(input_key, serde_json::json!("false"));
                        }
                    }

                    let inputs_val = serde_json::Value::Object(inputs);
                    let (success_card, btns) =
                        crate::ui::render_build_success_card(target, &inputs_val);
                    match self
                        .gh
                        .trigger_workflow_dispatch(target.repo, target.workflow, inputs_val)
                        .await
                    {
                        Ok(_) => {
                            let _ = self
                                .tg
                                .edit_message_text(chat_id, msg_id, &success_card, Some(btns))
                                .await;
                        }
                        Err(err) => {
                            let err_card = format!(
                                "❌ **WORKFLOW DISPATCH FAILED**\n\
                                 ──────────────────────────────\n\
                                 • 📦 **Repository:** `{}`\n\
                                 • 📄 **Workflow:**   `{}`\n\
                                 • ⚠️ **Details:**    `{}`\n\n\
                                 💡 *Verify that your GH_PAT secret has 'repo' or 'actions:write' permissions.*",
                                target.repo, target.workflow, err
                            );
                            let _ = self
                                .tg
                                .edit_message_text(chat_id, msg_id, &err_card, None)
                                .await;
                        }
                    }
                }
            }
        }
    }
}
