"""
Application Constants, Build Targets & Extensions Catalog
"""

from typing import Dict, List, Any, Optional

BUILD_TARGETS: Dict[str, Dict[str, Any]] = {
    "dtkace": {
        "key": "dtkace",
        "name": "DTKACE Plus",
        "repo": "DexterDevKH/DTKACE",
        "workflow": "main_url.yml",
        "desc": "Enhanced YouTube (YTKACE engine + 13 modular tweaks)",
        "defaultInputs": {
            "display_name": "DexTube",
            "bundle_id": "com.google.ios.youtube",
        },
        "requiredLabel": "decrypted YouTube IPA URL",
        "placeholder": "Paste decrypted YouTube IPA URL...",
        "hasExtensions": True,
    },
    "dtlite": {
        "key": "dtlite",
        "name": "DTLite Plus",
        "repo": "DexterDevKH/DTLite",
        "workflow": "main_url.yml",
        "desc": "Lightweight YouTube mod (Ad-blocking, PiP, SponsorBlock)",
        "defaultInputs": {
            "display_name": "DexTube",
            "bundle_id": "com.google.ios.youtube",
        },
        "requiredLabel": "decrypted YouTube IPA URL",
        "placeholder": "Paste decrypted YouTube IPA URL...",
        "hasExtensions": True,
    },
    "dtmusic": {
        "key": "dtmusic",
        "name": "DTMusicUltimate",
        "repo": "DexterDevKH/DTMusicUltimate",
        "workflow": "main.yml",
        "desc": "DexTube Music (Lossless audio & background playback)",
        "defaultInputs": {
            "display_name": "DexTube Music",
            "bundle_id": "com.google.ios.youtubemusic",
        },
        "requiredLabel": "decrypted YouTube Music IPA URL",
        "placeholder": "Paste decrypted YouTube Music IPA URL...",
        "hasExtensions": False,
    },
}

EXTENSIONS_CONFIG: Dict[str, List[Dict[str, str]]] = {
    "dtkace": [
        {"key": "ytabc", "input": "enable_ytabc", "name": "YTABConfig"},
        {"key": "ytweaks", "input": "enable_ytweaks", "name": "YTweaks"},
        {"key": "youpip", "input": "enable_youpip", "name": "YouPiP"},
        {"key": "vbyt", "input": "enable_vbyt", "name": "VolumeBoost"},
        {"key": "demc", "input": "enable_demc", "name": "DontEatMyContent"},
        {"key": "ryd", "input": "enable_ryd", "name": "Dislikes (RYD)"},
        {"key": "ytvo", "input": "enable_ytvo", "name": "VideoOverlay"},
        {"key": "ygc", "input": "enable_ygc", "name": "YouGetCaption"},
        {"key": "yq", "input": "enable_yq", "name": "YouQuality"},
        {"key": "ycq", "input": "enable_ycq", "name": "ChooseQuality"},
        {"key": "ythfs", "input": "enable_ythfs", "name": "HoldForSpeed"},
        {"key": "ygs", "input": "enable_ygs", "name": "GroupSettings"},
        {"key": "ytuhd", "input": "enable_ytuhd", "name": "YTUHD (4K/VP9)"},
    ],
    "dtlite": [
        {"key": "youpip", "input": "enable_youpip", "name": "YouPiP"},
        {"key": "ytuhd", "input": "enable_ytuhd", "name": "YTUHD (4K/VP9)"},
        {"key": "yq", "input": "enable_yq", "name": "YouQuality"},
        {"key": "ryd", "input": "enable_ryd", "name": "Dislikes (RYD)"},
        {"key": "ytabc", "input": "enable_ytabc", "name": "YTABConfig"},
        {"key": "demc", "input": "enable_demc", "name": "DontEatMyContent"},
        {"key": "ycq", "input": "enable_ycq", "name": "ChooseQuality"},
        {"key": "vbyt", "input": "enable_vbyt", "name": "VolumeBoost"},
        {"key": "ytamp", "input": "enable_ytamp", "name": "Miniplayer"},
        {"key": "loc", "input": "enable_localization", "name": "Localization"},
    ],
}

def get_target(key: str) -> Optional[Dict[str, Any]]:
    """Returns the target config dictionary by key or None."""
    return BUILD_TARGETS.get(key.lower()) if key else None

def get_extensions(target_key: str) -> List[Dict[str, str]]:
    """Returns the extensions list for a given target."""
    return EXTENSIONS_CONFIG.get(target_key.lower(), [])

