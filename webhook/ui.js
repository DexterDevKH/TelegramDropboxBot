/**
 * UI Presentation Layer for Telegram Interactive Cards & Keyboards
 * Renders high-visibility Markdown cards and inline keyboards for commands and build workflows.
 */

import { BUILD_TARGETS, getExtensions, getTarget } from "./targets.js";
import { decodeBitmask } from "./state.js";

/**
 * Main App Selection Menu
 */
export function renderMainMenuText() {
  return (
    "🚀 **TRIGGER GITHUB ACTIONS BUILD**\n" +
    "──────────────────────────────\n" +
    "Choose which target repository you want to build:\n\n" +
    "• 🚀 **DTKACE Plus**: Enhanced YouTube with YTKACE & 13 extensions\n" +
    "• ✨ **DTLite Plus**: Lightweight YouTube mod with 10 extensions\n" +
    "• 🎵 **DTMusicUltimate**: DexTube Music (Lossless audio mod)\n" +
    "──────────────────────────────\n" +
    "💡 *Tap an app below to customize parameters & trigger the build.*"
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
      { text: "❌ Cancel", callback_data: "cancel" },
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
    extSection = `• 🧩 **Extensions:** \`${decoded.enabledCount}/${decoded.totalCount} active\``;
    if (decoded.disabled.length > 0) {
      const disabledNames = exts
        .filter((e) => decoded.disabled.includes(e.key))
        .map((e) => e.name);
      extSection += ` *(Disabled: ${disabledNames.join(", ")})*\n`;
    } else {
      extSection += ` *(All enabled)*\n`;
    }
  }

  const ipaDisplay = state.ipa ? `\`${state.ipa}\`` : "⚠️ *Not Configured (Required)*";
  const nameDisplay = `\`${state.name || target.defaultInputs?.display_name || "DexTube"}\``;
  const bundleDisplay = `\`${state.bundle || target.defaultInputs?.bundle_id || "com.google.ios.youtube"}\``;
  const tweakDisplay = state.tweak ? `\`${state.tweak}\`` : "`Default (Built-in)`";

  return (
    `🛠️ **BUILD PARAMETERS: ${target.name}**\n` +
    `──────────────────────────────\n` +
    `📦 **Repository:** \`${target.repo}\`\n` +
    `📄 **Workflow:** \`${target.workflow}\`\n` +
    `ℹ️ *${target.desc}*\n\n` +
    `📋 **Current Configuration:**\n` +
    `• 🔗 **IPA URL:** ${ipaDisplay}\n` +
    `• 🏷️ **App Name:** ${nameDisplay}\n` +
    `• 🆔 **Bundle ID:** ${bundleDisplay}\n` +
    (target.hasExtensions ? `• 💉 **Tweak URL:** ${tweakDisplay}\n` : "") +
    extSection +
    `──────────────────────────────\n` +
    `💡 *Press any button below to enter or change values:*`
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
        text: `🏷️ Name: ${state.name || "Default"}`,
        callback_data: `ask:name:${tk}:${mid}:${mask}`,
      },
      {
        text: `🆔 Bundle: ${state.bundle ? state.bundle.split(".").pop() : "Default"}`,
        callback_data: `ask:bundle:${tk}:${mid}:${mask}`,
      },
    ],
  ];

  if (target.hasExtensions) {
    const exts = getExtensions(tk);
    const decoded = decodeBitmask(mask, exts);
    buttons.push([
      {
        text: state.tweak ? "💉 Tweak: Custom ✅" : "💉 Set Tweak URL (Optional)",
        callback_data: `ask:tweak:${tk}:${mid}:${mask}`,
      },
      {
        text: `🧩 Extensions (${decoded.enabledCount}/${decoded.totalCount})`,
        callback_data: `ext:${tk}:${mid}:${mask}`,
      },
    ]);
  }

  buttons.push([
    {
      text: hasIpa ? "🚀 Trigger Build Now" : "🚀 Trigger Build (Set IPA First)",
      callback_data: `trig:${tk}:${mid}:${mask}`,
    },
  ]);

  buttons.push([
    { text: "◀️ Back", callback_data: "menu" },
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
      text: "🔄 Reset All",
      callback_data: `tgl_rst:${targetKey}:${dashMsgId}`,
    },
  ]);

  keyboard.push([
    {
      text: "◀️ Back",
      callback_data: `ext_done:${targetKey}:${dashMsgId}:${maskHex}`,
    },
    {
      text: `💾 Save & Back (${decoded.enabledCount}/${decoded.totalCount})`,
      callback_data: `ext_done:${targetKey}:${dashMsgId}:${maskHex}`,
    },
  ]);

  return keyboard;
}

/**
 * Build Success Presentation Card
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
  let statusBadge = "🟡 **Status:** `Queued (Waiting for macOS runner...)`";
  if (status === "in_progress") {
    statusBadge = "🟢 **Status:** `In Progress (Building on macOS runner...)`";
  }

  const card =
    `⚙️ **BUILD IN PROGRESS: ${target.name}**\n` +
    `──────────────────────────────\n` +
    `📦 **Repository:** \`${target.repo}\`\n` +
    `📄 **Workflow:** \`${target.workflow}\`\n` +
    (runId ? `🆔 **Run ID:** \`${runId}\`\n` : "") +
    `⏱️ **Elapsed Time:** \`${formatDuration(elapsedSecs)}\`\n` +
    `${statusBadge}\n` +
    `──────────────────────────────\n` +
    `⚡ *Auto-refreshing status in real-time (No action needed)...*\n` +
    `💡 *This card will automatically transform into your IPA download button once compilation finishes.*`;

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
    `🎉 **BUILD COMPLETED SUCCESSFULLY!**\n` +
    `──────────────────────────────\n` +
    `🚀 **Target:** \`${target.name}\`\n` +
    `📦 **Package:** \`${assetName}\`${assetSize}\n` +
    `🏷️ **Release Tag:** \`${tagName}\`\n` +
    `⏱️ **Build Duration:** \`${formatDuration(elapsedSecs)}\`\n` +
    `──────────────────────────────\n` +
    `✅ Your modified IPA is compiled and ready for download! Tap below to get your file.`;

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
    `❌ **BUILD FAILED**\n` +
    `──────────────────────────────\n` +
    `🚀 **Target:** \`${target.name}\`\n` +
    `📦 **Repository:** \`${target.repo}\`\n` +
    (runId ? `🆔 **Run ID:** \`${runId}\`\n` : "") +
    `⚠️ **Conclusion:** \`${conclusionDisplay}\`\n` +
    `⏱️ **Elapsed Time:** \`${formatDuration(elapsedSecs)}\`\n` +
    `──────────────────────────────\n` +
    `💡 *The build failed on the GitHub Actions runner. Tap below to inspect error logs.*`;

  const buttons = [
    [
      {
        text: "🌐 View Workflow on GitHub",
        url: runUrl || `https://github.com/${target.repo}/actions`,
      },
    ],
  ];

  return { text: card, buttons };
}

export function renderBuildSuccessCard(target, inputs, disabledKeys = []) {
  const exts = getExtensions(target.key);
  let card =
    `✅ **GITHUB ACTION TRIGGERED!**\n` +
    `──────────────────────────────\n` +
    `🚀 **Target:** \`${target.name}\`\n` +
    `📦 **Repository:** \`${target.repo}\`\n` +
    `📄 **Workflow:** \`${target.workflow}\`\n` +
    `🔗 **IPA URL:** \`${inputs.ipa_url}\`\n`;

  if (inputs.display_name) card += `🏷️ **App Name:** \`${inputs.display_name}\`\n`;
  if (inputs.bundle_id) card += `🆔 **Bundle ID:** \`${inputs.bundle_id}\`\n`;
  if (inputs.tweak_url) card += `💉 **Tweak URL:** \`${inputs.tweak_url}\`\n`;

  if (target.hasExtensions && exts.length > 0) {
    const disabledItems = exts.filter((e) => disabledKeys.includes(e.key));
    const enabledCount = exts.length - disabledItems.length;
    card +=
      `🧩 **Extensions:** \`${enabledCount}/${exts.length} active\`` +
      (disabledItems.length > 0
        ? ` *(Disabled: ${disabledItems.map((e) => e.name).join(", ")})*\n`
        : ` *(All active)*\n`);
  }

  card +=
    `──────────────────────────────\n` +
    `⚡ **Runner State:** Queued on macOS runner\n` +
    `💡 *The GitHub Actions runner will compile tweaks, inject into the IPA, and create a release.*`;

  const buttons = [
    [
      {
        text: "🌐 View Workflow on GitHub",
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
    `❌ **WORKFLOW DISPATCH FAILED**\n` +
    `──────────────────────────────\n` +
    `📦 **Repository:** \`${target.repo}\`\n` +
    `📄 **Workflow:** \`${target.workflow}\`\n` +
    `⚠️ **Status Code:** HTTP \`${result.status}\`\n` +
    `📝 **Error Details:** \`${result.error || "Unknown error"}\`\n` +
    `──────────────────────────────\n` +
    `💡 *Please verify that your GH_PAT secret has 'repo' or 'actions:write' permissions.*`
  );
}

/**
 * Status Card
 */
export function renderStatusCard(env) {
  return (
    "📊 **SYSTEM STATUS MONITOR**\n" +
    "──────────────────────────────\n" +
    "🟢 **Edge Gateway:** `Cloudflare Global Edge (Operational)`\n" +
    "🛰️ **Pipeline Mode:** `100% Serverless On-Demand`\n" +
    "⚡ **Runner State:** `Standing By (0 idle usage)`\n" +
    "📦 **Payload Limit:** `Up to 2,000 MB (2.0 GB)`\n" +
    "🚀 **Build Dispatcher:** `Active (/build)` with Stateless Bitmasks\n" +
    `🐙 **Target Repository:** \`${env.GH_REPO || "DexterDevKH/TelegramDropboxBot"}\`\n` +
    "──────────────────────────────\n" +
    "💡 *Upload any media file to automatically trigger Dropbox sync.*"
  );
}

/**
 * Help Card
 */
export function renderHelpCard() {
  return (
    "⚡ **TELEGRAM TO DROPBOX SYNC & BUILD PIPELINE**\n" +
    "──────────────────────────────\n" +
    "📥 **Quick Transfer:** Forward or upload any document, video, archive, or IPA (up to 2.0 GB).\n" +
    "🚀 **GitHub Actions Builder:** Send `/build` to select a repo, configure inputs via buttons, and trigger builds.\n\n" +
    "✨ **Available Commands:**\n" +
    "• `/build` — Select an app, toggle extensions & configure inputs\n" +
    "• `/status` — View real-time runner status & health\n" +
    "• `/ping` — Measure gateway round-trip latency\n" +
    "• `/help` — Display operational manual\n" +
    "──────────────────────────────\n" +
    "🟢 **Status:** Armed and ready."
  );
}

/**
 * Ping Card
 */
export function renderPingCard() {
  return (
    "⚡ **GATEWAY PONG**\n" +
    "──────────────────────────────\n" +
    "🟢 **Status:** Operational (100%)\n" +
    "🛰️ **Host:** Cloudflare Global Edge (~15ms)\n" +
    "⚡ **Engine:** Serverless On-Demand Runner\n" +
    "💡 *Upload any media up to 2 GB to sync, or send /build to trigger builds.*"
  );
}

/**
 * Media Transfer Initial Notice Card
 */
export function renderMediaNoticeCard(fileName, fileSizeFormatted) {
  const isZip = fileName.toLowerCase().endsWith(".zip");
  const unzipNote = isZip ? " *(Auto-unzip enabled)*" : "";

  return (
    "⚡ **TRANSFER REQUEST RECEIVED**\n" +
    "──────────────────────────────\n" +
    `📄 **Target:** \`${fileName}\`${unzipNote}\n` +
    (fileSizeFormatted ? `📦 **Filesize:** \`${fileSizeFormatted}\`\n` : "") +
    "🛰️ **Status:** *Dispatching GitHub Actions cloud runner...*\n" +
    "⏳ *MTProto ingestion & auto-unzip engine will engage shortly.*"
  );
}

/**
 * URL / GitHub Artifact Transfer Initial Notice Card
 */
export function renderUrlNoticeCard(rawUrl, fileName, fileSizeFormatted, isArtifact = false, artifactRepo = null) {
  const sourceLine = isArtifact && artifactRepo
    ? `🔗 **Source:** GitHub Actions Artifact (\`${artifactRepo}\`)\n`
    : `🔗 **Source:** Remote Web Link\n`;

  const isZip = isArtifact || fileName.toLowerCase().endsWith(".zip");
  const unzipNote = isZip ? " *(Auto-unzip enabled)*" : "";

  return (
    "⚡ **URL DOWNLOAD REQUEST RECEIVED**\n" +
    "──────────────────────────────\n" +
    sourceLine +
    `📄 **Target:** \`${fileName}\`${unzipNote}\n` +
    (fileSizeFormatted ? `📦 **Filesize:** \`${fileSizeFormatted}\`\n` : "") +
    "🛰️ **Status:** *Dispatching GitHub Actions cloud runner...*\n" +
    "⏳ *High-speed download, archive extraction & Dropbox push will engage shortly.*"
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
    "🔗 **IPA LINK DETECTED**\n" +
    "──────────────────────────────\n" +
    `URL: \`${rawUrl}\`\n\n` +
    "Choose which app you want to build with this link:"
  );

  return { text, buttons };
}

