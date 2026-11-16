#!/usr/bin/env python3
"""
Telegram to Dropbox Cloud Sync & iOS IPA Workflow Builder
High-Performance Native Rust Core Bridge (v3.1.0)

Delegates execution to the compiled native Rust binary with zero overhead,
maintaining 100% backward compatibility with existing CI pipelines.
"""

import os
import sys
import subprocess

def find_binary():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_name = "telegram_dropbox_bot.exe" if sys.platform == "win32" else "telegram_dropbox_bot"
    
    candidates = [
        os.path.join(base_dir, "target", "release", bin_name),
        os.path.join(base_dir, "target", "debug", bin_name),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return [c]
    
    # Fallback to cargo run
    return ["cargo", "run", "--release", "--"]

def main():
    cmd = find_binary() + sys.argv[1:]
    try:
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"FATAL: Failed to execute Rust core engine: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
