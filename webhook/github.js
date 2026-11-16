/**
 * GitHub Actions REST API Dispatcher & Workflow Tracker
 * Dispatches repository_dispatch, workflow_dispatch, and tracks live build progress & releases.
 */

import nacl from "tweetnacl";
import blake2b from "blake2b";

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

  // GitHub repository_dispatch client_payload strictly limits to at most 10 top-level properties.
  // Enforce a hard clamp so 422 errors never occur.
  let clientPayload = payload || {};
  const propKeys = Object.keys(clientPayload);
  if (propKeys.length > 10) {
    console.warn(`[dispatchSyncPipeline] client_payload has ${propKeys.length} keys, exceeding GitHub 10-key limit. Pruning excess keys.`);
    const truncated = {};
    for (const k of propKeys.slice(0, 10)) {
      truncated[k] = clientPayload[k];
    }
    clientPayload = truncated;
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: getHeaders(pat),
      body: JSON.stringify({
        event_type: eventType,
        client_payload: clientPayload,
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

/**
 * Encrypts a plaintext secret value using a repository's Base64 public key (Libsodium sealed box).
 */
export function sealSecret(secretValue, publicKeyBase64) {
  const messageBytes = new TextEncoder().encode(secretValue);
  const binaryDer = atob(publicKeyBase64);
  const publicKeyBytes = new Uint8Array(binaryDer.length);
  for (let i = 0; i < binaryDer.length; i++) {
    publicKeyBytes[i] = binaryDer.charCodeAt(i);
  }

  const ephem = nacl.box.keyPair();
  const hash = blake2b(24);
  hash.update(ephem.publicKey);
  hash.update(publicKeyBytes);
  const nonce = hash.digest();

  const ciphertext = nacl.box(messageBytes, nonce, publicKeyBytes, ephem.secretKey);
  const sealed = new Uint8Array(ephem.publicKey.length + ciphertext.length);
  sealed.set(ephem.publicKey);
  sealed.set(ciphertext, ephem.publicKey.length);

  let binary = "";
  for (let i = 0; i < sealed.length; i++) {
    binary += String.fromCharCode(sealed[i]);
  }
  return btoa(binary);
}

/**
 * Updates a GitHub Actions repository secret (e.g. TWEAK_URL) via REST API.
 */
export async function updateRepositorySecret(pat, repo, secretName, secretValue) {
  if (!pat) {
    return {
      success: false,
      status: 401,
      error: "Missing GH_PAT secret. Configure GH_PAT with 'repo' or 'secrets:write' permissions.",
    };
  }

  try {
    // 1. Fetch the repository's Actions public key
    const pubKeyUrl = `${GITHUB_API_URL}/repos/${repo}/actions/secrets/public-key`;
    const pubKeyRes = await fetch(pubKeyUrl, {
      method: "GET",
      headers: getHeaders(pat),
    });

    if (!pubKeyRes.ok) {
      const errText = await pubKeyRes.text();
      return {
        success: false,
        status: pubKeyRes.status,
        error: `Failed to fetch repo public key: ${errText}`,
      };
    }

    const { key, key_id: keyId } = await pubKeyRes.json();
    if (!key || !keyId) {
      return {
        success: false,
        status: 500,
        error: "Repository public key data is incomplete.",
      };
    }

    // 2. Encrypt the secret value using Libsodium sealed box
    const encryptedValue = sealSecret(secretValue, key);

    // 3. Put the encrypted secret into the repository
    const putUrl = `${GITHUB_API_URL}/repos/${repo}/actions/secrets/${secretName}`;
    const putRes = await fetch(putUrl, {
      method: "PUT",
      headers: getHeaders(pat),
      body: JSON.stringify({
        encrypted_value: encryptedValue,
        key_id: keyId,
      }),
    });

    if (putRes.status === 201 || putRes.status === 204 || putRes.ok) {
      return { success: true, status: putRes.status };
    }

    const putErr = await putRes.text();
    return {
      success: false,
      status: putRes.status,
      error: `Failed to update secret: ${putErr}`,
    };
  } catch (err) {
    return { success: false, status: 500, error: err.message };
  }
}

