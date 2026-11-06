"""
Metric, Time, URL & Bitmask Presentation Formatting Utilities (v3.0.0)
"""

import time
from typing import List, Dict, Any, Optional

def format_size(size_bytes: int) -> str:
    """Converts raw byte counts into clean human-readable formatted strings."""
    if size_bytes <= 0:
        return "0 B"
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if val < 1024.0:
            return f"{val:.2f} {unit}"
        val /= 1024.0
    return f"{val:.2f} TB"

def format_eta(seconds: float) -> str:
    """Converts duration in seconds into clean human-readable ETA."""
    if seconds < 0 or seconds > 86400:
        return "Calculating..."
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60}s"
    else:
        return f"{s // 3600}h {(s % 3600) // 60}m"

def render_progress_bar(percent: float, bar_length: int = 12) -> str:
    """Renders a sleek visual block progress bar: [████████░░░░] 66.7%"""
    clamped = max(0.0, min(100.0, percent))
    filled = int(round(bar_length * (clamped / 100.0)))
    filled = max(0, min(bar_length, filled))
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {clamped:.1f}%"

def sanitize_filename(name: str) -> str:
    """Sanitizes filename for cross-platform cloud storage safety."""
    if not name:
        return f"payload_{int(time.time())}.bin"
    clean = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
    return clean if clean else f"payload_{int(time.time())}.bin"

def normalize_url(url: str) -> str:
    """Sanitizes URLs ensuring Dropbox links use direct download dl=1."""
    if not url:
        return ""
    cleaned = url.strip()
    if "dropbox.com" in cleaned:
        if "dl=0" in cleaned:
            cleaned = cleaned.replace("dl=0", "dl=1")
        elif "dl=1" not in cleaned:
            cleaned += "&dl=1" if "?" in cleaned else "?dl=1"
    return cleaned

def encode_bitmask(disabled_keys: List[str], exts: List[Dict[str, str]]) -> str:
    """Encodes disabled extension keys into a compact hexadecimal bitmask string."""
    if not exts:
        return "0"
    mask = 0
    disabled_set = set(disabled_keys)
    for i, ext in enumerate(exts):
        if ext["key"] not in disabled_set:
            mask |= (1 << i)
    return hex(mask)[2:]

def decode_bitmask(mask_hex: str, exts: List[Dict[str, str]]) -> Dict[str, Any]:
    """Decodes a hexadecimal bitmask string into enabled/disabled status."""
    if not exts:
        return {"disabled": [], "enabled_count": 0, "total_count": 0, "mask_hex": "0"}

    default_mask = (1 << len(exts)) - 1
    try:
        mask = int(mask_hex, 16) if (mask_hex is not None and mask_hex != "") else default_mask
    except ValueError:
        mask = default_mask

    disabled: List[str] = []
    enabled_count = 0

    for i, ext in enumerate(exts):
        if (mask & (1 << i)) != 0:
            enabled_count += 1
        else:
            disabled.append(ext["key"])

    return {
        "disabled": disabled,
        "enabled_count": enabled_count,
        "total_count": len(exts),
        "mask_hex": hex(mask)[2:],
        "is_enabled": lambda key: key not in disabled,
    }

class SpeedTracker:
    """Exponential Moving Average (EMA) speed calculator for smooth transfer rate reporting."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self.smoothed_speed: float = 0.0
        self.last_bytes: int = 0
        self.last_time: float = 0.0

    def update(self, current_bytes: int) -> float:
        now = time.time()
        if self.last_time == 0.0:
            self.last_time = now
            self.last_bytes = current_bytes
            return 0.0

        elapsed = now - self.last_time
        if elapsed <= 0.001:
            return self.smoothed_speed

        delta_bytes = current_bytes - self.last_bytes
        instant_speed = delta_bytes / elapsed

        if self.smoothed_speed == 0.0:
            self.smoothed_speed = instant_speed
        else:
            self.smoothed_speed = (self.alpha * instant_speed) + ((1.0 - self.alpha) * self.smoothed_speed)

        self.last_time = now
        self.last_bytes = current_bytes
        return self.smoothed_speed
