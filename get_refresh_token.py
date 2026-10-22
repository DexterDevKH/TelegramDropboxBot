#!/usr/bin/env python3
import urllib.parse
import requests

def main():
    print("=" * 60)
    print("Dropbox OAuth 2.0 Permanent Token Generator")
    print("=" * 60)
    app_key = input("Enter Dropbox App Key: ").strip()
    app_secret = input("Enter Dropbox App Secret: ").strip()

    if not app_key or not app_secret:
        print("Both App Key and Secret are required.")
        return

    url = (
        f"https://www.dropbox.com/oauth2/authorize?"
        f"client_id={urllib.parse.quote(app_key)}&"
        f"response_type=code&token_access_type=offline"
    )
    print(f"\n1. Open: {url}")
    print("2. Approve permissions and copy the authorization code.")
    code = input("\nEnter Code: ").strip()

    res = requests.post(
        "https://api.dropbox.com/oauth2/token",
        data={"code": code, "grant_type": "authorization_code"},
        auth=(app_key, app_secret)
    )

    if res.status_code == 200:
        token = res.json().get("refresh_token")
        print("\n" + "=" * 60)
        print(f"DROPBOX_REFRESH_TOKEN:\n{token}")
        print("=" * 60)
    else:
        print(f"Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    main()