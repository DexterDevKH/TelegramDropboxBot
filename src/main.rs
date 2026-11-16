//! Main CLI Entrypoint for Telegram to Dropbox Cloud Sync Engine

use clap::Parser;
use std::process;
use tracing::{error, info, Level};
use tracing_subscriber::FmtSubscriber;

use telegram_dropbox_bot::config::load_config;
use telegram_dropbox_bot::engine::SyncApp;
use telegram_dropbox_bot::github::GitHubService;
use telegram_dropbox_bot::privacy::register_github_mask;

#[derive(Parser, Debug)]
#[command(
    name = "telegram_dropbox_bot",
    version = "3.1.0",
    about = "High-performance native Rust core for Telegram to Dropbox sync & iOS builder"
)]
struct Cli {
    /// Run in standalone daemon mode
    #[arg(long)]
    daemon: bool,

    /// Check iOS App Store versions for YouTube and YouTube Music
    #[arg(long)]
    check_versions: bool,

    /// Run workflow build tracker mode
    #[arg(long)]
    tracker: bool,

    /// Target application key (e.g. dtkace, dtlite, dtmusic)
    #[arg(long)]
    target: Option<String>,

    /// Workflow run ID for tracking
    #[arg(long)]
    run_id: Option<i64>,

    /// Target Telegram chat ID
    #[arg(long)]
    chat_id: Option<i64>,

    /// Target Telegram message ID
    #[arg(long)]
    message_id: Option<i64>,

    /// Dispatch notice message ID to edit
    #[arg(long)]
    dispatch_msg_id: Option<i64>,

    /// Download URL for on-demand sync
    #[arg(long)]
    url: Option<String>,

    /// Update TWEAK_URL secret on GitHub Actions (target tweak_url)
    #[arg(long, num_args = 2)]
    set_tweak: Option<Vec<String>>,

    /// Interactively generate permanent Dropbox OAuth 2.0 offline refresh token
    #[arg(long, visible_alias = "oauth")]
    get_refresh_token: bool,
}

#[tokio::main]
async fn main() {
    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::INFO)
        .finish();
    let _ = tracing::subscriber::set_global_default(subscriber);

    let cli = Cli::parse();

    // Standalone OAuth refresh token generator
    if cli.get_refresh_token {
        if let Err(err) =
            telegram_dropbox_bot::dropbox::DropboxService::generate_refresh_token_interactive()
                .await
        {
            eprintln!("❌ Error: {}", err);
            process::exit(1);
        }
        process::exit(0);
    }

    let mut config = match load_config() {
        Ok(c) => c,
        Err(err) => {
            eprintln!("Configuration Error: {}", err);
            process::exit(1);
        }
    };

    // Apply CLI overrides if passed
    if let Some(cid) = cli.chat_id {
        config.target_chat_id = Some(cid);
    }
    if let Some(mid) = cli.message_id {
        config.target_message_id = Some(mid);
    }
    if let Some(did) = cli.dispatch_msg_id {
        config.dispatch_message_id = Some(did);
    }
    if let Some(tgt) = cli.target {
        config.build_target_key = Some(tgt);
    }
    if let Some(rid) = cli.run_id {
        config.build_run_id = Some(rid);
    }
    if let Some(u) = cli.url {
        config.download_url = Some(u);
    }

    // Register privacy masks
    if config.is_github_actions {
        register_github_mask(Some(&config.telegram_bot_token));
        register_github_mask(Some(&config.dropbox_ipa_folder));
        register_github_mask(Some(&config.dropbox_deb_folder));
    }

    // 1. Secret Tweak CLI
    if let Some(tweak_args) = cli.set_tweak {
        if tweak_args.len() >= 2 {
            let target_key = tweak_args[0].to_lowercase();
            let tweak_url = &tweak_args[1];
            let repo = match target_key.as_str() {
                "dtkace" => "DexterDevKH/DTKACE",
                "dtlite" => "DexterDevKH/DTLite",
                other => {
                    eprintln!("Unknown target '{}'. Use 'dtkace' or 'dtlite'.", other);
                    process::exit(1);
                }
            };
            let gh = GitHubService::new(config.gh_pat.clone());
            info!("Updating TWEAK_URL for repository '{}'...", repo);
            match gh
                .update_repository_secret(repo, "TWEAK_URL", tweak_url)
                .await
            {
                Ok(msg) => {
                    println!("SUCCESS: {}", msg);
                    process::exit(0);
                }
                Err(err) => {
                    eprintln!("ERROR: {}", err);
                    process::exit(1);
                }
            }
        }
    }

    let mut app = SyncApp::new(config.clone());

    // 2. iOS Version Check CLI
    if cli.check_versions {
        if let Err(err) = app.run_version_monitor().await {
            error!("Version monitor failed: {}", err);
            process::exit(1);
        }
        return;
    }

    // 3. Workflow Build Tracker Mode
    if cli.tracker
        || (config.build_target_key.is_some()
            && config.target_chat_id.is_some()
            && config.target_message_id.is_some())
    {
        let chat_id = config.target_chat_id.unwrap_or(0);
        let message_id = config.target_message_id.unwrap_or(0);
        let target_key = config
            .build_target_key
            .clone()
            .unwrap_or_else(|| "dtkace".to_string());
        let run_id = config.build_run_id;
        let start_time = config.build_start_time;

        if let Err(err) = app
            .run_tracker(chat_id, message_id, &target_key, run_id, start_time)
            .await
        {
            error!("Tracker execution failed: {}", err);
            process::exit(1);
        }
        return;
    }

    // 4. On-Demand Sync Mode
    if config.target_chat_id.is_some() && config.target_message_id.is_some() {
        let chat_id = config.target_chat_id.unwrap();
        let message_id = config.target_message_id.unwrap();
        let disp_id = config.dispatch_message_id;

        if let Err(err) = app.run_on_demand(chat_id, message_id, disp_id).await {
            error!("On-demand execution failed: {}", err);
            process::exit(1);
        }
        return;
    }

    // 5. Ephemeral GitHub Actions Exit (no payload provided)
    if config.is_github_actions {
        info!("GitHub Actions runner triggered without target payload. Exiting cleanly.");
        return;
    }

    // 6. Interactive Daemon Loop (default)
    if let Err(err) = app.run_daemon().await {
        error!("Daemon terminated with error: {}", err);
        process::exit(1);
    }
}
