# ⚡ Serverless Telegram Webhook Gateway

This folder contains the serverless edge trigger that makes the Telegram to Dropbox pipeline **completely event-driven**—no need to run a server or GitHub Actions 24/7.

```
Telegram User ──> Cloudflare Worker (Instant / Free) ──> GitHub Actions Runner (On-Demand) ──> Dropbox
```

---

## 🚀 Quick Setup (2 Minutes)

### Step 1: Create a GitHub Personal Access Token (PAT)
1. Go to **GitHub Settings** ➔ **Developer Settings** ➔ **Personal access tokens** ➔ **Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Name it `Telegram Webhook Dispatcher`.
4. Select the **`repo`** scope (or Fine-grained token with `Actions: Read and Write`).
5. Copy your new token.

---

### Step 2: Deploy the Cloudflare Worker

#### Option A: 1-Click via Cloudflare Web Dashboard (No Tools Needed)
1. Sign in to [Cloudflare Dashboard](https://dash.cloudflare.com/) (100% free account, 100k requests/day).
2. Go to **Compute (Workers) & Pages** ➔ **Create application** ➔ **Create Worker**.
3. Name it `telegram-dropbox-sync-trigger` and click **Deploy**.
4. Click **Edit code** and paste the entire contents of [`worker.js`](file:///c:/Users/Dexter/Documents/GitHub/TelegramDropboxBot/webhook/worker.js). Click **Deploy**.
5. Go to your Worker's **Settings** ➔ **Variables and Secrets** and add:
   - `GH_PAT`: Your GitHub Personal Access Token from Step 1.
   - `GH_REPO`: `DexterDevKH/TelegramDropboxBot` (or your repo name).
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token.
   - `AUTHORIZED_USER_IDS`: Your Telegram numeric User ID.
6. Copy your Worker URL (e.g. `https://telegram-dropbox-sync-trigger.<your-subdomain>.workers.dev`).

#### Option B: Deploy via CLI (Wrangler)
From the repository root:
```bash
cd webhook
npx wrangler deploy
npx wrangler secret put GH_PAT
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put AUTHORIZED_USER_IDS
```

---

### Step 3: Register the Webhook with Telegram

Use the built-in helper utility [`setup_webhook.py`](file:///c:/Users/Dexter/Documents/GitHub/TelegramDropboxBot/webhook/setup_webhook.py):

```bash
# Register the webhook
python webhook/setup_webhook.py --bot-token "YOUR_TELEGRAM_BOT_TOKEN" --set "https://telegram-dropbox-sync-trigger.<your-subdomain>.workers.dev"

# Verify active status
python webhook/setup_webhook.py --bot-token "YOUR_TELEGRAM_BOT_TOKEN" --info
```

*To revert back to continuous polling anytime:*
```bash
python webhook/setup_webhook.py --bot-token "YOUR_TELEGRAM_BOT_TOKEN" --delete
```

---

## 🎯 How It Operates

1. **User sends a document/video/audio to the bot.**
2. Cloudflare Worker wakes up instantly (~15ms) and sends you an acknowledgment on Telegram:
   > ⚡ **TRANSFER REQUEST RECEIVED**  
   > 📄 Target: `video.mp4`  
   > 🛰️ Status: *Dispatching GitHub Actions cloud runner...*  
   > ⏳ *Transfer engine will engage in ~25-30s.*
3. Worker calls GitHub's `repository_dispatch` API with the message ID.
4. GitHub Actions spins up the runner, fetches the file via Telethon MTProto (supporting up to 2 GB), uploads it to Dropbox, attaches the direct copy button, and cleanly shuts down.
5. If you send multiple files in an album, the runner automatically stays alive for 3 minutes (`IDLE_KEEP_ALIVE_SECONDS`) to process follow-up files without restarting.
