#!/usr/bin/env python3
import urllib.parse
import requests

def main():
    print("=" * 60)
    print("Dropbox OAuth 2.0 Refresh Token Generator")
    print("=" * 60)
    
    app_key = input("Enter your Dropbox App Key: ").strip()
    app_secret = input("Enter your Dropbox App Secret: ").strip()
    
    if not app_key or not app_secret:
        print("Error: Both App Key and App Secret are required.")
        return

    auth_url = (
        f"https://www.dropbox.com/oauth2/authorize?"
        f"client_id={urllib.parse.quote(app_key)}&"
        f"response_type=code&"
        f"token_access_type=offline"
    )

    print("\n1. Open this URL in your web browser:")
    print(auth_url)
    print("\n2. Click 'Allow' to grant access.")
    print("3. Copy the authorization code shown on screen.")
    
    auth_code = input("\nPaste the Authorization Code here: ").strip()
    if not auth_code:
        print("Error: Authorization Code is required.")
        return

    token_url = "https://api.dropbox.com/oauth2/token"
    data = {
        "code": auth_code,
        "grant_type": "authorization_code",
    }
    
    print("\nRequesting refresh token from Dropbox...")
    response = requests.post(token_url, data=data, auth=(app_key, app_secret))
    
    if response.status_code == 200:
        res_data = response.json()
        refresh_token = res_data.get("refresh_token")
        print("\n" + "=" * 60)
        print("SUCCESS! Your permanent Dropbox Refresh Token:")
        print("=" * 60)
        print(f"\nDROPBOX_REFRESH_TOKEN:\n{refresh_token}\n")
        print("Add this to your GitHub Repository Secrets alongside:")
        print(f"DROPBOX_APP_KEY: {app_key}")
        print(f"DROPBOX_APP_SECRET: {app_secret}")
        print("=" * 60)
    else:
        print(f"\nFailed to get token (HTTP {response.status_code}):")
        print(response.text)

if __name__ == "__main__":
    main()