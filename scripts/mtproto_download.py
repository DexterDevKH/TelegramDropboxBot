#!/usr/bin/env python3
"""
MTProto Telegram Media Downloader
High-performance direct binary download via Telethon for Telegram media of any size (up to 2 GB).
Bypasses the 20 MB Telegram Bot API getFile limit.
"""

import os
import sys
import time
import asyncio
from telethon import TelegramClient
from telethon.sessions import MemorySession


async def download():
    if len(sys.argv) < 4:
        print("Usage: mtproto_download.py <chat_id> <message_id> <dest_path>", file=sys.stderr)
        sys.exit(1)

    chat_id = int(sys.argv[1])
    message_id = int(sys.argv[2])
    dest_path = sys.argv[3]

    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not api_id_raw or not api_hash or not bot_token:
        print("ERROR: Missing TELEGRAM_API_ID, TELEGRAM_API_HASH, or TELEGRAM_BOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    api_id = int(api_id_raw)
    client = TelegramClient(MemorySession(), api_id, api_hash)
    await client.start(bot_token=bot_token)

    try:
        msg = await client.get_messages(chat_id, ids=message_id)
        if not msg or not msg.media:
            print(f"ERROR: Message {message_id} in {chat_id} does not contain downloadable media", file=sys.stderr)
            sys.exit(1)

        last_update = [0.0]

        def progress_callback(current, total):
            now = time.time()
            if (now - last_update[0] >= 1.5) or (current >= total):
                last_update[0] = now
                print(f"PROGRESS:{current}:{total}", flush=True)

        # Ensure destination directory exists
        dest_dir = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(dest_dir, exist_ok=True)

        await client.download_media(msg, file=dest_path, progress_callback=progress_callback)
        print("DONE", flush=True)
    finally:
        await client.disconnect()


def main():
    asyncio.run(download())


if __name__ == "__main__":
    main()
