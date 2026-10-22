#!/usr/bin/env python3
"""
Dropbox OAuth 2.0 Permanent Refresh Token Generator
Utility script to generate offline refresh tokens for long-running bots and CI pipelines.
"""

import urllib.parse
import requests
import sys

def main():
    print("┌" + "─" * 66 + "┐")
    print("│ ⚡ DROPBOX OAUTH 2.0 REFRESH TOKEN GENERATOR                      │")
    print("├" + "─" * 66 + "┤")
    print("│ Generates permanent offline refresh tokens for GitHub Actions CI  │")
    print("└" + "─" * 66 + "┘\n")

    app_key = input("🔑 Enter Dropbox App Key: ").strip()
    app_secret = input("🔒 Enter Dropbox App Secret: ").strip()

    if not app_key or not app_secret:
        print("\n❌ Error: Both App Key and App Secret are required.")
        sys.exit(1)

    url = (
        f"https://www.dropbox.com/oauth2/authorize?"
        f"client_id={urllib.parse.quote(app_key)}&"
        f"response_type=code&token_access_type=offline"
    )

    print("\n" + "─" * 68)
    print("📋 STEP 1: Open the authorization URL in your browser:")
    print(f"\n  👉 {url}\n")
    print("📋 STEP 2: Sign in, approve app permissions, and copy the code.")
    print("─" * 68)

    code = input("\n📥 Paste Authorization Code here: ").strip()
    if not code:
        print("\n❌ Error: Authorization code cannot be empty.")
        sys.exit(1)

    print("\n⏳ Exchanging authorization code for permanent refresh token...")

    try:
        res = requests.post(
            "https://api.dropbox.com/oauth2/token",
            data={"code": code, "grant_type": "authorization_code"},
            auth=(app_key, app_secret),
            timeout=15
        )

        if res.status_code == 200:
            data = res.json()
            refresh_token = data.get("refresh_token")
            access_token = data.get("access_token")

            print("\n┌" + "─" * 66 + "┐")
            print("│ ✅ AUTHORIZATION SUCCESSFUL                                       │")
            print("├" + "─" * 66 + "┤")
            print("│ Add this value to your GitHub Repository Secrets:                 │")
            print("│ Secret Name: DROPBOX_REFRESH_TOKEN                                │")
            print("└" + "─" * 66 + "┘\n")
            print(f"DROPBOX_REFRESH_TOKEN:\n{refresh_token}\n")
            print("─" * 68)
        else:
            print("\n┌" + "─" * 66 + "┐")
            print(f"│ ❌ TOKEN EXCHANGE FAILED (HTTP {res.status_code})                         │")
            print("└" + "─" * 66 + "┘")
            print(f"Details: {res.text}\n")
            print("💡 Tip: Verify your App Key and Secret, and ensure the code hasn't expired.")
    except Exception as exc:
        print(f"\n❌ Network or API Error: {exc}")

if __name__ == "__main__":
    main()