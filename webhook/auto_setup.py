#!/usr/bin/env python3
"""
Telegram Webhook & GitHub Actions Dispatch Setup Utility
Interactive and automated tool to configure, verify, test, and manage webhooks
and GitHub Actions on-demand sync dispatchers.
"""

import os
import sys
import argparse
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def print_banner():
    print("""
┌────────────────────────────────────────────────────────────────────┐
│ ⚡ TELEGRAM WEBHOOK & GITHUB ACTIONS AUTO-SETUP UTILITY             │
└────────────────────────────────────────────────────────────────────┘
""")

def get_env_or_prompt(key: str, prompt: str, default: str = "") -> str:
    val = os.getenv(key, "").strip()
    if not val and default:
        val = default
    return val

def check_telegram(bot_token: str) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        resp = requests.get(url, timeout=10)
        res = resp.json()
        if res.get("ok"):
            bot_info = res.get("result", {})
            return {"ok": True, "username": bot_info.get("username"), "first_name": bot_info.get("first_name")}
        return {"ok": False, "error": res.get("description", "Unknown error")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def check_webhook_info(bot_token: str) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        resp = requests.get(url, timeout=10)
        res = resp.json()
        if res.get("ok"):
            return {"ok": True, "info": res.get("result", {})}
        return {"ok": False, "error": res.get("description", "Unknown error")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def set_webhook(bot_token: str, webhook_url: str, secret_token: str = "") -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    params = {"url": webhook_url}
    if secret_token:
        params["secret_token"] = secret_token

    print(f"📡 Registering webhook URL: {webhook_url}")
    if secret_token:
        print("🔒 Attaching secret verification token...")

    try:
        resp = requests.post(url, json=params, timeout=15)
        res = resp.json()
        if res.get("ok"):
            print("✅ Telegram Webhook registered successfully!")
            print(f"ℹ️  Telegram Response: {res.get('description')}")
            return True
        else:
            print(f"❌ Failed to set webhook: {res.get('description')}")
            return False
    except Exception as exc:
        print(f"❌ Network error while setting webhook: {exc}")
        return False

def delete_webhook(bot_token: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    print("🗑️ Removing Telegram webhook...")
    try:
        resp = requests.post(url, json={"drop_pending_updates": False}, timeout=15)
        res = resp.json()
        if res.get("ok"):
            print("✅ Webhook removed! Bot is back in standard polling mode.")
            return True
        else:
            print(f"❌ Failed to remove webhook: {res.get('description')}")
    except Exception as exc:
        print(f"❌ Network error while deleting webhook: {exc}")
        return False

def set_bot_commands(bot_token: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    commands = [
        {"command": "start", "description": "Display bot welcome and transfer guide"},
        {"command": "status", "description": "Inspect serverless cloud pipeline health"},
        {"command": "ping", "description": "Measure Cloudflare Edge network latency"},
        {"command": "help", "description": "Show operational manual and limits"}
    ]
    print("📋 Registering Telegram interactive menu commands...")
    try:
        resp = requests.post(url, json={"commands": commands}, timeout=10)
        res = resp.json()
        if res.get("ok"):
            print("✅ Telegram Menu Commands registered successfully!")
            return True
        else:
            print(f"❌ Failed to set commands: {res.get('description')}")
            return False
    except Exception as exc:
        print(f"❌ Network error while setting commands: {exc}")
        return False

def check_github_repo(repo: str, pat: str) -> dict:
    url = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramDropbox-Setup-Utility"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {"ok": True, "full_name": data.get("full_name"), "private": data.get("private")}
        return {"ok": False, "status": resp.status_code, "error": resp.text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def trigger_test_dispatch(repo: str, pat: str) -> bool:
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramDropbox-Setup-Utility",
        "Content-Type": "application/json"
    }
    payload = {
        "event_type": "telegram_sync",
        "client_payload": {
            "chat_id": 0,
            "message_id": 0,
            "user_id": 0,
            "has_media": False,
            "file_name": "test_verification_probe.bin",
            "text": "/ping_test"
        }
    }
    print(f"🚀 Triggering test repository_dispatch on '{repo}'...")
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        if resp.status_code in (200, 204):
            print("✅ Test dispatch delivered successfully! Check your GitHub Actions tab.")
            return True
        else:
            print(f"❌ GitHub API Error [{resp.status_code}]: {resp.text}")
            return False
    except Exception as exc:
        print(f"❌ Failed to trigger test dispatch: {exc}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Configure and verify Telegram Webhook and GitHub Actions.")
    parser.add_argument("--set-url", metavar="URL", help="Set webhook endpoint URL (e.g. https://your-server.com/webhook or Cloudflare Worker URL)")
    parser.add_argument("--set-commands", action="store_true", help="Register Telegram interactive menu commands (/start, /status, /ping, /help)")
    parser.add_argument("--secret", metavar="TOKEN", help="Optional secret token for verification (X-Telegram-Bot-Api-Secret-Token)")
    parser.add_argument("--info", action="store_true", help="Display current Telegram webhook status")
    parser.add_argument("--delete", action="store_true", help="Delete active Telegram webhook")
    parser.add_argument("--test-tg", action="store_true", help="Test Telegram bot token connectivity")
    parser.add_argument("--test-gh", action="store_true", help="Test GitHub PAT and repository access")
    parser.add_argument("--dispatch-test", action="store_true", help="Send a test repository_dispatch event to trigger GitHub Actions")
    parser.add_argument("--bot-token", metavar="TOKEN", help="Override TELEGRAM_BOT_TOKEN")
    parser.add_argument("--gh-pat", metavar="TOKEN", help="Override GH_PAT")
    parser.add_argument("--gh-repo", metavar="OWNER/REPO", help="Override GH_REPO")

    args = parser.parse_args()
    print_banner()

    bot_token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    gh_pat = args.gh_pat or os.getenv("GH_PAT", "").strip()
    gh_repo = args.gh_repo or os.getenv("GH_REPO", "DexterDevKH/TelegramDropboxBot").strip()
    secret_token = args.secret or os.getenv("TELEGRAM_SECRET_TOKEN", "").strip()

    # Handle Set Webhook
    if args.set_url:
        if not bot_token:
            print("❌ Error: Missing TELEGRAM_BOT_TOKEN.")
            sys.exit(1)
        success = set_webhook(bot_token, args.set_url.strip(), secret_token)
        if success:
            set_bot_commands(bot_token)
        sys.exit(0 if success else 1)

    # Handle Set Commands Only
    if args.set_commands:
        if not bot_token:
            print("❌ Error: Missing TELEGRAM_BOT_TOKEN.")
            sys.exit(1)
        success = set_bot_commands(bot_token)
        sys.exit(0 if success else 1)

    # Handle Delete Webhook
    if args.delete:
        if not bot_token:
            print("❌ Error: Missing TELEGRAM_BOT_TOKEN.")
            sys.exit(1)
        success = delete_webhook(bot_token)
        sys.exit(0 if success else 1)

    # Handle Test Telegram
    if args.test_tg:
        if not bot_token:
            print("❌ Error: Missing TELEGRAM_BOT_TOKEN.")
            sys.exit(1)
        res = check_telegram(bot_token)
        if res.get("ok"):
            print(f"✅ Telegram Bot Valid: @{res.get('username')} ({res.get('first_name')})")
        else:
            print(f"❌ Telegram Bot Error: {res.get('error')}")
        sys.exit(0 if res.get("ok") else 1)

    # Handle Test GitHub
    if args.test_gh:
        if not gh_pat:
            print("❌ Error: Missing GH_PAT (GitHub Personal Access Token).")
            sys.exit(1)
        res = check_github_repo(gh_repo, gh_pat)
        if res.get("ok"):
            print(f"✅ GitHub Connection Valid: Repository '{res.get('full_name')}' accessible.")
        else:
            print(f"❌ GitHub Connection Error: {res.get('error')}")
        sys.exit(0 if res.get("ok") else 1)

    # Handle Dispatch Test
    if args.dispatch_test:
        if not gh_pat:
            print("❌ Error: Missing GH_PAT (GitHub Personal Access Token).")
            sys.exit(1)
        success = trigger_test_dispatch(gh_repo, gh_pat)
        sys.exit(0 if success else 1)

    # Default / Info Mode: Full diagnostics
    print("🔍 RUNNING COMPREHENSIVE STATUS DIAGNOSTICS...\n")

    # 1. Telegram Check
    if bot_token:
        tg_res = check_telegram(bot_token)
        if tg_res.get("ok"):
            print(f"🤖 Telegram Bot:        @{tg_res.get('username')} (Connected ✅)")
        else:
            print(f"🤖 Telegram Bot:        Error ❌ ({tg_res.get('error')})")

        wh_res = check_webhook_info(bot_token)
        if wh_res.get("ok"):
            info = wh_res["info"]
            curr_url = info.get("url") or "(None - Polling Mode)"
            pending = info.get("pending_update_count", 0)
            last_err = info.get("last_error_message")
            print(f"🌐 Active Webhook URL:  {curr_url}")
            print(f"📦 Pending Updates:     {pending}")
            if last_err:
                print(f"⚠️  Last Webhook Error:  {last_err}")
    else:
        print("🤖 Telegram Bot:        Not Configured ⚠️ (Set TELEGRAM_BOT_TOKEN)")

    # 2. GitHub Check
    if gh_pat:
        gh_res = check_github_repo(gh_repo, gh_pat)
        if gh_res.get("ok"):
            print(f"🐙 GitHub Repository:   {gh_res.get('full_name')} (Authorized ✅)")
        else:
            print(f"🐙 GitHub Repository:   Error ❌ ({gh_res.get('error')})")
    else:
        print("🐙 GitHub PAT:          Not Configured ⚠️ (Set GH_PAT in .env)")

    print("\n────────────────────────────────────────────────────────────────────")
    print("💡 COMMAND CHEATSHEET:")
    print("  • Set Webhook:      python webhook/auto_setup.py --set-url <YOUR_URL>")
    print("  • Inspect Status:   python webhook/auto_setup.py --info")
    print("  • Remove Webhook:   python webhook/auto_setup.py --delete")
    print("  • Test GitHub CI:   python webhook/auto_setup.py --dispatch-test")
    print("────────────────────────────────────────────────────────────────────\n")

if __name__ == "__main__":
    main()
