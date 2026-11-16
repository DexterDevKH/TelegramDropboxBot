#!/usr/bin/env python3
"""
Dropbox OAuth 2.0 Permanent Offline Refresh Token Generator
Production-ready utility using Python standard library (zero external dependencies).
Generates permanent offline refresh tokens for long-running bots and GitHub Actions CI.
"""

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

def main():
    print("┌" + "─" * 68 + "┐")
    print("│ ⚡ DROPBOX OAUTH 2.0 PERMANENT REFRESH TOKEN GENERATOR            │")
    print("├" + "─" * 68 + "┤")
    print("│ Generates permanent offline refresh tokens for GitHub Actions CI   │")
    print("└" + "─" * 68 + "┘\n")

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

    print("\n" + "─" * 70)
    print("📋 STEP 1: Open the authorization URL in your web browser:")
    print(f"\n  👉 {url}\n")
    try:
        webbrowser.open(url)
        print("  (Browser tab automatically opened)")
    except Exception:
        pass
    print("📋 STEP 2: Sign in, approve permissions, and copy the authorization code.")
    print("─" * 70)

    code = input("\n📥 Paste Authorization Code here: ").strip()
    if not code:
        print("\n❌ Error: Authorization code cannot be empty.")
        sys.exit(1)

    print("\n⏳ Exchanging authorization code for permanent refresh token...")

    post_data = urllib.parse.urlencode({
        "code": code,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    basic_auth = base64.b64encode(f"{app_key}:{app_secret}".encode("utf-8")).decode("ascii")

    req = urllib.request.Request(
        "https://api.dropbox.com/oauth2/token",
        data=post_data,
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TelegramDropboxBot/3.1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
            refresh_token = payload.get("refresh_token")

            if refresh_token:
                print("\n┌" + "─" * 68 + "┐")
                print("│ ✅ AUTHORIZATION SUCCESSFUL!                                       │")
                print("├" + "─" * 68 + "┤")
                print("│ Add this value to your GitHub Repository Secrets:                  │")
                print("│ Secret Name: DROPBOX_REFRESH_TOKEN                                 │")
                print("└" + "─" * 68 + "┘\n")
                print(f"DROPBOX_REFRESH_TOKEN:\n{refresh_token}\n")
                print("─" * 70)
            else:
                print("\n⚠️ Warning: No refresh_token returned in OAuth payload.")
                print("Payload:", json.dumps(payload, indent=2))
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        print("\n┌" + "─" * 68 + "┐")
        print(f"│ ❌ TOKEN EXCHANGE FAILED (HTTP {err.code})                         │")
        print("└" + "─" * 68 + "┘")
        print(f"Details: {err_body}\n")
        print("💡 Tip: Ensure App Key and App Secret are correct and authorization code is fresh.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌ Network or API Error: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
