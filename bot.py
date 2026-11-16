#!/usr/bin/env python3
"""
Telegram to Dropbox Cloud Sync & iOS IPA Workflow Builder
Production Entrypoint (Pure Python Architecture)
"""

import sys


def main():
    if "--check-versions" in sys.argv:
        from src.version_checker import (
            check_all_ios_versions,
            format_version_status_text,
            format_version_alert_text,
            send_telegram_alert_http,
        )
        import os

        print("Checking iOS App Store versions for YouTube and YouTube Music...")
        apps, new_alerts = check_all_ios_versions()
        print(format_version_status_text(apps))

        if new_alerts:
            print(f"\nFound {len(new_alerts)} new version alert(s)!")
            bot_tok = os.getenv("TELEGRAM_BOT_TOKEN")
            auth_raw = os.getenv("AUTHORIZED_USER_IDS", "")
            recipients = [
                int(i.strip()) for i in auth_raw.split(",") if i.strip().isdigit()
            ]

            for app_info, prev_ver in new_alerts:
                alert_text = format_version_alert_text(app_info, prev_ver)
                print("\n" + alert_text)
                if bot_tok and recipients:
                    send_telegram_alert_http(bot_tok, recipients, alert_text)
                    print(f"Alert dispatched to {len(recipients)} recipient(s).")
        else:
            print("\nAll tracked iOS apps are up to date.")
        sys.exit(0)

    from src.engine import main as engine_main

    engine_main()


if __name__ == "__main__":
    main()
