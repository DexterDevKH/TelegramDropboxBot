/**
 * Build Targets & Modular Extensions Catalog (v3.0.0)
 * Configures repositories, workflows, default inputs, and tweak extensions.
 */

export const BUILD_TARGETS = {
  dtkace: {
    key: "dtkace",
    name: "DTKACE Plus",
    repo: "DexterDevKH/DTKACE",
    workflow: "main_url.yml",
    desc: "Enhanced YouTube (YTKACE engine + 13 modular tweaks)",
    defaultInputs: {
      display_name: "DexTube",
      bundle_id: "com.google.ios.youtube",
    },
    requiredLabel: "decrypted YouTube IPA URL",
    placeholder: "Paste decrypted YouTube IPA URL...",
    hasExtensions: true,
  },
  dtlite: {
    key: "dtlite",
    name: "DTLite Plus",
    repo: "DexterDevKH/DTLite",
    workflow: "main_url.yml",
    desc: "Lightweight YouTube mod (Ad-blocking, PiP, SponsorBlock)",
    defaultInputs: {
      display_name: "DexTube",
      bundle_id: "com.google.ios.youtube",
    },
    requiredLabel: "decrypted YouTube IPA URL",
    placeholder: "Paste decrypted YouTube IPA URL...",
    hasExtensions: true,
  },
  dtmusic: {
    key: "dtmusic",
    name: "DTMusicUltimate",
    repo: "DexterDevKH/DTMusicUltimate",
    workflow: "main.yml",
    desc: "DexTube Music (Lossless audio & background playback)",
    defaultInputs: {
      display_name: "DexTube Music",
      bundle_id: "com.google.ios.youtubemusic",
    },
    requiredLabel: "decrypted YouTube Music IPA URL",
    placeholder: "Paste decrypted YouTube Music IPA URL...",
    hasExtensions: false,
  },
};

export const EXTENSIONS_CONFIG = {
  dtkace: [
    { key: "ytabc", input: "enable_ytabc", name: "YTABConfig" },
    { key: "ytweaks", input: "enable_ytweaks", name: "YTweaks" },
    { key: "youpip", input: "enable_youpip", name: "YouPiP" },
    { key: "vbyt", input: "enable_vbyt", name: "VolumeBoost" },
    { key: "demc", input: "enable_demc", name: "DontEatMyContent" },
    { key: "ryd", input: "enable_ryd", name: "Dislikes (RYD)" },
    { key: "ytvo", input: "enable_ytvo", name: "VideoOverlay" },
    { key: "ygc", input: "enable_ygc", name: "YouGetCaption" },
    { key: "yq", input: "enable_yq", name: "YouQuality" },
    { key: "ycq", input: "enable_ycq", name: "ChooseQuality" },
    { key: "ythfs", input: "enable_ythfs", name: "HoldForSpeed" },
    { key: "ygs", "input": "enable_ygs", name: "GroupSettings" },
    { key: "ytuhd", input: "enable_ytuhd", name: "YTUHD (4K/VP9)" },
  ],
  dtlite: [
    { key: "youpip", input: "enable_youpip", name: "YouPiP" },
    { key: "ytuhd", input: "enable_ytuhd", name: "YTUHD (4K/VP9)" },
    { key: "yq", input: "enable_yq", name: "YouQuality" },
    { key: "ryd", input: "enable_ryd", name: "Dislikes (RYD)" },
    { key: "ytabc", input: "enable_ytabc", name: "YTABConfig" },
    { key: "demc", input: "enable_demc", name: "DontEatMyContent" },
    { key: "ycq", input: "enable_ycq", name: "ChooseQuality" },
    { key: "vbyt", input: "enable_vbyt", name: "VolumeBoost" },
    { key: "ytamp", input: "enable_ytamp", name: "Miniplayer" },
    { key: "loc", input: "enable_localization", name: "Localization" },
  ],
};

export function getTarget(key) {
  if (!key) return null;
  return BUILD_TARGETS[key.toLowerCase()] || null;
}

export function getExtensions(targetKey) {
  if (!targetKey) return [];
  return EXTENSIONS_CONFIG[targetKey.toLowerCase()] || [];
}
