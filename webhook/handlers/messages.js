/**
 * Incoming Message Handler (Commands, Input Prompts, URLs, and Media Transfers)
 */

import { BUILD_TARGETS, getExtensions, getTarget } from "../targets.js";
import {
  getSession,
  saveSession,
  normalizeUrl,
  compileWorkflowInputs,
  extractPromptMetadata,
} from "../state.js";
import {
  sendMessage,
  editMessageText,
  deleteMessage,
  formatBytes,
} from "../telegram.js";
import {
  triggerWorkflowDispatch,
  dispatchSyncPipeline,
} from "../github.js";
import {
  renderMainMenuText,
  renderMainMenuButtons,
  renderDashboardText,
  renderDashboardButtons,
  renderBuildSuccessCard,
  renderBuildFailureCard,
  renderStatusCard,
  renderHelpCard,
  renderPingCard,
  renderMediaNoticeCard,
  renderUrlDetectedCard,
} from "../ui.js";

export async function handleIncomingMessage(message, env, ctx) {
  const chatId = message.chat?.id;
  const messageId = message.message_id;
  const userId = message.from?.id;

  const hasMedia = Boolean(
    message.document ||
    message.video ||
    message.audio ||
    message.photo ||
    message.voice ||
    message.video_note
  );
  const rawText = message.text || message.caption || "";
  const isCommand = rawText.startsWith("/");

  // 1. /cancel Command
  if ((rawText.trim().toLowerCase() === "/cancel" || rawText.trim().toLowerCase() === "cancel") && !hasMedia) {
    const session = await getSession(env, chatId);
    const promptMsgId = message.reply_to_message?.message_id || session?.pendingPromptId;

    if (promptMsgId) {
      await deleteMessage(env.TELEGRAM_BOT_TOKEN, chatId, promptMsgId);
    }
    await deleteMessage(env.TELEGRAM_BOT_TOKEN, chatId, messageId);
    if (session) {
      session.pendingPromptId = null;
      session.pendingField = null;
      await saveSession(env, chatId, session);
    }
    return new Response("OK", { status: 200 });
  }

  // 2. Reply to Input Prompt (IPA, Name, Bundle, Tweak)
  const promptMeta = extractPromptMetadata(message.reply_to_message);
  const session = await getSession(env, chatId);
  const isPendingInput = Boolean(promptMeta || session?.pendingField);

  if (isPendingInput && rawText && !hasMedia && !isCommand) {
    const field = promptMeta?.field || session?.pendingField || "ipa";
    const targetKey = promptMeta?.targetKey || session?.targetKey || "dtkace";
    const dashMsgId = promptMeta?.dashMsgId || session?.dashMsgId;
    const maskHex = promptMeta?.maskHex || session?.maskHex || "1fff";
    const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;
    const cleanVal = rawText.trim();

    const state = session || {
      targetKey,
      dashMsgId,
      maskHex,
      ipa: "",
      name: target.defaultInputs?.display_name || "DexTube",
      bundle: target.defaultInputs?.bundle_id || "com.google.ios.youtube",
      tweak: "",
    };

    if (field === "ipa") {
      const urlMatch = cleanVal.match(/https?:\/\/[^\s<>"]+/i);
      if (urlMatch) {
        state.ipa = normalizeUrl(urlMatch[0]);
      } else {
        await deleteMessage(env.TELEGRAM_BOT_TOKEN, chatId, messageId);
        return new Response("OK", { status: 200 });
      }
    } else if (field === "name") {
      state.name = cleanVal;
    } else if (field === "bundle") {
      state.bundle = cleanVal;
    } else if (field === "tweak") {
      if (["default", "none", "clear"].includes(cleanVal.toLowerCase())) {
        state.tweak = "";
      } else {
        const urlMatch = cleanVal.match(/https?:\/\/[^\s<>"]+/i);
        state.tweak = urlMatch ? normalizeUrl(urlMatch[0]) : cleanVal;
      }
    }

    // Clean chat: Delete prompt message and user reply message
    const promptMsgId = message.reply_to_message?.message_id || session?.pendingPromptId;
    if (promptMsgId) {
      await deleteMessage(env.TELEGRAM_BOT_TOKEN, chatId, promptMsgId);
    }
    await deleteMessage(env.TELEGRAM_BOT_TOKEN, chatId, messageId);

    state.pendingPromptId = null;
    state.pendingField = null;
    await saveSession(env, chatId, state);

    // Edit dashboard in-place
    if (dashMsgId) {
      await editMessageText(
        env.TELEGRAM_BOT_TOKEN,
        chatId,
        dashMsgId,
        renderDashboardText(state),
        { reply_markup: { inline_keyboard: renderDashboardButtons(state, dashMsgId) } }
      );
    }

    return new Response("OK", { status: 200 });
  }

  // 3. Bare IPA URL Detection
  if (!hasMedia && !isCommand && rawText) {
    const urlMatch = rawText.match(/https?:\/\/[^\s<>"]+/i);
    if (urlMatch) {
      const rawUrl = normalizeUrl(urlMatch[0]);
      const card = renderUrlDetectedCard(rawUrl);

      const sentMsg = await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, card.text, {
        reply_to_message_id: messageId,
        reply_markup: { inline_keyboard: card.buttons },
      });

      await saveSession(env, chatId, {
        ipa: rawUrl,
        dashMsgId: sentMsg?.message_id,
      });

      return new Response("OK", { status: 200 });
    }
  }

  // 4. Instant Edge Commands
  if (isCommand && !hasMedia) {
    const cmd = rawText.split(" ")[0].toLowerCase();

    if (cmd === "/build") {
      const args = rawText.trim().split(/\s+/);

      // Fast syntax: /build <target> <ipa_url>
      if (args.length >= 3 && BUILD_TARGETS[args[1].toLowerCase()]) {
        const target = BUILD_TARGETS[args[1].toLowerCase()];
        const ipaUrl = normalizeUrl(args[2]);
        const state = {
          targetKey: target.key,
          ipa: ipaUrl,
          name: target.defaultInputs?.display_name || "DexTube",
          bundle: target.defaultInputs?.bundle_id || "com.google.ios.youtube",
          tweak: "",
          maskHex: ((1 << getExtensions(target.key).length) - 1).toString(16),
        };

        const statusMsg = await sendMessage(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          `⏳ **DISPATCHING WORKFLOW...**\n──────────────────────────────\n` +
          `📦 **Target:** \`${target.name}\`\n` +
          `📄 **Workflow:** \`${target.workflow}\`\n` +
          `🔗 **IPA URL:** \`${ipaUrl}\``,
          { reply_to_message_id: messageId }
        );

        const inputs = compileWorkflowInputs(state, target);
        const result = await triggerWorkflowDispatch(env.GH_PAT, target.repo, target.workflow, inputs);

        if (result.success) {
          const card = renderBuildSuccessCard(target, inputs, []);
          await editMessageText(env.TELEGRAM_BOT_TOKEN, chatId, statusMsg?.message_id, card.text, {
            reply_markup: { inline_keyboard: card.buttons },
          });
        } else {
          const failCard = renderBuildFailureCard(target, result);
          await editMessageText(env.TELEGRAM_BOT_TOKEN, chatId, statusMsg?.message_id, failCard);
        }
        return new Response("OK", { status: 200 });
      }

      // Interactive UI menu: /build
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, renderMainMenuText(), {
        reply_to_message_id: messageId,
        reply_markup: { inline_keyboard: renderMainMenuButtons() },
      });
      return new Response("OK", { status: 200 });
    }

    if (cmd === "/ping") {
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, renderPingCard(), {
        reply_to_message_id: messageId,
      });
      return new Response("OK", { status: 200 });
    }

    if (cmd === "/status" || cmd === "/info") {
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, renderStatusCard(env), {
        reply_to_message_id: messageId,
      });
      return new Response("OK", { status: 200 });
    }

    if (cmd === "/start" || cmd === "/help") {
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, renderHelpCard(), {
        reply_to_message_id: messageId,
      });
      return new Response("OK", { status: 200 });
    }
  }

  // 5. Media Upload Ingestion -> Dispatch On-Demand CI Runner
  if (hasMedia) {
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

    const formattedSize = formatBytes(fileSize);
    const noticeText = renderMediaNoticeCard(fileName, formattedSize);

    const sentNotice = await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, noticeText, {
      reply_to_message_id: messageId,
    });
    const dispatchMessageId = sentNotice?.message_id || null;

    const payload = {
      chat_id: chatId,
      message_id: messageId,
      dispatch_message_id: dispatchMessageId,
      user_id: userId,
      has_media: true,
      file_name: fileName,
      file_size: fileSize,
      text: rawText,
    };

    const repo = env.GH_REPO || "DexterDevKH/TelegramDropboxBot";
    const dispatchResult = await dispatchSyncPipeline(env.GH_PAT, repo, payload);

    if (!dispatchResult.success) {
      console.error(`[GitHub Actions Dispatch Error ${dispatchResult.status}]:`, dispatchResult.error);
      if (dispatchMessageId) {
        await editMessageText(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          dispatchMessageId,
          `❌ **DISPATCH FAILED**\n──────────────────────────────\n` +
          `⚠️ GitHub Actions API Error (HTTP ${dispatchResult.status})\n` +
          `💡 *Please verify your GH_PAT secret in Cloudflare Worker settings.*`
        );
      }
    }

    return new Response("OK", { status: 200 });
  }

  return new Response("OK", { status: 200 });
}

