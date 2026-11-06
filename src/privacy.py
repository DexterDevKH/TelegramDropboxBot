"""
Privacy Shield & Log Sanitization Module
"""

import sys
from typing import Optional

def mask_filename(name: str, enabled: bool = True) -> str:
    """Masks filename for privacy in console logs (e.g. 'my_secret_file.pdf' -> 'my***e.pdf')."""
    if not enabled or not name:
        return name
    if "." in name:
        base, ext = name.rsplit(".", 1)
        if len(base) <= 3:
            masked_base = "***"
        else:
            masked_base = base[:2] + "***" + base[-1]
        return f"{masked_base}.{ext}"
    return name[:2] + "***" if len(name) > 2 else "***"

def mask_user_id(user_id: int, enabled: bool = True) -> str:
    """Masks user ID for privacy in console logs (e.g. 12345678 -> '12***')."""
    if not enabled:
        return str(user_id)
    uid_str = str(user_id)
    return uid_str[:2] + "***" if len(uid_str) > 2 else "***"

def register_github_mask(secret_value: Optional[str]) -> None:
    """Registers dynamic mask in GitHub Actions runner so secret values never leak."""
    if secret_value and secret_value.strip():
        print(f"::add-mask::{secret_value.strip()}", file=sys.stdout, flush=True)

