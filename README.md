# ⚡ Telegram to Dropbox Cloud Sync & iOS IPA Workflow Builder

[![Engine Version](https://img.shields.io/badge/version-3.0.0-blue.svg)](https://github.com/DexterDevKH/TelegramDropboxBot)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Cloudflare Workers](https://img.shields.io/badge/edge-Cloudflare%20Workers-F38020.svg?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![GitHub Actions](https://img.shields.io/badge/ci-GitHub%20Actions-2088FF.svg?logo=githubactions&logoColor=white)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An enterprise-grade, serverless cloud pipeline combining high-speed **Telegram-to-Dropbox synchronization** (up to 2.0 GB via Telethon MTProto) and an interactive **iOS IPA GitHub Actions Workflow Builder** (`/build` for DTKACE Plus, DTLite Plus, and DTMusicUltimate).

Powered by a 24/7 **Cloudflare Worker Global Edge Gateway** (<20ms latency) and on-demand **GitHub Actions CI Runners** (0 idle cost).

---

## 🌟 Key Architecture & Highlights

- **🚀 2.0 GB MTProto Direct Binary Ingestion**: Full MTProto protocol implementation streaming files up to 2,000 MB directly from Telegram's media cluster.
- **🔗 Auto-Download for Dropped Links & GitHub Actions Artifacts**: Drop any direct download URL or GitHub Actions artifact link (e.g. `https://github.com/DexterDevKH/ytkace/actions/runs/.../artifacts/...`) directly in chat. The bot automatically fetches the artifact/file, unzips single binaries (e.g. `.deb` / `.ipa`), and streams chunked uploads to Dropbox with dual-phase progress bars.
- **⚡ 100% Serverless Edge-First Operation**:
  - **Cloudflare Worker (`webhook/`)**: Free global edge gateway running 24/7. Handles commands (`/build`, `/status`, `/ping`, `/help`, `/cancel`), inline toggle menus, parameter prompts, and dispatches GitHub Actions pipelines.
  - **On-Demand CI Runner (`bot.py` / `src/`)**: Boots on Ubuntu runner only when a payload arrives or build tracking is needed, streams chunked uploads to Dropbox, and terminates immediately (zero hosting fees).
- **📊 Real-Time Dual-Phase Progress Updates**:
  - **Phase 1**: Throttled MTProto download tracking with live transfer speed, ETA, and visual block progress bar (`[████████░░░░] 66.7%`).
  - **Phase 2**: Chunked streaming upload session tracking (configurable 8 MB / 16 MB chunks) with live upload speed and ETA.
- **📋 Direct 1-Tap OS Clipboard Copy**: Powered by Telegram Bot API v7.0+ `CopyTextButton` — directly copies the direct download link (`dl=1`) straight into iOS/Android/Desktop clipboard with a single tap.
- **🧩 Interactive iOS IPA Builder (`/build`)**:
  - Target repositories: **DTKACE Plus**, **DTLite Plus**, and **DTMusicUltimate**.
  - **Stateless Bitmask Engine**: Toggles 13 modular tweak extensions instantly without brittle regex parsing or server session limits.
  - Single-use force reply prompts with clean chat auto-cleanup (prompts and input messages are automatically deleted upon receipt).
- **♻️ Automated FIFO Folder Retention**: Automatically prunes the oldest files when folder capacity exceeds the configured cap (`MAX_FILES_IN_FOLDER`).
- **📁 Smart Destination Routing**: Automatically stores `.ipa` files inside the designated vault folder (`DROPBOX_TARGET_FOLDER`), while all non-IPA payloads (e.g. rootless `.deb` tweaks, documents, media) are uploaded outside the folder directly to the Dropbox root (`/`) with retention pruning safely restricted to the dedicated folder.
- **🛡️ Privacy Shield & Log Sanitization**: Automatically masks transferred filenames (`se***t.pdf`), redacts Telegram user IDs, hides Dropbox account details, and dynamically registers `::add-mask::` on all secrets in GitHub Actions console logs.
- **🧹 Auto-Purge Run History**: Automated cleanup workflow (`cleanup.yml`) and pre/post steps automatically delete completed workflow runs and execution logs from GitHub Actions.

---

## 🏗️ System Architecture

```text
[ Telegram User ]
       │
       ▼ (Webhook Update)
[ Cloudflare Global Edge Worker (webhook/) ]
       │
       ├─► Instant Commands: /status, /ping, /help, /cancel
       ├─► Interactive /build Flow: App Select, Bitmask Extension Matrix, Input Prompts
       │
       ▼ (repository_dispatch: telegram_sync | track_build)
[ GitHub Actions On-Demand Runner (Python 3.11) ]
       │
       ├─► Phase 1: High-Speed MTProto Binary Ingestion (up to 2 GB)
       │    └─► Live in-place throttled progress bar updates to Telegram
       │
       ├─► Phase 2: Chunked Upload Session (8 MB blocks)
       │    └─► Live cloud upload speed & ETA updates to Telegram
       │
       ▼
[ Dropbox Cloud Storage Vault ]
       │
       ├─► FIFO Retention Auto-Rotation (Prunes oldest if count > cap)
       ├─► Shared Link Generation (?dl=1 Direct Binary URL)
       │
       ▼
[ Final Telegram Presentation Card ]
       ├── [ 📋 Copy Direct Link ] (Native 1-Tap OS Clipboard Copy)
       └── [ 🌐 Open in Dropbox ]  (Web Browser Link)
```

---

## 🕹️ Telegram Commands Reference

| Command | Scope | Description |
| :--- | :---: | :--- |
| `/build` | Edge Gateway | Opens interactive menu to configure parameters and trigger GitHub Actions builds for DTKACE, DTLite, or DTMusic |
| `/status` or `/info` | Edge Gateway | Displays real-time gateway health, cloud quota, target repo, and runner state |
| `/ping` | Edge Gateway | Measures round-trip edge latency (~15ms) |
| `/cancel` | Edge Gateway | Cleanly aborts any active parameter prompt and removes leftover messages |
| `/help` or `/start` | Edge Gateway | Displays the interactive operational manual |

> 💡 **Quick Ingestion**:
> • **Upload Media**: Forward or upload any media file (document, video, audio, IPA, archive) to trigger automatic Dropbox sync.
> • **Drop Links**: Paste any direct download URL or GitHub Actions artifact link (e.g., `https://github.com/DexterDevKH/ytkace/actions/runs/42453711687/artifacts/13606462977`) to auto-download and push directly to Dropbox.

---

## 📁 Project Structure

```text
TelegramDropboxBot/
├── .github/
│   └── workflows/
│       ├── bot.yml            # Streamlined on-demand CI sync & build tracker pipeline
│       └── cleanup.yml        # Auto-purge completed workflow runs & history daemon
├── src/                       # Refactored, high-performance modular Python core engine
│   ├── __init__.py            # Package root & metadata
│   ├── config.py              # Strongly-typed configuration loader & validation
│   ├── constants.py           # Build targets catalog & tweak extensions config
│   ├── privacy.py             # Privacy shield, log sanitization & GitHub mask registration
│   ├── formatters.py          # Formats sizes, ETAs, filenames, URLs & bitmasks
│   ├── dropbox_service.py     # Dropbox OAuth, streaming chunked uploads & FIFO retention
│   ├── github_service.py      # GitHub Actions workflow dispatch & release inspector
│   ├── telegram_bot.py        # Telethon client wrapper & safe edit/progress handling
│   ├── ui.py                  # Presentation cards, buttons & Bot API v7.0+ CopyTextButton
│   └── engine.py              # Application lifecycle (On-demand runner & daemon modes)
├── webhook/                   # Edge gateway (Cloudflare Worker v2)
│   ├── targets.js             # Build target catalog & tweak extensions config
│   ├── state.js               # Stateless bitmask engine & resilient multi-tier session storage
│   ├── telegram.js            # Telegram Bot API client wrapper with Markdown parse recovery
│   ├── github.js              # GitHub Actions REST API dispatcher & tracker
│   ├── ui.js                  # Markdown presentation cards & button matrices
│   └── worker.js              # Cloudflare Worker master edge router (Fetch & Scheduled)
├── tests/                     # Unit test suite
│   ├── test_formatters.py     # Unit tests for formatting and bitmask codecs
│   ├── test_privacy.py        # Unit tests for privacy shield and masking
│   └── test_constants.py      # Unit tests for catalog definitions
├── bot.py                     # Clean CLI & CI entrypoint (delegates to src.engine)
├── get_refresh_token.py       # Dropbox OAuth 2.0 permanent refresh token generator
├── wrangler.toml              # Cloudflare Workers configuration
├── package.json               # Node.js project manifest & deployment scripts
├── requirements.txt           # Python production dependencies
└── .env.example               # Reference environment variables
```

---

## ⚙️ Configuration & Secrets

### 1. GitHub Repository Secrets
Configure in **Settings ➔ Secrets and variables ➔ Actions**:

| Secret Name | Required | Description |
| :--- | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | Telegram Bot API token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API_ID` | **Yes** | Telegram App API ID from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | **Yes** | Telegram App API Hash from [my.telegram.org](https://my.telegram.org) |
| `DROPBOX_APP_KEY` | **Yes** | Dropbox App Key from [Dropbox App Console](https://www.dropbox.com/developers/apps) |
| `DROPBOX_APP_SECRET` | **Yes** | Dropbox App Secret from Dropbox App Console |
| `DROPBOX_REFRESH_TOKEN` | **Yes** | Permanent OAuth 2.0 offline refresh token (generate via `python get_refresh_token.py`) |
| `GH_PAT` | **Yes** | GitHub Personal Access Token with `repo` or `actions:write` permissions |
| `AUTHORIZED_USER_IDS` | No | Comma-separated Telegram User IDs allowed to use the bot (e.g. `123456,789012`). Empty = public. |
| `DROPBOX_TARGET_FOLDER` | No | Destination folder in Dropbox (Default: `/IPA`) |
| `MAX_FILES_IN_FOLDER` | No | Maximum number of files to retain in folder before FIFO pruning (Default: `2`) |
| `PRIVACY_MODE` | No | Mask filenames, user IDs, and paths in console logs (Default: `true`) |

### 2. Cloudflare Worker Environment Variables
Configure in your Cloudflare Dashboard under **Workers & Pages ➔ telegramdropboxbot ➔ Settings ➔ Variables**:

| Variable Name | Type | Description |
| :--- | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | Secret | Your Telegram Bot Token |
| `GH_PAT` | Secret | GitHub Personal Access Token with `repo` / `actions:write` permission |
| `GH_REPO` | Plain Text | Target repository name (Default: `DexterDevKH/TelegramDropboxBot`) |
| `AUTHORIZED_USER_IDS` | Plain Text | Comma-separated authorized Telegram user IDs |
| `TELEGRAM_SECRET_TOKEN` | Secret | (Optional) Verification token for `X-Telegram-Bot-Api-Secret-Token` |

---

## 🔑 Generating Dropbox Permanent Refresh Token

Dropbox access tokens expire after 4 hours. Run the included offline refresh token generator locally:

```bash
python get_refresh_token.py
```

Follow the console instructions to authorize your Dropbox app and paste the generated `DROPBOX_REFRESH_TOKEN` into your GitHub repository secrets.

---

## 🚀 Cloudflare Worker Deployment

### Deploy via Wrangler CLI

```bash
npm install
npx wrangler deploy
```

### Set Telegram Webhook

Point your Telegram bot to your deployed Cloudflare Worker URL:

```bash
curl -F "url=https://telegramdropboxbot.<your-subdomain>.workers.dev" \
     -F "secret_token=your_optional_secret" \
     https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/setWebhook
```

---

## 🧪 Running Unit Tests

Run the included unit test suite to verify formatters, bitmask engine, and privacy filters:

```bash
python -m unittest discover -s tests
```

---

## 📄 License

MIT License. Designed and engineered for high-performance cloud data operations.
