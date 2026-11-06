/**
 * Telegram to Dropbox & Build Dispatcher (Cloudflare Worker v3.0.0)
 * High-performance edge gateway for 24/7 autonomous Telegram operations.
 */

import { sendMessage, answerCallbackQuery } from "./telegram.js";
import { handleCallbackQuery } from "./handlers/callbacks.js";
import { handleIncomingMessage } from "./handlers/messages.js";
import { checkAllActiveBuilds } from "./handlers/scheduler.js";

export default {
  async fetch(request, env, ctx) {
    // 1. Health check endpoint
    if (request.method !== "POST") {
      return new Response(
        JSON.stringify(
          {
            status: "healthy",
            version: "3.0.0",
            gateway: "Cloudflare Global Edge",
            service: "Telegram to Dropbox & Build Gateway",
            repo: env.GH_REPO || "DexterDevKH/TelegramDropboxBot",
            timestamp: new Date().toISOString(),
          },
          null,
          2
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // 2. Secret Token verification (Optional header check)
    if (env.TELEGRAM_SECRET_TOKEN) {
      const receivedSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (receivedSecret !== env.TELEGRAM_SECRET_TOKEN) {
        return new Response("Unauthorized Secret Token", { status: 403 });
      }
    }

    try {
      const update = await request.json();
      const callbackQuery = update.callback_query;
      const message = update.message || update.edited_message;

      if (!message && !callbackQuery) {
        return new Response("OK", { status: 200 });
      }

      const userId = (message?.from || callbackQuery?.from)?.id;
      const chatId = (message?.chat || callbackQuery?.message?.chat)?.id;
      const messageId = message?.message_id || callbackQuery?.message?.message_id;

      // 3. Authorization Filter
      if (env.AUTHORIZED_USER_IDS) {
        const allowed = env.AUTHORIZED_USER_IDS.split(",")
          .map((id) => id.trim())
          .filter(Boolean);
        if (allowed.length > 0 && !allowed.includes(String(userId))) {
          if (callbackQuery) {
            await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, callbackQuery.id, "Unauthorized Access", true);
          } else {
            await sendMessage(
              env.TELEGRAM_BOT_TOKEN,
              chatId,
              "🔒 **ACCESS RESTRICTED**\n──────────────────────────────\nYour Telegram ID is not authorized to use this pipeline.",
              { reply_to_message_id: messageId }
            );
          }
          return new Response("OK", { status: 200 });
        }
      }

      // 4. Route Callbacks or Messages
      if (callbackQuery) {
        return await handleCallbackQuery(callbackQuery, env, ctx);
      }

      if (message) {
        return await handleIncomingMessage(message, env, ctx);
      }

      return new Response("OK", { status: 200 });
    } catch (err) {
      console.error("[Worker Runtime Error]:", err);
      return new Response("OK", { status: 200 });
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(checkAllActiveBuilds(env));
  },
};
