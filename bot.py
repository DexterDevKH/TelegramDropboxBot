#!/usr/bin/env python3
"""
Telegram to Dropbox Cloud Sync & iOS IPA Workflow Builder
Production Entrypoint

Author: Automated Cloud Solutions / DexterDevKH
Architecture: High-performance Telegram MTProto (Telethon) binary ingestion,
              streaming chunked uploads to Dropbox, FIFO folder retention,
              native Telegram Bot API v7.0+ CopyTextButton, and interactive /build engine.
"""

import sys
from src.engine import main

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
    except Exception as exc:
        print(f"FATAL: Application terminated unexpectedly: {exc}", file=sys.stderr)
        sys.exit(1)
