/**
 * UI Presentation Layer for Telegram Interactive Cards & Keyboards (v3.1.0)
 * Ultra-sleek, modern tree-structured cards and inline keyboard grids for Telegram Bot API.
 */

import { BUILD_TARGETS, getExtensions, getTarget } from "./targets.js";
import { decodeBitmask } from "./state.js";

/**
 * Main App Selection Menu
 */
export function renderMainMenuText() {
  return (
    "╭─ 🚀 **GITHUB ACTIONS WORKFLOW BUILDER**\n" +
    "├──────────────────────────────\n" +
    "│ Choose a target iOS application to configure:\n" +
    "│\n" +
    "│ • 🚀 **DTKACE Plus** — Enhanced YouTube (13 modular tweaks)\n" +
    "│ • ✨ **DTLite Plus** — Lightweight YouTube (Ad-block, PiP, RYD)\n" +
    "│ • 🎵 **DTMusicUltimate** — DexTube Music (Lossless audio mod)\n" +
    "│\n" +
    "╰─ 💡 *Select an app button below to customize and build.*"
  );
}

export function renderMainMenuButtons() {
  return [
    [
      { text: "🚀 DTKACE Plus", callback_data: "sel:dtkace" },
      { text: "✨ DTLite Plus", callback_data: "sel:dtlite" },
    ],
    [
      { text: "🎵 DTMusicUltimate", callback_data: "sel:dtmusic" },
    ],
    [
      { text: "🔐 Secret Tweak", callback_data: "settweak_menu" },
      { text: "🍎 App Store Versions", callback_data: "check_versions" },
    ],
    [
      { text: "❌ Dismiss", callback_data: "cancel" },
    ],
  ];
}

/**
 * Parameters Dashboard Text
 */
export function renderDashboardText(state) {
  const target = getTarget(state.targetKey) || BUILD_TARGETS.dtkace;
  const exts = getExtensions(target.key);
  const decoded = decodeBitmask(state.maskHex, exts);

  let extSection = "";
  if (target.hasExtensions && exts.length > 0) {
    extSection = `│  • 🧩 **Extensions:**  \`${decoded.enabledCount}/${decoded.totalCount} active\``;
    if (decoded.disabled.length > 0) {
      const disabledNames = exts
        .filter((e) => decoded.disabled.includes(e.key))
        .map((e) => e.name);
      extSection += ` *(Disabled: ${disabledNames.join(", ")})*\n`;
    } else {
      extSection += ` *(All active)*\n`;
    }
  }

  const ipaDisplay = state.ipa ? `\`${state.ipa}\`` : "⚠️ *Not Configured (Required)*";
  const nameDisplay = `\`${state.name || target.defaultInputs?.display_name || "DexTube"}\``;
  const bundleDisplay = `\`${state.bundle || target.defaultInputs?.bundle_id || "com.google.ios.youtube"}\``;
  const tweakDisplay = state.tweak ? `\`${state.tweak}\`` : "`Default (Built-in)`";

  return (
    `╭─ 🛠️ **BUILD CONFIGURATION: ${target.name}**\n` +
    `├──────────────────────────────\n` +
    `│ 📦 **Repository:** \`${target.repo}\`\n` +
    `│ 📄 **Workflow:**   \`${target.workflow}\`\n` +
    `│ ℹ️ *${target.desc}*\n` +
    `│\n` +
    `├─ 📋 **Parameters**\n` +
    `│  • 🔗 **IPA URL:**     ${ipaDisplay}\n` +
    `│  • 🏷️ **App Name:**    ${nameDisplay}\n` +
    `│  • 🆔 **Bundle ID:**   ${bundleDisplay}\n` +
    (target.hasExtensions ? `│  • 💉 **Tweak URL:**   ${tweakDisplay}\n` : "") +
    extSection +
    `│\n` +
    `╰─ 💡 *Tap buttons below to modify values or trigger dispatch:*`
  );
}

/**
 * Parameters Dashboard Buttons
 */
export function renderDashboardButtons(state, dashMsgId) {
  const target = getTarget(state.targetKey) || BUILD_TARGETS.dtkace;
  const hasIpa = Boolean(state.ipa);
  const mid = dashMsgId || state.dashMsgId || 0;
  const mask = state.maskHex || "1fff";
  const tk = target.key;

  const buttons = [
    [
      {
        text: hasIpa ? "🔗 Change IPA URL ✅" : "🔗 Set IPA URL (Required) ⚠️",
        callback_data: `ask:ipa:${tk}:${mid}:${mask}`,
      },
    ],
    [
      {
        text: `🏷️ App Name`,
        callback_data: `ask:name:${tk}:${mid}:${mask}`,
      },
      {
        text: `🆔 Bundle ID`,
        callback_data: `ask:bundle:${tk}:${mid}:${mask}`,
      },
    ],
  ];

  if (target.hasExtensions) {
    const exts = getExtensions(tk);
    const decoded = decodeBitmask(mask, exts);
    buttons.push([
      {
        text: state.tweak ? "💉 Tweak: Custom ✅" : "💉 Set Tweak URL",
        callback_data: `ask:tweak:${tk}:${mid}:${mask}`,
      },
      {
        text: `🧩 Extensions (${decoded.enabledCount}/${decoded.totalCount})`,
        callback_data: `ext:${tk}:${mid}:${mask}`,
      },
    ]);
    buttons.push([
      {
        text: "🔐 Update Secret TWEAK_URL Env",
        callback_data: `ask_sec:${tk}:${mid}:${mask}`,
      },
    ]);
  }

  if (hasIpa) {
    buttons.push([
      {
        text: "🚀 TRIGGER GITHUB ACTIONS BUILD",
        callback_data: `trig:${tk}:${mid}:${mask}`,
      },
    ]);
  }

  buttons.push([
    { text: "◀️ Change App", callback_data: "menu" },
    { text: "❌ Cancel", callback_data: "cancel" },
  ]);

  return buttons;
}

/**
 * Extensions Interactive Toggle Keyboard (2-column layout)
 */
export function renderExtensionsKeyboard(targetKey, dashMsgId, maskHex) {
  const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;
  const exts = getExtensions(targetKey);
  const decoded = decodeBitmask(maskHex, exts);
  const keyboard = [];

  for (let i = 0; i < exts.length; i += 2) {
    const row = [];
    const ext1 = exts[i];
    const isEnabled1 = decoded.isEnabled(ext1.key);
    row.push({
      text: `${isEnabled1 ? "✅" : "❌"} ${ext1.name}`,
      callback_data: `tgl:${targetKey}:${dashMsgId}:${i}:${maskHex}`,
    });

    if (i + 1 < exts.length) {
      const ext2 = exts[i + 1];
      const isEnabled2 = decoded.isEnabled(ext2.key);
      row.push({
        text: `${isEnabled2 ? "✅" : "❌"} ${ext2.name}`,
        callback_data: `tgl:${targetKey}:${dashMsgId}:${i + 1}:${maskHex}`,
      });
    }
    keyboard.push(row);
  }

  const allDisabled = decoded.enabledCount === 0;
  keyboard.push([
    {
      text: allDisabled ? "⚡ Enable All" : "⚡ Disable All",
      callback_data: `tgl_all:${targetKey}:${dashMsgId}:${maskHex}`,
    },
    {
      text: "🔄 Reset Defaults",
      callback_data: `tgl_rst:${targetKey}:${dashMsgId}`,
    },
  ]);

  keyboard.push([
    {
      text: `💾 Save & Return (${decoded.enabledCount}/${decoded.totalCount})`,
      callback_data: `ext_done:${targetKey}:${dashMsgId}:${maskHex}`,
    },
  ]);

  return keyboard;
}

/**
 * Duration formatter
 */
export function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return "0s";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

/**
 * Live Workflow Tracking Card
 */
export function renderBuildTrackingCard(target, runId, status, elapsedSecs, runUrl) {
  let statusBadge = "Queued on macOS runner";
  if (status === "in_progress") {
    statusBadge = "Compiling on macOS runner";
  }

  const card =
    `╭─ ⚙️ **BUILD IN PROGRESS: ${target.name}**\n` +
    `├──────────────────────────────\n` +
    `│ 📦 **Repository:** \`${target.repo}\`\n` +
    `│ 📄 **Workflow:**   \`${target.workflow}\`\n` +
    (runId ? `│ 🆔 **Run ID:**     \`${runId}\`\n` : "") +
    `│ ⏱️ **Elapsed:**    \`${formatDuration(elapsedSecs)}\`\n` +
    `│ ⚡ **Status:**     \`${statusBadge}\`\n` +
    `│\n` +
    `╰─ ☕ *Compilation executing on cloud runner. Card auto-updates.*`;

  const buttons = [
    [
      {
        text: "🌐 View Live Logs on GitHub",
        url: runUrl || `https://github.com/${target.repo}/actions`,
      },
    ],
  ];

  return { text: card, buttons };
}

/**
 * Build Completed Successfully Card (with direct download button)
 */
export function renderBuildCompletedCard(target, release, ipaAsset, elapsedSecs, runUrl) {
  const assetName = ipaAsset?.name || `${target.name}.ipa`;
  const assetSize = ipaAsset?.size ? ` (${(ipaAsset.size / (1024 * 1024)).toFixed(1)} MB)` : "";
  const tagName = release?.tagName || "Latest";
  const downloadUrl = ipaAsset?.downloadUrl || release?.htmlUrl || `https://github.com/${target.repo}/releases`;

  const card =
    `╭─ 🎉 **BUILD COMPLETED SUCCESSFULLY!**\n` +
    `├──────────────────────────────\n` +
    `│ 🚀 **Target:**   \`${target.name}\`\n` +
    `│ 📦 **Package:**  \`${assetName}\`${assetSize}\n` +
    `│ 🏷️ **Tag:**      \`${tagName}\`\n` +
    `│ ⏱️ **Duration:** \`${formatDuration(elapsedSecs)}\`\n` +
    `│\n` +
    `╰─ ✅ *Modified IPA is compiled and ready for download:*`;

  const buttons = [
    [
      {
        text: "📥 Download IPA",
        url: downloadUrl,
      },
    ],
    [
      {
        text: "🌐 Open GitHub Release",
        url: release?.htmlUrl || `https://github.com/${target.repo}/releases`,
      },
    ],
  ];

  return { text: card, buttons, downloadUrl };
}

/**
 * Build Failed Card (with button to view error logs)
 */
export function renderBuildFailedCard(target, runId, conclusion, elapsedSecs, runUrl) {
  const conclusionDisplay = (conclusion || "FAILED").toUpperCase();
  const card =
    `╭─ ❌ **BUILD FAILED**\n` +
    `├──────────────────────────────\n` +
    `│ 🚀 **Target:**     \`${target.name}\`\n` +
    `│ 📦 **Repository:** \`${target.repo}\`\n` +
    (runId ? `│ 🆔 **Run ID:**     \`${runId}\`\n` : "") +
    `│ ⚠️ **Conclusion:** \`${conclusionDisplay}\`\n` +
    `│ ⏱️ **Elapsed:**    \`${formatDuration(elapsedSecs)}\`\n` +
    `│\n` +
    `╰─ 💡 *Compilation failed on the runner. Tap below to inspect logs.*`;

  const buttons = [
    [
      {
        text: "🌐 View Workflow Logs on GitHub",
        url: runUrl || `https://github.com/${target.repo}/actions`,
      },
    ],
  ];

  return { text: card, buttons };
}

export function renderBuildSuccessCard(target, inputs, disabledKeys = []) {
  const exts = getExtensions(target.key);
  let card =
    `╭─ 🚀 **GITHUB ACTION TRIGGERED!**\n` +
    `├──────────────────────────────\n` +
    `│ 🚀 **Target:**     \`${target.name}\`\n` +
    `│ 📦 **Repository:** \`${target.repo}\`\n` +
    `│ 📄 **Workflow:**   \`${target.workflow}\`\n` +
    `│ 🔗 **IPA URL:**    \`${inputs.ipa_url}\`\n`;

  if (inputs.display_name) card += `│ 🏷️ **App Name:**   \`${inputs.display_name}\`\n`;
  if (inputs.bundle_id) card += `│ 🆔 **Bundle ID:**  \`${inputs.bundle_id}\`\n`;
  if (inputs.tweak_url) card += `│ 💉 **Tweak URL:**  \`${inputs.tweak_url}\`\n`;

  if (target.hasExtensions && exts.length > 0) {
    const disabledItems = exts.filter((e) => disabledKeys.includes(e.key));
    const enabledCount = exts.length - disabledItems.length;
    card +=
      `│ 🧩 **Extensions:** \`${enabledCount}/${exts.length} active\`` +
      (disabledItems.length > 0
        ? ` *(Disabled: ${disabledItems.map((e) => e.name).join(", ")})*\n`
        : ` *(All active)*\n`);
  }

  card +=
    `│\n` +
    `╰─ ⚡ *Dispatched to macOS runner. Tracking progress in real-time...*`;

  const buttons = [
    [
      {
        text: "🌐 View Live Logs on GitHub",
        url: `https://github.com/${target.repo}/actions`,
      },
    ],
  ];

  return { text: card, buttons };
}

/**
 * Build Failure Card
 */
export function renderBuildFailureCard(target, result) {
  return (
    `╭─ ❌ **WORKFLOW DISPATCH FAILED**\n` +
    `├──────────────────────────────\n` +
    `│ 📦 **Repository:** \`${target.repo}\`\n` +
    `│ 📄 **Workflow:**   \`${target.workflow}\`\n` +
    `│ ⚠️ **Status Code:** HTTP \`${result.status}\`\n` +
    `│ 📝 **Details:**     \`${result.error || "Unknown error"}\`\n` +
    `│\n` +
    `╰─ 💡 *Verify that your GH_PAT secret has 'repo' or 'actions:write' permissions.*`
  );
}

/**
 * Status Card
 */
export function renderStatusCard(env) {
  return (
    "╭─ 📊 **SYSTEM STATUS MONITOR**\n" +
    "├──────────────────────────────\n" +
    "│ 🟢 **Edge Gateway:**   `Cloudflare Global Edge (Operational)`\n" +
    "│ 🛰️ **Pipeline Mode:**  `100% Serverless On-Demand`\n" +
    "│ ⚡ **Runner State:**   `Standing By (0 idle usage)`\n" +
    "│ 📦 **Payload Limit:**  `Up to 2,000 MB (2.0 GB)`\n" +
    "│ 🍎 **iOS Monitor:**    `Active (YouTube & YouTube Music)`\n" +
    "│ 🚀 **Build Engine:**   `Active (/build)` with Stateless Bitmasks\n" +
    `│ 🐙 **Target Repo:**    \`${env.GH_REPO || "DexterDevKH/TelegramDropboxBot"}\`\n` +
    "│\n" +
    "╰─ 💡 *Upload any media file or link to trigger cloud sync.*"
  );
}

/**
 * Help Card
 */
export function renderHelpCard() {
  return (
    "╭─ ⚡ **TELEGRAM TO DROPBOX PIPELINE**\n" +
    "├──────────────────────────────\n" +
    "│ 📥 **Quick Transfer:** Forward any file or paste direct URLs (up to 2 GB).\n" +
    "│ 🚀 **GitHub Builder:** Send `/build` to configure parameters & trigger builds.\n" +
    "│\n" +
    "├─ 🕹️ **Commands Manual**\n" +
    "│ • `/build` — Configure inputs, toggle extensions & dispatch build\n" +
    "│ • `/settweak` — Update secret TWEAK_URL env for DTKACE and DTLite\n" +
    "│ • `/checkversion` — Check official App Store iOS releases\n" +
    "│ • `/status` — View real-time runner status & health metrics\n" +
    "│ • `/ping` — Measure gateway round-trip edge latency\n" +
    "│ • `/help` — Display this operational manual\n" +
    "│\n" +
    "╰─ 🟢 **Status:** Armed and ready for transmission."
  );
}

/**
 * Ping Card
 */
export function renderPingCard() {
  return (
    "╭─ ⚡ **GATEWAY PONG**\n" +
    "├──────────────────────────────\n" +
    "│ 🟢 **Status:**  `Operational (100%)`\n" +
    "│ 🛰️ **Host:**    `Cloudflare Global Edge (~15ms)`\n" +
    "│ ⚡ **Engine:**  `Serverless On-Demand Runner`\n" +
    "│\n" +
    "╰─ 💡 *Drop any media or URL to sync, or send /build to trigger builds.*"
  );
}

/**
 * Media Transfer Initial Notice Card
 */
export function renderMediaNoticeCard(fileName, fileSizeFormatted) {
  const isZip = fileName.toLowerCase().endsWith(".zip");
  const unzipNote = isZip ? " *(Auto-unzip enabled)*" : "";

  return (
    "╭─ ⚡ **TRANSFER REQUEST RECEIVED**\n" +
    "├──────────────────────────────\n" +
    `│ 📄 **Target:**   \`${fileName}\`${unzipNote}\n` +
    (fileSizeFormatted ? `│ 📦 **Filesize:** \`${fileSizeFormatted}\`\n` : "") +
    "│ 🛰️ **Status:**   `Dispatching GitHub Actions runner...`\n" +
    "│\n" +
    "╰─ ⏳ *High-speed cloud ingestion & Dropbox push will engage shortly.*"
  );
}

/**
 * URL / GitHub Artifact Transfer Initial Notice Card
 */
export function renderUrlNoticeCard(rawUrl, fileName, fileSizeFormatted, isArtifact = false, artifactRepo = null) {
  const sourceLine = isArtifact && artifactRepo
    ? `│ 🔗 **Source:**   GitHub Actions Artifact (\`${artifactRepo}\`)\n`
    : `│ 🔗 **Source:**   Remote Web Link\n`;

  const isZip = isArtifact || fileName.toLowerCase().endsWith(".zip");
  const unzipNote = isZip ? " *(Auto-unzip enabled)*" : "";

  return (
    "╭─ ⚡ **URL DOWNLOAD REQUEST RECEIVED**\n" +
    "├──────────────────────────────\n" +
    sourceLine +
    `│ 📄 **Target:**   \`${fileName}\`${unzipNote}\n` +
    (fileSizeFormatted ? `│ 📦 **Filesize:** \`${fileSizeFormatted}\`\n` : "") +
    "│ 🛰️ **Status:**   `Dispatching GitHub Actions runner...`\n" +
    "│\n" +
    "╰─ ⏳ *Download, archive extraction & Dropbox push will engage shortly.*"
  );
}

/**
 * Bare IPA URL Detected Card
 */
export function renderUrlDetectedCard(rawUrl) {
  const buttons = [
    [
      { text: "🚀 Build DTKACE Plus", callback_data: `url_build:dtkace` },
      { text: "✨ Build DTLite Plus", callback_data: `url_build:dtlite` },
    ],
    [
      { text: "🎵 Build DTMusicUltimate", callback_data: `url_build:dtmusic` },
    ],
    [
      { text: "❌ Dismiss", callback_data: "cancel" },
    ],
  ];

  const text = (
    "╭─ 🔗 **IPA LINK DETECTED**\n" +
    "├──────────────────────────────\n" +
    `│ URL: \`${rawUrl}\`\n` +
    "│\n" +
    "╰─ 💡 *Choose which iOS app to build with this link:*"
  );

  return { text, buttons };
}

/**
 * Secret Tweak Environment Menu
 */
export function renderSecretTweakMenuText() {
  return (
    "╭─ 🔐 **CONFIGURE SECRET TWEAK ENV (TWEAK_URL)**\n" +
    "├──────────────────────────────\n" +
    "│ Select a target repository to update its GitHub Actions `TWEAK_URL` secret:\n" +
    "│\n" +
    "│ • 🚀 **DTKACE Plus** (`DexterDevKH/DTKACE`)\n" +
    "│ • ✨ **DTLite Plus** (`DexterDevKH/DTLite`)\n" +
    "│ • 🔄 **Both Repositories**\n" +
    "│\n" +
    "╰─ 🛡️ *Encrypted end-to-end via Libsodium SealedBox (X25519).*"
  );
}

export function renderSecretTweakMenuButtons() {
  return [
    [
      { text: "🚀 DTKACE Plus", callback_data: "settweak_sel:dtkace" },
      { text: "✨ DTLite Plus", callback_data: "settweak_sel:dtlite" },
    ],
    [
      { text: "🔄 Update Both (DTKACE + DTLite)", callback_data: "settweak_sel:both" },
    ],
    [
      { text: "❌ Dismiss", callback_data: "cancel" },
    ],
  ];
}

/**
 * Secret Tweak Updated Success Card
 */
export function renderSecretTweakSuccessCard(repoLabel, tweakUrl) {
  return (
    "╭─ ✅ **SECRET TWEAK ENV UPDATED!**\n" +
    "├──────────────────────────────\n" +
    "│ 🔐 **Secret Name:** `TWEAK_URL`\n" +
    `│ 📦 **Repository:**  \`${repoLabel}\`\n` +
    `│ 🔗 **Tweak URL:**   \`${tweakUrl}\`\n` +
    "│ 🛡️ **Security:**    Libsodium SealedBox (X25519)\n" +
    "│\n" +
    "╰─ 💡 *Future compilation runs will automatically use this secret!*"
  );
}

/**
 * Secret Tweak Update Failure Card
 */
export function renderSecretTweakFailureCard(repoLabel, errorMsg) {
  return (
    "╭─ ❌ **FAILED TO UPDATE SECRET ENV**\n" +
    "├──────────────────────────────\n" +
    `│ 📦 **Repository:** \`${repoLabel}\`\n` +
    `│ ⚠️ **Details:**    \`${errorMsg}\`\n` +
    "│\n" +
    "╰─ 💡 *Verify that GH_PAT has 'repo' or 'secrets:write' permissions.*"
  );
}
