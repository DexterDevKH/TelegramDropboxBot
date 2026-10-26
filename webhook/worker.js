/**
 * Telegram to GitHub Actions Serverless Dispatcher
 * Hosted on Cloudflare Workers (Free Tier: 100k requests/day)
 *
 * Receives incoming file uploads from Telegram Webhooks, sends an immediate
 * acknowledgement to the user, and triggers GitHub Actions on-demand via repository_dispatch.
 */

export default {
  async fetch(request, env) {
    // Health check endpoint for browser verification
    if (request.method !== "POST") {
      return new Response(
        JSON.stringify(
          {
            status: "healthy",
            gateway: "Cloudflare Global Edge",
            service: "Telegram to Dropbox Serverless Sync Dispatcher",
            repo: env.GH_REPO || "DexterDevKH/TelegramDropboxBot",
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

      // 3. Instant Edge Command Handling (Saves GitHub Actions runs on text commands)
      if (isCommand && !hasMedia) {
        const cmd = text.split(" ")[0].toLowerCase();
        if (cmd === "/ping") {
          await sendTelegramMessage(
            env.TELEGRAM_BOT_TOKEN,
            chatId,
            messageId,
            "⚡ **GATEWAY PONG**\n──────────────────────────────\n🟢 **Status:** Operational (100%)\n🛰️ **Host:** Cloudflare Global Edge (~15ms)\n⚡ **Engine:** Serverless On-Demand Runner\n💡 *Upload any document, video, or archive up to 2 GB to sync.*"
          );
          return new Response("OK", { status: 200 });
        }
        if (cmd === "/status" || cmd === "/info") {
          await sendTelegramMessage(
            env.TELEGRAM_BOT_TOKEN,
            chatId,
            messageId,
            "📊 **SYSTEM STATUS MONITOR**\n──────────────────────────────\n" +
            "🟢 **Gateway:** `Cloudflare Global Edge (Operational)`\n" +
            "🛰️ **Pipeline Mode:** `100% Serverless On-Demand`\n" +
            "⚡ **Runner State:** `Standing By (0s idle usage)`\n" +
            "📦 **Payload Limit:** `Up to 2,000 MB (2.0 GB)`\n" +
            "──────────────────────────────\n" +
            "💡 *Upload any media file to automatically engage cloud sync.*"
          );
          return new Response("OK", { status: 200 });
        }
        if (cmd === "/start" || cmd === "/help") {
          await sendTelegramMessage(
            env.TELEGRAM_BOT_TOKEN,
            chatId,
            messageId,
            "⚡ **TELEGRAM TO DROPBOX SYNC PIPELINE**\n──────────────────────────────\n" +
            "📥 **Quick Transfer:** Simply forward or upload any document, video, archive, or IPA.\n\n" +
            "✨ **Features:**\n" +
            "• Up to **2 GB** files supported via Telethon MTProto\n" +
            "• Real-time progress updates & native 1-tap OS copy button\n" +
            "• Automated FIFO folder retention\n" +
            "• 100% serverless on-demand runner (0 idle waste)\n" +
            "──────────────────────────────\n" +
            "🟢 **Status:** Armed and ready."
          );
          return new Response("OK", { status: 200 });
        }
      }

      // 4. Extract Detailed Media Metadata
      let fileName = "Attachment";
      let fileSize = 0;

      if (message.document) {
        fileName = message.document.file_name || `document_${messageId}.bin`;
        fileSize = message.document.file_size || 0;
      } else if (message.video) {
        fileName = message.video.file_name || `video_${messageId}.mp4`;
        fileSize = message.video.file_size || 0;
      } else if (message.audio) {
        fileName = message.audio.file_name || `${message.audio.title || "audio"}_${messageId}.mp3`;
        fileSize = message.audio.file_size || 0;
      } else if (message.photo && Array.isArray(message.photo) && message.photo.length > 0) {
        fileName = `photo_${messageId}.jpg`;
        fileSize = message.photo[message.photo.length - 1].file_size || 0;
      } else if (message.voice) {
        fileName = `voice_${messageId}.ogg`;
        fileSize = message.voice.file_size || 0;
      } else if (message.video_note) {
        fileName = `videonote_${messageId}.mp4`;
        fileSize = message.video_note.file_size || 0;
      }

      // 5. Send Initial In-Place Notice to User
      const formattedSize = formatSize(fileSize);
      let notice = "";
      if (hasMedia) {
        notice =
          "⚡ **TRANSFER REQUEST RECEIVED**\n" +
          "──────────────────────────────\n" +
          `📄 **Target:** \`${fileName}\`\n` +
          (fileSize > 0 ? `📦 **Filesize:** \`${formattedSize}\`\n` : "") +
          "🛰️ **Status:** *Dispatching GitHub Actions cloud runner...*\n" +
          "⏳ *Transfer engine will engage in ~25-30s.*";
      } else {
        notice =
          "🛰️ **COMMAND RECEIVED**\n" +
          "──────────────────────────────\n" +
          `⌨️ **Command:** \`${text.split(" ")[0]}\`\n` +
          "⚡ *Waking up cloud engine to process request...*";
      }

      const sentNotice = await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, messageId, notice);
      const dispatchMessageId = sentNotice?.message_id || null;

      // 6. Trigger GitHub Actions via repository_dispatch API
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
            dispatch_message_id: dispatchMessageId,
            user_id: userId,
            has_media: hasMedia,
            file_name: fileName,
            text: text,
          },
        }),
      });

      // 7. Error Handling: Notify User if GitHub API Rejects Dispatch
      if (!ghResponse.ok) {
        const errDetails = await ghResponse.text();
        console.error(`GitHub Actions dispatch error (${ghResponse.status}):`, errDetails);
        if (dispatchMessageId) {
          await editTelegramMessage(
            env.TELEGRAM_BOT_TOKEN,
            chatId,
            dispatchMessageId,
            `❌ **DISPATCH FAILED**\n──────────────────────────────\n⚠️ GitHub API Error (${ghResponse.status})\n💡 *Please verify your GH_PAT secret in Cloudflare Worker settings.*`
          );
        }
      }

      return new Response("OK", { status: 200 });
    } catch (err) {
      console.error("Worker Execution Error:", err);
      return new Response("OK", { status: 200 });
    }
  },
};

/**
 * Format bytes into human-readable strings
 */
function formatSize(bytes) {
  if (!bytes) return "Unknown size";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let val = bytes;
  let i = 0;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

/**
 * Sends a Markdown formatted response directly via Telegram Bot API
 */
async function sendTelegramMessage(botToken, chatId, replyToId, text) {
  if (!botToken || !chatId) return null;
  try {
    const resp = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "Markdown",
        reply_to_message_id: replyToId,
      }),
    });
    const data = await resp.json();
    return data.result || null;
  } catch (err) {
    console.error("Telegram message delivery failed:", err);
    return null;
  }
}

/**
 * Edits an existing Telegram message in-place
 */
async function editTelegramMessage(botToken, chatId, messageId, text) {
  if (!botToken || !chatId || !messageId) return false;
  try {
    await fetch(`https://api.telegram.org/bot${botToken}/editMessageText`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_id: messageId,
        text: text,
        parse_mode: "Markdown",
      }),
    });
    return true;
  } catch (err) {
    console.error("Telegram edit message failed:", err);
    return false;
  }
}
