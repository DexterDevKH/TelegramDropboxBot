/**
 * Telegram to GitHub Actions Serverless Dispatcher
 * Hosted on Cloudflare Workers (Free Tier: 100k requests/day)
 *
 * Receives incoming file uploads from Telegram Webhooks, sends an immediate
 * acknowledgement to the user, and triggers GitHub Actions on-demand via repository_dispatch.
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Telegram Webhook Gateway Active", { status: 200 });
    }

    // Optional Telegram Secret Token verification
    if (env.TELEGRAM_SECRET_TOKEN) {
      const receivedSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (receivedSecret !== env.TELEGRAM_SECRET_TOKEN) {
        return new Response("Unauthorized Secret Token", { status: 403 });
      }
    }

    try {
      const update = await request.json();
      const message = update.message || update.edited_message;

      // Ignore updates without message body
      if (!message) {
        return new Response("OK", { status: 200 });
      }

      const userId = message.from?.id;
      const chatId = message.chat?.id;
      const messageId = message.message_id;

      // 1. Authorization Filter
      if (env.AUTHORIZED_USER_IDS) {
        const allowed = env.AUTHORIZED_USER_IDS.split(",")
          .map((id) => id.trim())
          .filter(Boolean);
        if (allowed.length > 0 && !allowed.includes(String(userId))) {
          // Send unauthorized notice if a direct user attempts access
          await sendTelegramMessage(
            env.TELEGRAM_BOT_TOKEN,
            chatId,
            messageId,
            "🔒 **ACCESS RESTRICTED**\n──────────────────────────────\nYour Telegram ID is not authorized to dispatch this cloud pipeline."
          );
          return new Response("OK", { status: 200 });
        }
      }

      // 2. Detect Actionable Content (Media or Commands)
      const hasMedia = Boolean(
        message.document ||
        message.video ||
        message.audio ||
        message.photo ||
        message.voice ||
        message.video_note
      );
      const text = message.text || message.caption || "";
      const isCommand = text.startsWith("/");

      if (!hasMedia && !isCommand) {
        return new Response("OK", { status: 200 });
      }

      // 3. Instant User Feedback
      let notice = "";
      if (hasMedia) {
        const fileName = message.document?.file_name || message.video?.file_name || "Attachment";
        notice =
          "⚡ **TRANSFER REQUEST RECEIVED**\n" +
          "──────────────────────────────\n" +
          `📄 **Target:** \`${fileName}\`\n` +
          "🛰️ **Status:** *Dispatching GitHub Actions cloud runner...*\n" +
          "⏳ *Transfer engine will engage in ~25-30s.*";
      } else {
        notice =
          "🛰️ **COMMAND RECEIVED**\n" +
          "──────────────────────────────\n" +
          `⌨️ **Command:** \`${text.split(" ")[0]}\`\n` +
          "⚡ *Waking up cloud engine to process request...*";
      }

      await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, messageId, notice);

      // 4. Trigger GitHub Actions via repository_dispatch API
      const repo = env.GH_REPO || "DexterDevKH/TelegramDropboxBot";
      const ghResponse = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_PAT}`,
          Accept: "application/vnd.github.v3+json",
          "User-Agent": "Cloudflare-Worker-Telegram-Trigger",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          event_type: "telegram_sync",
          client_payload: {
            chat_id: chatId,
            message_id: messageId,
            user_id: userId,
            has_media: hasMedia,
            text: text,
          },
        }),
      });

      if (!ghResponse.ok) {
        const errDetails = await ghResponse.text();
        console.error(`GitHub Actions dispatch error (${ghResponse.status}):`, errDetails);
      }

      return new Response("OK", { status: 200 });
    } catch (err) {
      console.error("Worker Execution Error:", err);
      // Always return 200 to prevent Telegram from spamming retry requests on unhandled errors
      return new Response("OK", { status: 200 });
    }
  },
};

/**
 * Sends a Markdown formatted response directly via Telegram Bot API
 */
async function sendTelegramMessage(botToken, chatId, replyToId, text) {
  if (!botToken || !chatId) return;
  try {
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "Markdown",
        reply_to_message_id: replyToId,
      }),
    });
  } catch (err) {
    console.error("Telegram message delivery failed:", err);
  }
}
