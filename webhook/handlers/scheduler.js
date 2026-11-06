/**
 * Scheduled Cron & Background Build Tracker
 */

import { BUILD_TARGETS, getTarget } from "../targets.js";
import {
  saveActiveBuild,
  listActiveBuilds,
  deleteActiveBuild,
} from "../state.js";
import { editMessageText } from "../telegram.js";
import {
  getLatestWorkflowRun,
  getWorkflowRunDetails,
  getLatestRelease,
} from "../github.js";
import {
  renderBuildTrackingCard,
  renderBuildCompletedCard,
  renderBuildFailedCard,
} from "../ui.js";

/**
 * Initial 15-second tracking window inside Cloudflare Worker execution context.
 */
export async function trackInitialWindow(env, chatId, messageId, target, initialRunId, startMs) {
  let runId = initialRunId;
  const maxTicks = 3; // 3 ticks * 5s = 15s

  for (let i = 0; i < maxTicks; i++) {
    await new Promise((r) => setTimeout(r, 5000));
    try {
      if (!runId) {
        const latest = await getLatestWorkflowRun(env.GH_PAT, target.repo);
        if (latest) {
          runId = latest.id;
          await saveActiveBuild(env, {
            chatId,
            messageId,
            targetKey: target.key,
            runId,
            startMs,
          });
        }
      }
      if (!runId) continue;

      const details = await getWorkflowRunDetails(env.GH_PAT, target.repo, runId);
      if (!details) continue;

      const createdMs = details.created_at ? new Date(details.created_at).getTime() : startMs;
      const elapsedSecs = Math.max(1, (Date.now() - createdMs) / 1000);
      const runUrl = details.html_url || `https://github.com/${target.repo}/actions/runs/${runId}`;

      if (details.status === "completed") {
        if (details.conclusion === "success") {
          let rel = await getLatestRelease(env.GH_PAT, target.repo);
          if (!rel?.asset) {
            await new Promise((r) => setTimeout(r, 2000));
            rel = await getLatestRelease(env.GH_PAT, target.repo);
          }
          const card = renderBuildCompletedCard(target, rel, rel?.asset, elapsedSecs, runUrl);
          await editMessageText(env.TELEGRAM_BOT_TOKEN, chatId, messageId, card.text, {
            reply_markup: { inline_keyboard: card.buttons },
          });
        } else {
          const card = renderBuildFailedCard(target, runId, details.conclusion, elapsedSecs, runUrl);
          await editMessageText(env.TELEGRAM_BOT_TOKEN, chatId, messageId, card.text, {
            reply_markup: { inline_keyboard: card.buttons },
          });
        }
        await deleteActiveBuild(env, chatId, messageId);
        break;
      } else {
        const card = renderBuildTrackingCard(target, runId, details.status, elapsedSecs, runUrl);
        await editMessageText(env.TELEGRAM_BOT_TOKEN, chatId, messageId, card.text, {
          reply_markup: { inline_keyboard: card.buttons },
        });
      }
    } catch (_) {
      break;
    }
  }
}

/**
 * Cron scheduled job handler to check and auto-refresh active builds.
 */
export async function checkAllActiveBuilds(env) {
  try {
    const builds = await listActiveBuilds(env);
    if (!builds || builds.length === 0) return;

    for (const build of builds) {
      try {
        const target = getTarget(build.targetKey) || BUILD_TARGETS.dtkace;
        let runId = build.runId;
        if (!runId) {
          const latest = await getLatestWorkflowRun(env.GH_PAT, target.repo);
          if (latest) {
            runId = latest.id;
            build.runId = runId;
            await saveActiveBuild(env, build);
          }
        }
        if (!runId) continue;

        const details = await getWorkflowRunDetails(env.GH_PAT, target.repo, runId);
        if (!details) continue;

        const createdMs = details.created_at ? new Date(details.created_at).getTime() : (build.startMs || Date.now());
        const elapsedSecs = Math.max(1, (Date.now() - createdMs) / 1000);
        const runUrl = details.html_url || `https://github.com/${target.repo}/actions/runs/${runId}`;

        if (details.status === "completed") {
          if (details.conclusion === "success") {
            let rel = await getLatestRelease(env.GH_PAT, target.repo);
            if (!rel?.asset) {
              await new Promise((r) => setTimeout(r, 2000));
              rel = await getLatestRelease(env.GH_PAT, target.repo);
            }
            const card = renderBuildCompletedCard(target, rel, rel?.asset, elapsedSecs, runUrl);
            await editMessageText(env.TELEGRAM_BOT_TOKEN, build.chatId, build.messageId, card.text, {
              reply_markup: { inline_keyboard: card.buttons },
            });
          } else {
            const card = renderBuildFailedCard(target, runId, details.conclusion, elapsedSecs, runUrl);
            await editMessageText(env.TELEGRAM_BOT_TOKEN, build.chatId, build.messageId, card.text, {
              reply_markup: { inline_keyboard: card.buttons },
            });
          }
          await deleteActiveBuild(env, build.chatId, build.messageId);
        } else {
          if (elapsedSecs > 7200) {
            await deleteActiveBuild(env, build.chatId, build.messageId);
          } else {
            const card = renderBuildTrackingCard(target, runId, details.status, elapsedSecs, runUrl);
            await editMessageText(env.TELEGRAM_BOT_TOKEN, build.chatId, build.messageId, card.text, {
              reply_markup: { inline_keyboard: card.buttons },
            });
          }
        }
      } catch (err) {
        console.error(`[checkAllActiveBuilds Error for ${build.chatId}_${build.messageId}]:`, err);
      }
    }
  } catch (err) {
    console.error("[checkAllActiveBuilds Global Error]:", err);
  }
}

