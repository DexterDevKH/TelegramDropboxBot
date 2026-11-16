//! Application Constants, Build Targets & Extensions Catalog

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DefaultInputs {
    pub display_name: String,
    pub bundle_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BuildTarget {
    pub key: &'static str,
    pub name: &'static str,
    pub repo: &'static str,
    pub workflow: &'static str,
    pub desc: &'static str,
    pub default_inputs: DefaultInputs,
    pub required_label: &'static str,
    pub placeholder: &'static str,
    pub has_extensions: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtensionConfig {
    pub key: &'static str,
    pub input: &'static str,
    pub name: &'static str,
}

pub static TARGET_DTKACE: BuildTarget = BuildTarget {
    key: "dtkace",
    name: "DTKACE Plus",
    repo: "DexterDevKH/DTKACE",
    workflow: "main_url.yml",
    desc: "Enhanced YouTube (YTKACE engine + 13 modular tweaks)",
    default_inputs: DefaultInputs {
        display_name: String::new(),
        bundle_id: String::new(),
    },
    required_label: "decrypted YouTube IPA URL",
    placeholder: "Paste decrypted YouTube IPA URL...",
    has_extensions: true,
};

pub static TARGET_DTLITE: BuildTarget = BuildTarget {
    key: "dtlite",
    name: "DTLite Plus",
    repo: "DexterDevKH/DTLite",
    workflow: "main_url.yml",
    desc: "Lightweight YouTube mod (Ad-blocking, PiP, SponsorBlock)",
    default_inputs: DefaultInputs {
        display_name: String::new(),
        bundle_id: String::new(),
    },
    required_label: "decrypted YouTube IPA URL",
    placeholder: "Paste decrypted YouTube IPA URL...",
    has_extensions: true,
};

pub static TARGET_DTMUSIC: BuildTarget = BuildTarget {
    key: "dtmusic",
    name: "DTMusicUltimate",
    repo: "DexterDevKH/DTMusicUltimate",
    workflow: "main.yml",
    desc: "DexTube Music (Lossless audio & background playback)",
    default_inputs: DefaultInputs {
        display_name: String::new(),
        bundle_id: String::new(),
    },
    required_label: "decrypted YouTube Music IPA URL",
    placeholder: "Paste decrypted YouTube Music IPA URL...",
    has_extensions: false,
};

pub static BUILD_TARGETS: &[&BuildTarget] = &[&TARGET_DTKACE, &TARGET_DTLITE, &TARGET_DTMUSIC];

pub static DTKACE_EXTENSIONS: &[ExtensionConfig] = &[
    ExtensionConfig { key: "ytabc", input: "enable_ytabc", name: "YTABConfig" },
    ExtensionConfig { key: "ytweaks", input: "enable_ytweaks", name: "YTweaks" },
    ExtensionConfig { key: "youpip", input: "enable_youpip", name: "YouPiP" },
    ExtensionConfig { key: "vbyt", input: "enable_vbyt", name: "VolumeBoost" },
    ExtensionConfig { key: "demc", input: "enable_demc", name: "DontEatMyContent" },
    ExtensionConfig { key: "ryd", input: "enable_ryd", name: "Dislikes (RYD)" },
    ExtensionConfig { key: "ytvo", input: "enable_ytvo", name: "VideoOverlay" },
    ExtensionConfig { key: "ygc", input: "enable_ygc", name: "YouGetCaption" },
    ExtensionConfig { key: "yq", input: "enable_yq", name: "YouQuality" },
    ExtensionConfig { key: "ycq", input: "enable_ycq", name: "ChooseQuality" },
    ExtensionConfig { key: "ythfs", input: "enable_ythfs", name: "HoldForSpeed" },
    ExtensionConfig { key: "ygs", input: "enable_ygs", name: "GroupSettings" },
    ExtensionConfig { key: "ytuhd", input: "enable_ytuhd", name: "YTUHD (4K/VP9)" },
];

pub static DTLITE_EXTENSIONS: &[ExtensionConfig] = &[
    ExtensionConfig { key: "youpip", input: "enable_youpip", name: "YouPiP" },
    ExtensionConfig { key: "ytuhd", input: "enable_ytuhd", name: "YTUHD (4K/VP9)" },
    ExtensionConfig { key: "yq", input: "enable_yq", name: "YouQuality" },
    ExtensionConfig { key: "ryd", input: "enable_ryd", name: "Dislikes (RYD)" },
    ExtensionConfig { key: "ytabc", input: "enable_ytabc", name: "YTABConfig" },
    ExtensionConfig { key: "demc", input: "enable_demc", name: "DontEatMyContent" },
    ExtensionConfig { key: "ycq", input: "enable_ycq", name: "ChooseQuality" },
    ExtensionConfig { key: "vbyt", input: "enable_vbyt", name: "VolumeBoost" },
    ExtensionConfig { key: "ytamp", input: "enable_ytamp", name: "Miniplayer" },
    ExtensionConfig { key: "loc", input: "enable_localization", name: "Localization" },
];

pub fn get_target(key: &str) -> Option<&'static BuildTarget> {
    match key.to_lowercase().as_str() {
        "dtkace" => Some(&TARGET_DTKACE),
        "dtlite" => Some(&TARGET_DTLITE),
        "dtmusic" => Some(&TARGET_DTMUSIC),
        _ => None,
    }
}

pub fn get_extensions(target_key: &str) -> &'static [ExtensionConfig] {
    match target_key.to_lowercase().as_str() {
        "dtkace" => DTKACE_EXTENSIONS,
        "dtlite" => DTLITE_EXTENSIONS,
        _ => &[],
    }
}

pub fn get_default_display_name(target_key: &str) -> &'static str {
    match target_key.to_lowercase().as_str() {
        "dtmusic" => "DexTube Music",
        _ => "DexTube",
    }
}

pub fn get_default_bundle_id(target_key: &str) -> &'static str {
    match target_key.to_lowercase().as_str() {
        "dtmusic" => "com.google.ios.youtubemusic",
        _ => "com.google.ios.youtube",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_target() {
        assert!(get_target("dtkace").is_some());
        assert!(get_target("DTLITE").is_some());
        assert!(get_target("dtmusic").is_some());
        assert!(get_target("unknown").is_none());
    }

    #[test]
    fn test_get_extensions() {
        assert_eq!(get_extensions("dtkace").len(), 13);
        assert_eq!(get_extensions("dtlite").len(), 10);
        assert_eq!(get_extensions("dtmusic").len(), 0);
    }
}
