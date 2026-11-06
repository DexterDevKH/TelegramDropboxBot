/**
 * Stateless Bitmask Engine & Session Store (v3.0.0)
 * Eliminates brittle regex scraping by providing deterministic bitmask toggles
 * and zero-width embedded metadata in Telegram prompt entities.
 */

import { getExtensions, getTarget } from "./targets.js";

// In-Memory Fallback Cache (Isolate-local)
const IN_MEM_SESSIONS = new Map();
const IN_MEM_BUILDS = new Map();

/**
 * Encodes an array of disabled extension keys into a compact hexadecimal bitmask string.
 * Bit i = 1 means enabled, 0 means disabled.
 */
export function encodeBitmask(disabledKeys = [], exts = []) {
  if (!exts || exts.length === 0) return "0";
  let mask = 0;
  const disabledSet = new Set(disabledKeys);
  for (let i = 0; i < exts.length; i++) {
    if (!disabledSet.has(exts[i].key)) {
      mask |= (1 << i);
    }
  }
  return mask.toString(16);
}

/**
 * Decodes a hexadecimal bitmask string into an object detailing enabled/disabled status.
 */
export function decodeBitmask(maskHex, exts = []) {
  if (!exts || exts.length === 0) {
    return { disabled: [], enabledCount: 0, totalCount: 0, isEnabled: () => true };
  }

  const defaultMask = (1 << exts.length) - 1;
  const mask = maskHex !== null && maskHex !== undefined && maskHex !== ""
    ? parseInt(maskHex, 16)
    : defaultMask;

  const disabled = [];
  let enabledCount = 0;

  for (let i = 0; i < exts.length; i++) {
    const isEnabled = (mask & (1 << i)) !== 0;
    if (isEnabled) {
      enabledCount++;
    } else {
      disabled.push(exts[i].key);
    }
  }

  return {
    disabled,
    enabledCount,
    totalCount: exts.length,
    maskHex: mask.toString(16),
    isEnabled: (key) => {
      const idx = exts.findIndex((e) => e.key === key);
      if (idx === -1) return true;
      return (mask & (1 << idx)) !== 0;
    },
  };
}

/**
 * Generates an invisible zero-width markdown link embedding state parameters.
 * Renders as zero-width space (\u200B) in Telegram UI without cluttering chat bubbles.
 */
export function createPromptMetadataTag(field, targetKey, dashMsgId, maskHex) {
  const params = new URLSearchParams({
    f: field || "ipa",
    t: targetKey || "dtkace",
    d: String(dashMsgId || 0),
    m: maskHex || "1fff",
  });
  return `[\u200B](https://tg.internal/p?${params.toString()})`;
}

/**
 * Extracts prompt metadata from Telegram message entities or text.
 * Returns { field, targetKey, dashMsgId, maskHex } or null.
 */
export function extractPromptMetadata(message) {
  if (!message) return null;

  // 1. Inspect text entities
  const entities = message.entities || message.caption_entities || [];
  for (const ent of entities) {
    if (ent.type === "text_link" && ent.url && ent.url.startsWith("https://tg.internal/p?")) {
      try {
        const u = new URL(ent.url);
        return {
          field: u.searchParams.get("f") || "ipa",
          targetKey: u.searchParams.get("t") || "dtkace",
          dashMsgId: parseInt(u.searchParams.get("d") || "0", 10) || null,
          maskHex: u.searchParams.get("m") || "1fff",
        };
      } catch (_) {}
    }
  }

  // 2. Fallback: Parse raw URL string in message text
  const text = message.text || message.caption || "";
  const match = text.match(/https:\/\/tg\.internal\/p\?[^\s)\]]+/);
  if (match) {
    try {
      const u = new URL(match[0]);
      return {
        field: u.searchParams.get("f") || "ipa",
        targetKey: u.searchParams.get("t") || "dtkace",
        dashMsgId: parseInt(u.searchParams.get("d") || "0", 10) || null,
        maskHex: u.searchParams.get("m") || "1fff",
      };
    } catch (_) {}
  }

  return null;
}

/**
 * Normalizes input URL (ensures direct download dl=1 for Dropbox links).
 */
export function normalizeUrl(url) {
  if (!url) return "";
  let cleaned = url.trim();
  if (cleaned.includes("dropbox.com")) {
    if (cleaned.includes("dl=0")) {
      cleaned = cleaned.replace("dl=0", "dl=1");
    } else if (!cleaned.includes("dl=1")) {
      cleaned += (cleaned.includes("?") ? "&dl=1" : "?dl=1");
    }
  }
  return cleaned;
}

/**
 * Compiles GitHub Actions workflow inputs based on target & state.
 */
export function compileWorkflowInputs(state, target) {
  const inputs = {
    ipa_url: state.ipa || "",
    display_name: state.name || target.defaultInputs?.display_name || "DexTube",
    bundle_id: state.bundle || target.defaultInputs?.bundle_id || "com.google.ios.youtube",
  };

  if (target.hasExtensions) {
    if (state.tweak) {
      inputs.custom_tweak = "true";
      inputs.tweak_url = state.tweak;
    }
    const exts = getExtensions(target.key);
    const decoded = decodeBitmask(state.maskHex, exts);
    for (const ext of exts) {
      inputs[ext.input] = decoded.isEnabled(ext.key) ? "true" : "false";
    }
  }

  return inputs;
}

/**
 * Saves session data to Cloudflare KV (if configured), Cache API, or Memory.
 */
export async function saveSession(env, chatId, data) {
  if (!chatId) return;
  const strId = String(chatId);
  IN_MEM_SESSIONS.set(strId, data);

  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.put(`session_${strId}`, JSON.stringify(data), { expirationTtl: 3600 });
      return;
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      const cacheKey = new Request(`https://telegram-session.worker.dev/session/${strId}`);
      await caches.default.put(
        cacheKey,
        new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json", "Cache-Control": "max-age=3600" },
        })
      );
    }
  } catch (_) {}
}

/**
 * Retrieves session data from Cloudflare KV, Cache API, or Memory.
 */
export async function getSession(env, chatId) {
  if (!chatId) return null;
  const strId = String(chatId);
  const inMem = IN_MEM_SESSIONS.get(strId);
  if (inMem) return inMem;

  if (env && env.SESSION_KV) {
    try {
      const val = await env.SESSION_KV.get(`session_${strId}`);
      if (val) return JSON.parse(val);
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      const cacheKey = new Request(`https://telegram-session.worker.dev/session/${strId}`);
      const res = await caches.default.match(cacheKey);
      if (res) return await res.json();
    }
  } catch (_) {}

  return null;
}

/**
 * Clears session data from all storage tiers.
 */
export async function clearSession(env, chatId) {
  if (!chatId) return;
  const strId = String(chatId);
  IN_MEM_SESSIONS.delete(strId);

  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.delete(`session_${strId}`);
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      await caches.default.delete(new Request(`https://telegram-session.worker.dev/session/${strId}`));
    }
  } catch (_) {}
}

/**
 * Stores an active workflow build tracking record.
 */
export async function saveActiveBuild(env, build) {
  const id = `${build.chatId}_${build.messageId}`;
  IN_MEM_BUILDS.set(id, build);

  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.put(`build_${id}`, JSON.stringify(build), { expirationTtl: 3600 });
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      const itemKey = new Request(`https://telegram-session.worker.dev/builds/${id}`);
      await caches.default.put(
        itemKey,
        new Response(JSON.stringify(build), {
          headers: { "Content-Type": "application/json", "Cache-Control": "max-age=3600" },
        })
      );
    }
  } catch (_) {}
}

/**
 * Lists all active workflow build tracking records.
 */
export async function listActiveBuilds(env) {
  const map = new Map();

  // 1. In-Memory
  for (const [k, v] of IN_MEM_BUILDS.entries()) {
    map.set(k, v);
  }

  // 2. KV if configured
  if (env && env.SESSION_KV) {
    try {
      const list = await env.SESSION_KV.list({ prefix: "build_" });
      for (const k of list.keys || []) {
        const val = await env.SESSION_KV.get(k.name);
        if (val) {
          const parsed = JSON.parse(val);
          map.set(`${parsed.chatId}_${parsed.messageId}`, parsed);
        }
      }
    } catch (_) {}
  }

  return Array.from(map.values());
}

/**
 * Removes an active workflow build tracking record once completed.
 */
export async function deleteActiveBuild(env, chatId, messageId) {
  const id = `${chatId}_${messageId}`;
  IN_MEM_BUILDS.delete(id);

  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.delete(`build_${id}`);
    } catch (_) {}
  }

  try {
    if (typeof caches !== "undefined" && caches.default) {
      await caches.default.delete(new Request(`https://telegram-session.worker.dev/builds/${id}`));
    }
  } catch (_) {}
}
