"""
Metric, Time, URL & Bitmask Presentation Formatting Utilities (v3.0.0)
"""

import os
import re
import time
import shutil
import zipfile
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple

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

def parse_artifact_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parses a GitHub Actions artifact URL into owner, repo, and artifact_id.
    Matches:
      - https://github.com/:owner/:repo/actions/runs/:run_id/artifacts/:artifact_id
      - https://github.com/:owner/:repo/suites/:suite_id/artifacts/:artifact_id
      - https://api.github.com/repos/:owner/:repo/actions/artifacts/:artifact_id
    """
    if not url:
        return None
    cleaned = url.strip()
    m = re.search(
        r"https?://github\.com/([^/]+)/([^/]+)/(?:actions/runs/\d+|suites/\d+)/artifacts/(\d+)",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "repo_full_name": f"{m.group(1)}/{m.group(2)}",
            "artifact_id": m.group(3),
        }
    m_api = re.search(
        r"https?://api\.github\.com/repos/([^/]+)/([^/]+)/actions/artifacts/(\d+)",
        cleaned,
        re.IGNORECASE,
    )
    if m_api:
        return {
            "owner": m_api.group(1),
            "repo": m_api.group(2),
            "repo_full_name": f"{m_api.group(1)}/{m_api.group(2)}",
            "artifact_id": m_api.group(3),
        }
    return None

def parse_run_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parses a GitHub Actions workflow run URL into owner, repo, and run_id.
    Matches:
      - https://github.com/:owner/:repo/actions/runs/:run_id
    """
    if not url:
        return None
    cleaned = url.strip()
    m = re.search(
        r"https?://github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)/?$",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "repo_full_name": f"{m.group(1)}/{m.group(2)}",
            "run_id": m.group(3),
        }
    return None

def parse_content_disposition_filename(cd_header: str) -> Optional[str]:
    """
    Extracts filename from Content-Disposition header.
    Handles RFC 5987 / 6266 (filename*=UTF-8''...) and standard filename="...".
    """
    if not cd_header:
        return None
    m_star = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^;]+)", cd_header, re.IGNORECASE)
    if m_star:
        raw = m_star.group(1).strip("\"' ")
        return sanitize_filename(urllib.parse.unquote(raw))
    m = re.search(r'filename="?([^";]+)"?', cd_header, re.IGNORECASE)
    if m:
        raw = m.group(1).strip("\"' ")
        return sanitize_filename(urllib.parse.unquote(raw))
    return None

def extract_filename_from_url(url: str, default_name: str = "downloaded_file.bin") -> str:
    """
    Extracts the filename component from a URL path, decoding percent-encoded chars.
    """
    if not url:
        return default_name
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if path:
            basename = path.split("/")[-1]
            if basename:
                unquoted = urllib.parse.unquote(basename).strip()
                if unquoted:
                    return sanitize_filename(unquoted)
    except Exception:
        pass
    return default_name

def extract_single_file_from_zip(
    zip_path: str, tmp_dir: str
) -> Optional[Tuple[str, str, int, str]]:
    """
    Inspects a ZIP archive, filters out OS metadata (__MACOSX, .DS_Store, hidden files),
    identifies the target file inside, extracts it to tmp_dir, and returns:
    (final_file_path, final_file_name, file_size, extract_dest_dir)
    Returns None if zip_path is not a valid zip or has no valid files inside.
    """
    if not os.path.exists(zip_path):
        return None
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            valid_members = [
                m for m in zf.infolist()
                if not m.is_dir()
                and not m.filename.startswith("__MACOSX")
                and not os.path.basename(m.filename).startswith(".")
            ]
            if not valid_members:
                return None

            target_member = None
            if len(valid_members) == 1:
                target_member = valid_members[0]
            else:
                # Prioritize app / package binaries (.ipa, .deb, .tipa, .apk, .dylib)
                for m in valid_members:
                    ext = os.path.splitext(m.filename)[1].lower()
                    if ext in [".ipa", ".deb", ".tipa", ".apk", ".dylib"]:
                        target_member = m
                        break
                if not target_member:
                    target_member = max(valid_members, key=lambda m: m.file_size)

            extracted_name = os.path.basename(target_member.filename)
            extract_dest_dir = os.path.join(tmp_dir, f"ext_{int(time.time())}_{os.getpid()}")
            zf.extract(target_member, path=extract_dest_dir)
            extracted_full_path = os.path.join(extract_dest_dir, target_member.filename)

            final_flat = os.path.join(tmp_dir, f"{int(time.time())}_{sanitize_filename(extracted_name)}")
            shutil.move(extracted_full_path, final_flat)
            file_size = os.path.getsize(final_flat)
            return final_flat, sanitize_filename(extracted_name), file_size, extract_dest_dir
    except (zipfile.BadZipFile, Exception):
        return None

def resolve_dropbox_destination(
    filename: str, configured_folder: str = "/IPA"
) -> Tuple[str, str, str]:
    """
    Determines Dropbox destination path, retention folder, and presentation vault display.
    Rule:
      - If .ipa file: uploads into configured folder (e.g. /IPA/app.ipa).
      - If NOT .ipa: uploads outside the folder to Dropbox root (e.g. /tweak.deb).
    Returns: (dropbox_target_path, retention_folder, vault_display)
    """
    is_ipa = filename.lower().endswith(".ipa")
    if is_ipa:
        folder = (configured_folder or "/IPA").strip().rstrip("/")
        if not folder.startswith("/"):
            folder = "/" + folder
        dest_path = f"{folder}/{filename}"
        retention_folder = folder
        vault_display = folder
    else:
        dest_path = f"/{filename}"
        retention_folder = ""  # Root is protected from retention pruning
        vault_display = "/ (Root)"
    return dest_path, retention_folder, vault_display
