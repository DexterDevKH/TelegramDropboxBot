# ⚡ Telegram to Dropbox Cloud Sync Engine

An enterprise-grade, high-performance Telegram-to-Dropbox sync pipeline powered by Telethon MTProto and the Dropbox API. Designed for continuous 24/7 autonomous operation via GitHub Actions.

---

## 🌟 Key Features

- **🚀 2 GB MTProto Ingestion**: Full MTProto protocol support for files up to 2.0 GB (documents, videos, archives, IPAs).
- **📊 Real-Time Dual-Phase Progress**:
  - Phase 1: Throttled MTProto download progress with live speed, ETA, and block progress bar.
  - Phase 2: Live chunked cloud upload tracking with real-time transfer speed and ETA.
- **📋 Direct 1-Tap Copy Link**: Powered by Telegram Bot API v7.0+ `CopyTextButton` — directly writes the shared Dropbox link to the client OS clipboard with a single tap.
- **♻️ Automated FIFO Folder Retention**: Automatically prunes the oldest files when folder capacity exceeds the configured cap (`MAX_FILES_IN_FOLDER`).
- **🕹️ Remote Daemon Control**:
  - `/status` — Real-time health monitor, runner uptime, Dropbox storage quota, and session metrics.
  - `/ping` — Measures round-trip gateway latency between Telegram and the runner.
  - `/stop` — Safely terminates the runner with a clean session summary and Exit Code 0.
  - `/help` — Interactive command manual.
- **🔒 Access Whitelisting**: Strict authorization filter via `AUTHORIZED_USER_IDS` to restrict usage to approved accounts.
- **🛡️ Privacy Shield & Log Sanitization**: Automatically masks transferred filenames (`se***t.pdf`), redacts Telegram user IDs, hides Dropbox account names/emails, and masks confidential secrets in GitHub Actions console logs while preserving full details in private Telegram chats.
- **🧹 Automated Run Log Purging**: Dedicated auto-purge workflow (`cleanup.yml`) automatically deletes completed GitHub Actions workflow runs and their logs immediately upon completion, leaving no historical trace.
- **🔄 24/7 CI Runner Cycling**: GitHub Actions workflow automatically cycles every 6 hours with singleton concurrency to prevent race conditions.

---

## 🏗️ Architecture Pipeline

```text
[Telegram User]
       │
       ▼ (MTProto direct download up to 2 GB)
[GitHub Actions Runner (Python 3.11)]
       │
       ├─► Live Progress Bar Updates to Telegram
       │
       ▼ (8 MB chunked streaming upload session)
[Dropbox Cloud Storage]
       │
       ├─► FIFO Retention Auto-Rotation
       ├─► Shared Link Generation
       │
       ▼ (Telegram Bot API v7.0+)
[Interactive Telegram Message Card]
   ├── [ 📋 Copy Direct Link ] (Native Clipboard Copy)
   └── [ 🌐 Open in Dropbox ]  (Direct Web Link)
```

---

## 🕹️ Telegram Commands Reference

| Command | Description | Example Output |
| :--- | :--- | :--- |
| `/start` or `/help` | Operational manual and system configuration overview | Configuration, limits, and command guide |
| `/status` or `/info` | Real-time runner uptime, cloud quota, and session metrics | Session duration, file counts, and quota usage |
| `/ping` | Test network round-trip latency to the GitHub Actions runner | Latency in milliseconds and host health |
| `/stop` or `/kill` | Remotely stop the active GitHub Actions runner | Session summary report and clean exit |

---

## ⚙️ GitHub Secrets Configuration

Configure the following secrets in **Settings ➔ Secrets and variables ➔ Actions**:

| Secret Name | Required | Description |
| :--- | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | Telegram Bot API token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API_ID` | **Yes** | Telegram App API ID from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | **Yes** | Telegram App API Hash from [my.telegram.org](https://my.telegram.org) |
| `DROPBOX_APP_KEY` | **Yes** | Dropbox App Key from [Dropbox App Console](https://www.dropbox.com/developers/apps) |
| `DROPBOX_APP_SECRET` | **Yes** | Dropbox App Secret from Dropbox App Console |
| `DROPBOX_REFRESH_TOKEN` | **Yes** | Permanent OAuth 2.0 offline refresh token (generate via `get_refresh_token.py`) |
| `AUTHORIZED_USER_IDS` | No | Comma-separated Telegram User IDs allowed to use the bot (e.g. `123456,789012`). If empty, public. |
| `DROPBOX_TARGET_FOLDER` | No | Destination folder path in Dropbox (Default: `/Telegram Uploads`) |
| `MAX_FILES_IN_FOLDER` | No | Maximum number of files to retain before pruning oldest (Default: `2`) |
| `PRIVACY_MODE` | No | Mask filenames, user IDs, and cloud paths in runner logs (Default: `true`) |

---

## 🔑 Generating Dropbox Permanent Refresh Token

Run the included token generator locally:

```bash
python get_refresh_token.py
```

Follow the prompts to authorize your app with offline access and paste the generated `DROPBOX_REFRESH_TOKEN` into your GitHub repository secrets.

---

## 🚀 GitHub Actions CI Pipeline & Privacy Protection

The repository includes two complementary workflows:
1. **Sync Pipeline (`.github/workflows/bot.yml`)**:
   - **Privacy Shield & Secret Masking**: Automatically registers `::add-mask::` on all user IDs, API IDs, and folder paths. Filenames are masked in console output (`do***t.pdf`).
   - **Environment-based Secret Audits**: Verifies credentials securely without exposing secrets directly in bash strings.
   - **Sanitized Job Summary**: Deployment summary on GitHub renders without exposing sensitive Dropbox vault paths or credentials.
   - **Pre-Run Historical Purge**: Automatically cleans out old completed runs at startup.
   - **Customizable Manual Dispatch**: Easily adjust execution window, retention cap, log verbosity, and toggle Privacy Mode.
2. **Auto-Purge History Daemon (`.github/workflows/cleanup.yml`)**:
   - **Automated Trigger**: Triggers automatically whenever the sync pipeline finishes a session (via `/stop`, timeout, or cancellation).
   - **Zero Footprint**: Deletes the completed workflow run and its execution logs from GitHub via GitHub Actions REST API so no sensitive metadata or logs persist.

---

## 📄 License

MIT License. Designed for automated cloud data ingestion.