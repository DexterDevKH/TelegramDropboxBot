#!/usr/bin/env python3
"""
Telegram Webhook Setup Utility
Quickly configure, inspect, or remove Telegram webhooks for the Cloudflare Worker gateway.
"""

import os
import sys
import argparse
import requests

def main():
    parser = argparse.ArgumentParser(description="Manage Telegram Bot Webhook configuration.")
    parser.add_argument("--set", metavar="URL", help="Set webhook endpoint URL (e.g. https://your-worker.workers.dev)")
    parser.add_argument("--secret", metavar="TOKEN", help="Optional secret token for verification (X-Telegram-Bot-Api-Secret-Token)")
    parser.add_argument("--info", action="store_true", help="Inspect current webhook registration status")
    parser.add_argument("--delete", action="store_true", help="Remove active webhook and return to polling mode")
    parser.add_argument("--bot-token", metavar="TOKEN", help="Override TELEGRAM_BOT_TOKEN environment variable")

    args = parser.parse_args()

    token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ Error: Missing Telegram Bot Token.")
        print("Please export TELEGRAM_BOT_TOKEN or pass --bot-token <TOKEN>")
        sys.exit(1)

    base_url = f"https://api.telegram.org/bot{token}"

    if args.set:
        url = args.set.strip()
        print(f"📡 Registering webhook endpoint: {url}")
        params = {"url": url}
        if args.secret:
            params["secret_token"] = args.secret.strip()
        
        resp = requests.post(f"{base_url}/setWebhook", json=params, timeout=15)
        res = resp.json()
        if res.get("ok"):
            print("✅ Webhook successfully registered!")
            print(f"Description: {res.get('description')}")
        else:
            print(f"❌ Failed to set webhook: {res}")
            sys.exit(1)

    elif args.delete:
        print("🗑️ Deleting active webhook...")
        resp = requests.post(f"{base_url}/deleteWebhook", json={"drop_pending_updates": False}, timeout=15)
        res = resp.json()
        if res.get("ok"):
            print("✅ Webhook successfully removed.")
        else:
            print(f"❌ Failed to delete webhook: {res}")
            sys.exit(1)

    else:
        # Default: Display webhook info
        print("🔍 Querying Telegram webhook status...")
        resp = requests.get(f"{base_url}/getWebhookInfo", timeout=15)
        res = resp.json()
        if res.get("ok"):
            info = res.get("result", {})
            current_url = info.get("url")
            print("──────────────────────────────────────────")
            print(f"🌐 Active Webhook URL: {current_url if current_url else '(None / Polling mode)'}")
            print(f"📦 Pending Update Count: {info.get('pending_update_count', 0)}")
            if info.get("last_error_date"):
                print(f"⚠️ Last Error Date: {info.get('last_error_date')}")
                print(f"⚠️ Last Error Message: {info.get('last_error_message')}")
            print("──────────────────────────────────────────")
        else:
            print(f"❌ Failed to retrieve webhook info: {res}")
            sys.exit(1)

if __name__ == "__main__":
    main()
