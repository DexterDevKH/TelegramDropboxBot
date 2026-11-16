/**
 * iOS App Store Version Monitor & Alert Service (Cloudflare Worker Edge)
 * Automatically tracks official App Store releases for YouTube and YouTube Music.
 */

import { sendMessage } from "../telegram.js";

export const IOS_TRACKED_APPS = [
  {
    key: "youtube",
    name: "YouTube",
    bundleId: "com.google.ios.youtube",
    appStoreId: "544007664",
    targetKeys: ["dtkace", "dtlite"],
    icon: "📺",
  },
  {
    key: "youtubemusic",
    name: "YouTube Music",
    bundleId: "com.google.ios.youtubemusic",
    appStoreId: "1012933549",
    targetKeys: ["dtmusic"],
    icon: "🎵",
  },
];

let inMemoryVersionCache = {};
let lastCheckTimestamp = 0;

/**
 * Fetches iOS app metadata directly from official Apple iTunes Lookup API.
 */
export async function fetchIosAppInfo(bundleId) {
  try {
    const url = `https://itunes.apple.com/lookup?bundleId=${encodeURIComponent(bundleId.trim())}&t=${Date.now()}`;
    const res = await fetch(url, {
      headers: {
        "User-Agent": "TelegramDropboxBot/3.0.0 (Cloudflare Edge Version Monitor)",
      },
    });

    if (res.ok) {
      const data = await res.json();
      const results = data?.results;
      if (Array.isArray(results) && results.length > 0) {
        const r = results[0];
        const releaseDateRaw = r.currentVersionReleaseDate || "";
        const releaseDate = releaseDateRaw.includes("T") ? releaseDateRaw.split("T")[0] : releaseDateRaw;

        return {
          trackName: r.trackName || "",
          bundleId: r.bundleId || bundleId,
          version: r.version || "",
          releaseDate,
          releaseDateFull: releaseDateRaw,
          releaseNotes: r.releaseNotes || "Bug fixes and performance improvements.",
          trackViewUrl: r.trackViewUrl || "",
          artworkUrl: r.artworkUrl100 || "",
          minOs: r.minimumOsVersion || "",
        };
      }
    }
  } catch (err) {
    console.error(`[iOS Version Fetch Error for ${bundleId}]:`, err);
  }
  return null;
}

/**
 * Retrieves recorded versions from Cloudflare KV, Cache API, or Memory.
 */
export async function getStoredVersions(env) {
  if (env && env.SESSION_KV) {
    try {
      const val = await env.SESSION_KV.get("ios_version_cache");
      if (val) return JSON.parse(val);
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      const cacheKey = new Request("https://tg.internal/ios_version_cache");
      const res = await caches.default.match(cacheKey);
      if (res) return await res.json();
    }
  } catch (_) {}

  return inMemoryVersionCache;
}

/**
 * Persists recorded versions across Cloudflare KV, Cache API, and Memory.
 */
export async function saveStoredVersions(env, data) {
  inMemoryVersionCache = data;

  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.put("ios_version_cache", JSON.stringify(data));
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      const cacheKey = new Request("https://tg.internal/ios_version_cache");
      await caches.default.put(
        cacheKey,
        new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json", "Cache-Control": "max-age=86400" },
        })
      );
    }
  } catch (_) {}
}

/**
 * Renders status overview card for all tracked iOS apps.
 */
export function renderVersionStatusCard(appsData) {
  let card =
    "╭─ 🍎 **IOS APP STORE VERSION MONITOR**\n" +
    "├──────────────────────────────\n";

  for (let i = 0; i < appsData.length; i++) {
    const app = appsData[i];
    const targetsStr = (app.targetKeys || []).map((k) => `\`${k.toUpperCase()}\``).join(", ");
    card +=
      `│ ${app.icon || "📱"} **${app.trackName || app.appName}**\n` +
      `│  • 🆔 **Bundle ID:** \`${app.bundleId}\`\n` +
      `│  • 🏷️ **Version:**   \`${app.version}\`\n` +
      `│  • 📅 **Released:**  \`${app.releaseDate || "Recent"}\`\n` +
      `│  • 🛠️ **Targets:**   ${targetsStr}\n`;
    if (i + 1 < appsData.length) {
      card += "│\n";
    }
  }

  card +=
    "│\n" +
    "╰─ ⚡ *24/7 monitor active. Instant alerts dispatched upon App Store updates.*";

  const buttons = [
    [
      { text: "🚀 Build DTKACE Plus", callback_data: "url_build:dtkace" },
      { text: "✨ Build DTLite Plus", callback_data: "url_build:dtlite" },
    ],
    [
      { text: "🎵 Build DTMusicUltimate", callback_data: "url_build:dtmusic" },
      { text: "🔄 Refresh Versions", callback_data: "check_versions" },
    ],
  ];

  return { text: card, buttons };
}

/**
 * Renders alert card for a newly released iOS app version.
 */
export function renderVersionAlertCard(appInfo, prevVersion) {
  const prevStr = prevVersion ? `\`${prevVersion}\`` : "`Initial Detection`";
  let notes = (appInfo.releaseNotes || "Bug fixes and improvements.").trim();
  if (notes.length > 300) {
    notes = notes.slice(0, 297) + "...";
  }

  const card =
    "╭─ 🍎 **NEW IOS RELEASE DETECTED!**\n" +
    "├──────────────────────────────\n" +
    `│ ${appInfo.icon || "📱"} **Application:** ${appInfo.trackName || appInfo.appName || "iOS App"}\n` +
    `│ 🆔 **Bundle ID:**   \`${appInfo.bundleId}\`\n` +
    `│ 🆕 **New Version:** \`${appInfo.version}\`\n` +
    `│ ⏮️ **Previous:**    ${prevStr}\n` +
    `│ 📅 **Release Date:** \`${appInfo.releaseDate || "Recent"}\`\n` +
    "│\n" +
    "├─ 📝 **Release Notes**\n" +
    `│ ${notes.replace(/\n/g, "\n│ ")}\n` +
    "│\n" +
    "╰─ 💡 *Official release detected. Tap below to trigger an updated build.*";

  const storeUrl = appInfo.trackViewUrl || "https://apps.apple.com";
  let buttons;

  if (appInfo.bundleId === "com.google.ios.youtubemusic") {
    buttons = [
      [{ text: "🎵 Build DTMusicUltimate", callback_data: "url_build:dtmusic" }],
      [{ text: "🌐 View in App Store", url: storeUrl }],
    ];
  } else {
    buttons = [
      [
        { text: "🚀 Build DTKACE Plus", callback_data: "url_build:dtkace" },
        { text: "✨ Build DTLite Plus", callback_data: "url_build:dtlite" },
      ],
      [{ text: "🌐 View in App Store", url: storeUrl }],
    ];
  }

  return { text: card, buttons };
}

/**
 * Background auto-check runner (invoked from Cloudflare Worker scheduled event or command).
 * Throttled to 15-minute intervals unless forceCheck is true.
 */
export async function checkIosAppVersions(env, forceCheck = false) {
  const now = Date.now();
  if (!forceCheck && now - lastCheckTimestamp < 15 * 60 * 1000) {
    return { apps: [], alerts: [] };
  }
  lastCheckTimestamp = now;

  const stored = await getStoredVersions(env);
  const apps = [];
  const alerts = [];
  let updated = false;

  for (const app of IOS_TRACKED_APPS) {
    const info = await fetchIosAppInfo(app.bundleId);
    if (!info) continue;

    info.key = app.key;
    info.appName = app.name;
    info.icon = app.icon;
    info.targetKeys = app.targetKeys;
    apps.push(info);

    const prev = stored[app.bundleId];
    const prevVersion = prev?.version;

    if (!prevVersion) {
      stored[app.bundleId] = {
        version: info.version,
        releaseDate: info.releaseDate,
        trackName: info.trackName,
      };
      updated = true;
    } else if (prevVersion !== info.version) {
      alerts.push({ appInfo: info, prevVersion });
      stored[app.bundleId] = {
        version: info.version,
        releaseDate: info.releaseDate,
        trackName: info.trackName,
      };
      updated = true;
    }
  }

  if (updated) {
    await saveStoredVersions(env, stored);
  }

  // If new versions detected, alert all authorized users
  if (alerts.length > 0 && env.TELEGRAM_BOT_TOKEN) {
    const recipients = [];
    if (env.AUTHORIZED_USER_IDS) {
      for (const id of env.AUTHORIZED_USER_IDS.split(",")) {
        const cleanId = id.trim();
        if (cleanId && !recipients.includes(cleanId)) recipients.push(cleanId);
      }
    }
    if (env.TARGET_CHAT_ID && !recipients.includes(String(env.TARGET_CHAT_ID))) {
      recipients.push(String(env.TARGET_CHAT_ID));
    }

    for (const { appInfo, prevVersion } of alerts) {
      const alertCard = renderVersionAlertCard(appInfo, prevVersion);
      for (const chatId of recipients) {
        try {
          await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, alertCard.text, {
            reply_markup: { inline_keyboard: alertCard.buttons },
          });
        } catch (err) {
          console.error(`[Version Alert Delivery Error to ${chatId}]:`, err);
        }
      }
    }
  }

  return { apps, alerts };
}
