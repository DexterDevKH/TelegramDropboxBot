/**
 * Telegram Bot API HTTP Client
 * Provides robust, resilient wrappers for Telegram Bot API operations
 * with automatic fallback on Markdown parse errors.
 */

const BASE_URL = "https://api.telegram.org";

/**
 * Sends a message via Telegram Bot API with automatic Markdown parse error recovery.
 */
export async function sendMessage(botToken, chatId, text, options = {}) {
  if (!botToken || !chatId) return null;
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: options.parse_mode !== undefined ? options.parse_mode : "Markdown",
    disable_web_page_preview: options.disable_web_page_preview ?? true,
  };

  if (options.reply_to_message_id) {
    payload.reply_to_message_id = options.reply_to_message_id;
  }
  if (options.reply_markup) {
    payload.reply_markup = options.reply_markup;
  }

  try {
    const res = await fetch(`${BASE_URL}/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      // Auto-fallback: if Markdown parsing failed, retry as plain text
      if (payload.parse_mode && data.description && data.description.includes("can't parse entities")) {
        delete payload.parse_mode;
        const retryRes = await fetch(`${BASE_URL}/bot${botToken}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const retryData = await retryRes.json();
        return retryData.result || null;
      }
      console.warn(`[Telegram sendMessage Error ${res.status}]:`, data.description || data);
    }
    return data.result || null;
  } catch (err) {
    console.error("[Telegram sendMessage Network Error]:", err);
    return null;
  }
}

/**
 * Edits message text and/or reply markup in-place.
 */
export async function editMessageText(botToken, chatId, messageId, text, options = {}) {
  if (!botToken || !chatId || !messageId) return false;
  const payload = {
    chat_id: chatId,
    message_id: messageId,
    text: text,
    parse_mode: options.parse_mode !== undefined ? options.parse_mode : "Markdown",
    disable_web_page_preview: options.disable_web_page_preview ?? true,
  };

  if (options.reply_markup) {
    payload.reply_markup = options.reply_markup;
  }

  try {
    const res = await fetch(`${BASE_URL}/bot${botToken}/editMessageText`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      // Ignore if text is identical
      if (data.description && data.description.includes("message is not modified")) {
        return true;
      }
      // Markdown fallback
      if (payload.parse_mode && data.description && data.description.includes("can't parse entities")) {
        delete payload.parse_mode;
        const retryRes = await fetch(`${BASE_URL}/bot${botToken}/editMessageText`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const retryData = await retryRes.json();
        return Boolean(retryData.ok);
      }
      console.warn(`[Telegram editMessageText Error ${res.status}]:`, data.description || data);
    }
    return Boolean(data.ok);
  } catch (err) {
    console.error("[Telegram editMessageText Network Error]:", err);
    return false;
  }
}

/**
 * Edits only the reply markup (buttons) of an existing message.
 */
export async function editMessageReplyMarkup(botToken, chatId, messageId, replyMarkup) {
  if (!botToken || !chatId || !messageId) return false;
  try {
    const res = await fetch(`${BASE_URL}/bot${botToken}/editMessageReplyMarkup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_id: messageId,
        reply_markup: replyMarkup || { inline_keyboard: [] },
      }),
    });
    const data = await res.json();
    return Boolean(data.ok);
  } catch (err) {
    console.error("[Telegram editMessageReplyMarkup Network Error]:", err);
    return false;
  }
}

/**
 * Deletes a message from a chat.
 */
export async function deleteMessage(botToken, chatId, messageId) {
  if (!botToken || !chatId || !messageId) return false;
  try {
    const res = await fetch(`${BASE_URL}/bot${botToken}/deleteMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, message_id: messageId }),
    });
    const data = await res.json();
    return Boolean(data.ok);
  } catch (err) {
    console.error("[Telegram deleteMessage Network Error]:", err);
    return false;
  }
}

/**
 * Answers incoming Telegram callback query.
 */
export async function answerCallbackQuery(botToken, callbackQueryId, text = "", showAlert = false) {
  if (!botToken || !callbackQueryId) return false;
  const payload = {
    callback_query_id: callbackQueryId,
    show_alert: showAlert,
  };
  if (text) {
    payload.text = text;
  }

  try {
    const res = await fetch(`${BASE_URL}/bot${botToken}/answerCallbackQuery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    return Boolean(data.ok);
  } catch (err) {
    console.error("[Telegram answerCallbackQuery Network Error]:", err);
    return false;
  }
}

/**
 * Formats byte size into human-readable representation.
 */
export function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let val = bytes;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx++;
  }
  return `${val.toFixed(2)} ${units[idx]}`;
}
