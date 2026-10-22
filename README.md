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
| `DROPBOX_TARGET_FOLDER` | No | Destination folder path in Dropbox (Default: `/Telegram_Uploads`) |
| `MAX_FILES_IN_FOLDER` | No | Maximum number of files to retain before pruning oldest (Default: `2`) |

---

## 🔑 Generating Dropbox Permanent Refresh Token

Run the included token generator locally:

```bash
python get_refresh_token.py
```

Follow the prompts to authorize your app with offline access and paste the generated `DROPBOX_REFRESH_TOKEN` into your GitHub repository secrets.

---

## 🚀 GitHub Actions CI Pipeline

The pipeline workflow (`.github/workflows/bot.yml`) features:
- **Pre-Flight Secrets Audit**: Automatically verifies credentials before starting and provides clear diagnostic notices.
- **Rich Job Summary**: Generates a deployment dashboard table in `$GITHUB_STEP_SUMMARY`.
- **Manual Dispatch with Inputs**: Customize execution window, retention cap, and log level on-demand.
- **Folded Log Groups**: Structured, foldable console logs in GitHub Actions for clean auditing.

---

## ☁️ Deploy to Northflank (Free 24/7 Cloud Hosting)

Northflank offers a free Developer tier (512 MB RAM, 0.2 vCPU) capable of running this bot continuously 24/7 without sleeping.

### Deployment Steps:
1. Sign up for free at [northflank.com](https://northflank.com).
2. Create a new **Project**.
3. Click **Create Service** ➔ Select **Deployment** service.
4. Set **Source**: Link your GitHub account and select this repository (`main` branch).
5. Set **Build**: Choose **Dockerfile** (Northflank will auto-detect the root `Dockerfile`).
6. Set **Service Type**: Select **Web Service** or **Worker Service**.
   - If Web Service: Set Port to `8000` (HTTP health check endpoint automatically responds with `200 OK`).
   - If Worker: No port needed.
7. Under **Environment Variables**, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `DROPBOX_APP_KEY`
   - `DROPBOX_APP_SECRET`
   - `DROPBOX_REFRESH_TOKEN`
   - `AUTHORIZED_USER_IDS` *(optional)*
   - `DROPBOX_TARGET_FOLDER` *(optional, default `/Telegram_Uploads`)*
   - `MAX_FILES_IN_FOLDER` *(optional, default `2`)*
8. Click **Deploy Service**.

---

## 📄 License

MIT License. Designed for automated cloud data ingestion.