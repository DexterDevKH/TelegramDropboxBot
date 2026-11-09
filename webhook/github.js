/**
 * GitHub Actions REST API Dispatcher & Workflow Tracker
 * Dispatches repository_dispatch, workflow_dispatch, and tracks live build progress & releases.
 */

const GITHUB_API_URL = "https://api.github.com";

function getHeaders(pat) {
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "Cloudflare-Worker-Telegram-Dispatcher",
    "Content-Type": "application/json",
  };
  if (pat) {
    headers.Authorization = `Bearer ${pat}`;
  }
  return headers;
}

/**
 * Triggers repository_dispatch to engage on-demand Telegram-to-Dropbox sync runner.
 */
export async function dispatchSyncPipeline(pat, repo, payload, eventType = "telegram_sync") {
  if (!pat) {
    return {
      success: false,
      status: 401,
      error: "Missing GH_PAT secret. Please configure GH_PAT in Cloudflare Worker settings.",
    };
  }

  const targetRepo = repo || "DexterDevKH/TelegramDropboxBot";
  const url = `${GITHUB_API_URL}/repos/${targetRepo}/dispatches`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: getHeaders(pat),
      body: JSON.stringify({
        event_type: eventType,
        client_payload: payload,
      }),
    });

    if (res.status === 204 || res.ok) {
      return { success: true, status: res.status };
    }

    const errBody = await res.text();
    return { success: false, status: res.status, error: errBody };
  } catch (err) {
    return { success: false, status: 500, error: err.message };
  }
}

/**
 * Triggers workflow_dispatch to launch iOS app compile/injection actions.
 */
export async function triggerWorkflowDispatch(pat, repo, workflowFile, inputs) {
  if (!pat) {
    return {
      success: false,
      status: 401,
      error: "Missing GH_PAT secret. Please configure GH_PAT in Cloudflare Worker settings.",
    };
  }

  const url = `${GITHUB_API_URL}/repos/${repo}/actions/workflows/${workflowFile}/dispatches`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: getHeaders(pat),
      body: JSON.stringify({
        ref: "main",
        inputs: inputs,
      }),
    });

    if (res.status === 204 || res.ok) {
      return { success: true, status: res.status };
    }

    const errBody = await res.text();
    return { success: false, status: res.status, error: errBody };
  } catch (err) {
    return { success: false, status: 500, error: err.message };
  }
}

/**
 * Retrieves the most recent workflow run for a repository.
 */
export async function getLatestWorkflowRun(pat, repo) {
  const url = `${GITHUB_API_URL}/repos/${repo}/actions/runs?per_page=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(pat),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.workflow_runs?.[0] || null;
  } catch (_) {
    return null;
  }
}

/**
 * Fetches current execution status and conclusion for a specific workflow run ID.
 */
export async function getWorkflowRunDetails(pat, repo, runId) {
  if (!runId) return null;
  const url = `${GITHUB_API_URL}/repos/${repo}/actions/runs/${runId}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(pat),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

/**
 * Fetches the latest release of a repository and discovers the compiled .ipa asset.
 */
export async function getLatestRelease(pat, repo) {
  const url = `${GITHUB_API_URL}/repos/${repo}/releases?per_page=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(pat),
    });
    if (!res.ok) return null;
    const releases = await res.json();
    if (!Array.isArray(releases) || releases.length === 0) return null;
    const rel = releases[0];

    // Find the primary .ipa asset
    const ipaAsset = (rel.assets || []).find((a) => a.name && a.name.toLowerCase().endsWith(".ipa"))
      || (rel.assets && rel.assets.length > 0 ? rel.assets[0] : null);

    return {
      tagName: rel.tag_name || "Latest",
      htmlUrl: rel.html_url || `https://github.com/${repo}/releases`,
      publishedAt: rel.published_at || null,
      asset: ipaAsset
        ? {
            name: ipaAsset.name,
            size: ipaAsset.size,
            downloadUrl: ipaAsset.browser_download_url,
          }
        : null,
    };
  } catch (_) {
    return null;
  }
}

/**
 * Fetches artifact details (name, size, expired status) from GitHub REST API.
 */
export async function getArtifactDetails(pat, repo, artifactId) {
  if (!artifactId) return null;
  const url = `${GITHUB_API_URL}/repos/${repo}/actions/artifacts/${artifactId}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(pat),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

/**
 * Fetches all artifacts for a specific workflow run.
 */
export async function getRunArtifacts(pat, repo, runId) {
  if (!runId) return [];
  const url = `${GITHUB_API_URL}/repos/${repo}/actions/runs/${runId}/artifacts`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(pat),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.artifacts) ? data.artifacts : [];
  } catch (_) {
    return [];
  }
}
