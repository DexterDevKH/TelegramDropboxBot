/**
 * Callback Query Handler (Inline Button Clicks)
 */

import { BUILD_TARGETS, getExtensions, getTarget } from "../targets.js";
import {
  getSession,
  saveSession,
  clearSession,
  saveActiveBuild,
  compileWorkflowInputs,
  createPromptMetadataTag,
} from "../state.js";
import {
  editMessageText,
  editMessageReplyMarkup,
  answerCallbackQuery,
  sendMessage,
} from "../telegram.js";
import {
  triggerWorkflowDispatch,
  getLatestWorkflowRun,
  getWorkflowRunDetails,
  getLatestRelease,
  dispatchSyncPipeline,
} from "../github.js";
import {
  renderMainMenuText,
  renderMainMenuButtons,
  renderDashboardText,
  renderDashboardButtons,
  renderExtensionsKeyboard,
  renderBuildTrackingCard,
  renderBuildCompletedCard,
  renderBuildFailedCard,
  renderBuildFailureCard,
} from "../ui.js";
import { trackInitialWindow } from "./scheduler.js";

export async function handleCallbackQuery(callbackQuery, env, ctx) {
  const queryId = callbackQuery.id;
  const cbData = callbackQuery.data || "";
  const cbChatId = callbackQuery.message?.chat?.id;
  const cbMessageId = callbackQuery.message?.message_id;

  if (!cbChatId || !cbMessageId) {
    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId);
    return new Response("OK", { status: 200 });
  }

  // 1. Action: Cancel
  if (cbData === "cancel" || cbData === "build_cancel") {
    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "Cancelled.");
    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      cbMessageId,
      "🚫 **BUILD REQUEST CANCELLED**\n──────────────────────────────\nNo workflow dispatch was initiated."
    );
    await clearSession(env, cbChatId);
    return new Response("OK", { status: 200 });
  }

  // 2. Action: Return to Main Menu
  if (cbData === "menu" || cbData === "build_menu") {
    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId);
    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      cbMessageId,
      renderMainMenuText(),
      { reply_markup: { inline_keyboard: renderMainMenuButtons() } }
    );
    return new Response("OK", { status: 200 });
  }

  // 3. Action: App Selected from Main Menu
  if (cbData.startsWith("sel:") || cbData.startsWith("build_select:")) {
    const targetKey = cbData.split(":")[1];
    const target = getTarget(targetKey);
    if (!target) {
      await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "Unknown target.");
      return new Response("OK", { status: 200 });
    }

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, `Selected ${target.name}`);

    const session = await getSession(env, cbChatId);
    const exts = getExtensions(targetKey);
    const defaultMask = (1 << exts.length) - 1;

    const state = {
      targetKey: targetKey,
      dashMsgId: cbMessageId,
      ipa: session?.ipa || "",
      name: session?.name || target.defaultInputs?.display_name || "DexTube",
      bundle: session?.bundle || target.defaultInputs?.bundle_id || "com.google.ios.youtube",
      tweak: session?.tweak || "",
      maskHex: defaultMask.toString(16),
    };

    await saveSession(env, cbChatId, state);

    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      cbMessageId,
      renderDashboardText(state),
      { reply_markup: { inline_keyboard: renderDashboardButtons(state, cbMessageId) } }
    );
    return new Response("OK", { status: 200 });
  }

  // 4. Action: Open Extensions Toggle Menu
  if (cbData.startsWith("ext:") || cbData.startsWith("open_exts:")) {
    const parts = cbData.split(":");
    const targetKey = parts[1];
    const dashMsgId = parts[2] || cbMessageId;
    const maskHex = parts[3] || "1fff";
    const target = getTarget(targetKey);
    if (!target || !target.hasExtensions) {
      await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "No extensions available.");
      return new Response("OK", { status: 200 });
    }

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, `Editing ${target.name} extensions`);

    const mid = parseInt(dashMsgId, 10) || cbMessageId;
    const kb = renderExtensionsKeyboard(targetKey, mid, maskHex);

    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      mid,
      `⚙️ **CONFIGURE EXTENSIONS: ${target.name}**\n` +
      `──────────────────────────────\n` +
      `Tap any extension below to toggle it **On (✅)** or **Off (❌)**.\n` +
      `When satisfied, tap **[ 💾 Save & Back ]** below:`,
      { reply_markup: { inline_keyboard: kb } }
    );
    return new Response("OK", { status: 200 });
  }

  // 5. Action: Toggle Individual Extension
  if (cbData.startsWith("tgl:")) {
    const [, targetKey, dashMsgId, extIdxStr, maskHex] = cbData.split(":");
    const extIdx = parseInt(extIdxStr, 10);
    const exts = getExtensions(targetKey);
    const mid = parseInt(dashMsgId, 10) || cbMessageId;

    const currentMask = parseInt(maskHex, 16);
    const newMask = currentMask ^ (1 << extIdx);
    const newMaskHex = newMask.toString(16);

    const newKb = renderExtensionsKeyboard(targetKey, mid, newMaskHex);
    await editMessageReplyMarkup(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, {
      inline_keyboard: newKb,
    });

    const isNowEnabled = (newMask & (1 << extIdx)) !== 0;
    const extName = exts[extIdx]?.name || `Ext #${extIdx}`;
    await answerCallbackQuery(
      env.TELEGRAM_BOT_TOKEN,
      queryId,
      `${extName}: ${isNowEnabled ? "Enabled ✅" : "Disabled ❌"}`
    );
    return new Response("OK", { status: 200 });
  }

  // 6. Action: Toggle All
  if (cbData.startsWith("tgl_all:")) {
    const [, targetKey, dashMsgId, maskHex] = cbData.split(":");
    const exts = getExtensions(targetKey);
    const mid = parseInt(dashMsgId, 10) || cbMessageId;

    const currentMask = parseInt(maskHex, 16);
    const fullMask = (1 << exts.length) - 1;
    const newMask = currentMask === 0 ? fullMask : 0;
    const newMaskHex = newMask.toString(16);

    const newKb = renderExtensionsKeyboard(targetKey, mid, newMaskHex);
    await editMessageReplyMarkup(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, {
      inline_keyboard: newKb,
    });

    await answerCallbackQuery(
      env.TELEGRAM_BOT_TOKEN,
      queryId,
      newMask > 0 ? "All extensions enabled ✅" : "All extensions disabled ❌"
    );
    return new Response("OK", { status: 200 });
  }

  // 7. Action: Reset Extensions
  if (cbData.startsWith("tgl_rst:") || cbData.startsWith("tgl_reset:")) {
    const [, targetKey, dashMsgId] = cbData.split(":");
    const exts = getExtensions(targetKey);
    const mid = parseInt(dashMsgId, 10) || cbMessageId;
    const fullMask = (1 << exts.length) - 1;
    const newMaskHex = fullMask.toString(16);

    const newKb = renderExtensionsKeyboard(targetKey, mid, newMaskHex);
    await editMessageReplyMarkup(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, {
      inline_keyboard: newKb,
    });

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "Reset: All extensions enabled ✅");
    return new Response("OK", { status: 200 });
  }

  // 8. Action: Extensions Done / Save & Return to Dashboard
  if (cbData.startsWith("ext_done:")) {
    const [, targetKey, dashMsgId, maskHex] = cbData.split(":");
    const mid = parseInt(dashMsgId, 10) || cbMessageId;
    const session = (await getSession(env, cbChatId)) || {};

    session.targetKey = targetKey;
    session.dashMsgId = mid;
    session.maskHex = maskHex;
    await saveSession(env, cbChatId, session);

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "Extensions saved!");
    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      mid,
      renderDashboardText(session),
      { reply_markup: { inline_keyboard: renderDashboardButtons(session, mid) } }
    );
    return new Response("OK", { status: 200 });
  }

  // 9. Action: Ask for Input (IPA, Name, Bundle, Tweak)
  if (cbData.startsWith("ask:") || cbData.startsWith("input_ask:")) {
    const parts = cbData.split(":");
    const field = parts[1];
    const targetKey = parts[2];
    const dashMsgId = parts[3] || cbMessageId;
    const maskHex = parts[4] || "1fff";
    const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;
    const mid = parseInt(dashMsgId, 10) || cbMessageId;
    const session = (await getSession(env, cbChatId)) || {};

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, `Enter ${field.toUpperCase()}...`);

    let promptLabel = "";
    let placeholder = "";

    if (field === "ipa") {
      promptLabel = `🔗 **INPUT: DECRYPTED IPA URL**\n──────────────────────────────\nTarget: \`${target.name}\`\n\nPlease reply to this message with the direct download URL for the decrypted IPA file.`;
      placeholder = "Paste direct IPA download URL...";
    } else if (field === "name") {
      promptLabel = `🏷️ **INPUT: APP DISPLAY NAME**\n──────────────────────────────\nTarget: \`${target.name}\`\nCurrent: \`${session.name || target.defaultInputs?.display_name}\`\n\nPlease reply with your desired app name (e.g. \`My YouTube\`).`;
      placeholder = "e.g. My YouTube";
    } else if (field === "bundle") {
      promptLabel = `🆔 **INPUT: BUNDLE IDENTIFIER**\n──────────────────────────────\nTarget: \`${target.name}\`\nCurrent: \`${session.bundle || target.defaultInputs?.bundle_id}\`\n\nPlease reply with your desired bundle identifier (e.g. \`com.my.youtube\`).`;
      placeholder = "e.g. com.my.youtube";
    } else if (field === "tweak") {
      promptLabel = `💉 **INPUT: CUSTOM TWEAK URL**\n──────────────────────────────\nTarget: \`${target.name}\`\nCurrent: \`${session.tweak || "Default (built-in)"}\`\n\nPlease reply with a direct link to your custom deb/dylib, or type \`default\` to clear.`;
      placeholder = "Paste custom tweak .deb/.dylib URL or type default";
    }

    const metaTag = createPromptMetadataTag(field, targetKey, mid, maskHex);

    const sentPrompt = await sendMessage(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      `${metaTag}${promptLabel}\n\n👉 *Reply directly with your value (or type /cancel to abort):*`,
      {
        reply_to_message_id: mid,
        reply_markup: {
          force_reply: true,
          selective: true,
          input_field_placeholder: placeholder,
        },
      }
    );

    session.pendingPromptId = sentPrompt?.message_id || null;
    session.pendingField = field;
    session.targetKey = targetKey;
    session.dashMsgId = mid;
    session.maskHex = maskHex;
    await saveSession(env, cbChatId, session);

    return new Response("OK", { status: 200 });
  }

  // 10. Action: Trigger Build Now
  if (cbData.startsWith("trig:") || cbData.startsWith("input_trigger:")) {
    const parts = cbData.split(":");
    const targetKey = parts[1];
    const dashMsgId = parts[2] || cbMessageId;
    const maskHex = parts[3] || "1fff";
    const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;
    const mid = parseInt(dashMsgId, 10) || cbMessageId;
    const session = (await getSession(env, cbChatId)) || {};

    session.targetKey = targetKey;
    session.dashMsgId = mid;
    session.maskHex = maskHex;

    if (!session.ipa) {
      await answerCallbackQuery(
        env.TELEGRAM_BOT_TOKEN,
        queryId,
        "⚠️ Please set the IPA URL first by tapping [ 🔗 Set IPA URL ]!",
        true
      );
      return new Response("OK", { status: 200 });
    }

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "🚀 Dispatching GitHub Actions...");

    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      mid,
      `⏳ **DISPATCHING WORKFLOW...**\n──────────────────────────────\n` +
      `📦 **Target:** \`${target.name}\`\n` +
      `🛰️ **Repository:** \`${target.repo}\`\n` +
      `📄 **Workflow:** \`${target.workflow}\`\n` +
      `🔗 **IPA URL:** \`${session.ipa}\`\n\n` +
      `*Connecting to GitHub Actions API...*`
    );

    const inputs = compileWorkflowInputs(session, target);
    const result = await triggerWorkflowDispatch(env.GH_PAT, target.repo, target.workflow, inputs);

    if (result.success) {
      const startMs = Date.now();
      await clearSession(env, cbChatId);

      await new Promise((r) => setTimeout(r, 2500));
      const latestRun = await getLatestWorkflowRun(env.GH_PAT, target.repo);
      const runId = latestRun?.id || null;
      const runUrl = latestRun?.html_url || `https://github.com/${target.repo}/actions`;

      const trackCard = renderBuildTrackingCard(target, runId, "queued", 3, runUrl);
      await editMessageText(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, trackCard.text, {
        reply_markup: { inline_keyboard: trackCard.buttons },
      });

      await saveActiveBuild(env, {
        chatId: cbChatId,
        messageId: mid,
        targetKey: target.key,
        runId: runId,
        startMs: startMs,
      });

      const trackerPayload = {
        chat_id: cbChatId,
        message_id: mid,
        target_key: target.key,
        run_id: runId,
        start_time: startMs,
      };
      const repo = env.GH_REPO || "DexterDevKH/TelegramDropboxBot";
      await dispatchSyncPipeline(env.GH_PAT, repo, trackerPayload, "track_build");

      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(trackInitialWindow(env, cbChatId, mid, target, runId, startMs));
      }
    } else {
      const failCard = renderBuildFailureCard(target, result);
      await editMessageText(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, failCard);
    }

    return new Response("OK", { status: 200 });
  }

  // 11. Action: Check Build Status
  if (cbData.startsWith("chk_bld:")) {
    const parts = cbData.split(":");
    const targetKey = parts[1];
    let runId = parts[2] !== "0" && parts[2] !== "null" ? parts[2] : null;
    const mid = parseInt(parts[3], 10) || cbMessageId;
    const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, "Checking build status on GitHub...");

    if (!runId) {
      const latest = await getLatestWorkflowRun(env.GH_PAT, target.repo);
      if (latest) runId = latest.id;
    }

    if (runId) {
      const details = await getWorkflowRunDetails(env.GH_PAT, target.repo, runId);
      if (details) {
        const runUrl = details.html_url || `https://github.com/${target.repo}/actions/runs/${runId}`;
        const createdMs = details.created_at ? new Date(details.created_at).getTime() : Date.now();
        const elapsedSecs = Math.max(1, (Date.now() - createdMs) / 1000);

        if (details.status === "completed") {
          if (details.conclusion === "success") {
            const rel = await getLatestRelease(env.GH_PAT, target.repo);
            const card = renderBuildCompletedCard(target, rel, rel?.asset, elapsedSecs, runUrl);
            await editMessageText(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, card.text, {
              reply_markup: { inline_keyboard: card.buttons },
            });
          } else {
            const card = renderBuildFailedCard(target, runId, details.conclusion, elapsedSecs, runUrl);
            await editMessageText(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, card.text, {
              reply_markup: { inline_keyboard: card.buttons },
            });
          }
          return new Response("OK", { status: 200 });
        } else {
          const card = renderBuildTrackingCard(target, runId, details.status, elapsedSecs, runUrl);
          await editMessageText(env.TELEGRAM_BOT_TOKEN, cbChatId, mid, card.text, {
            reply_markup: { inline_keyboard: card.buttons },
          });
          return new Response("OK", { status: 200 });
        }
      }
    }

    return new Response("OK", { status: 200 });
  }

  // 12. Action: URL Build Target Selection
  if (cbData.startsWith("url_build:")) {
    const targetKey = cbData.split(":")[1];
    const target = getTarget(targetKey) || BUILD_TARGETS.dtkace;
    const session = (await getSession(env, cbChatId)) || {};
    const exts = getExtensions(targetKey);
    const defaultMask = (1 << exts.length) - 1;

    session.targetKey = targetKey;
    session.dashMsgId = cbMessageId;
    session.maskHex = defaultMask.toString(16);
    await saveSession(env, cbChatId, session);

    await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId, `Configuring ${target.name}`);

    await editMessageText(
      env.TELEGRAM_BOT_TOKEN,
      cbChatId,
      cbMessageId,
      renderDashboardText(session),
      { reply_markup: { inline_keyboard: renderDashboardButtons(session, cbMessageId) } }
    );
    return new Response("OK", { status: 200 });
  }

  await answerCallbackQuery(env.TELEGRAM_BOT_TOKEN, queryId);
  return new Response("OK", { status: 200 });
}

