"""
GitHub Actions Workflow Dispatcher & Release Inspector
"""

import logging
import asyncio
from typing import Tuple, Optional, Dict, Any
import requests

logger = logging.getLogger("SyncEngine.GitHub")

class GitHubService:
    """Interacts with GitHub REST API to trigger workflows and track runs/releases."""

    def __init__(self, pat: str):
        self.pat = pat

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Telegram-Dropbox-Dispatcher",
        }
        if self.pat:
            headers["Authorization"] = f"Bearer {self.pat}"
        return headers

    def trigger_workflow_dispatch_sync(
        self, repo: str, workflow_file: str, inputs: dict
    ) -> Tuple[bool, int, str]:
        """Synchronously triggers workflow_dispatch via GitHub REST API."""
        if not self.pat:
            return False, 401, "Missing GH_PAT secret. Configure GH_PAT in GitHub Secrets or environment."

        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        payload = {"ref": "main", "inputs": inputs}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code in [200, 204]:
                return True, resp.status_code, ""
            return False, resp.status_code, resp.text
        except Exception as exc:
            return False, 500, str(exc)

    async def trigger_workflow_dispatch(
        self, repo: str, workflow_file: str, inputs: dict
    ) -> Tuple[bool, int, str]:
        """Asynchronously triggers workflow_dispatch without blocking event loop."""
        return await asyncio.to_thread(self.trigger_workflow_dispatch_sync, repo, workflow_file, inputs)

    def get_latest_workflow_run_sync(self, repo: str) -> Optional[Dict[str, Any]]:
        """Synchronously retrieves the most recent workflow run for a repository."""
        url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=1"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                runs = resp.json().get("workflow_runs", [])
                return runs[0] if runs else None
        except Exception as exc:
            logger.debug(f"Error fetching latest workflow run: {exc}")
        return None

    async def get_latest_workflow_run(self, repo: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_latest_workflow_run_sync, repo)

    def get_workflow_run_details_sync(self, repo: str, run_id: int) -> Optional[Dict[str, Any]]:
        """Synchronously fetches status and details for a specific workflow run ID."""
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.debug(f"Error fetching run details for {run_id}: {exc}")
        return None

    async def get_workflow_run_details(self, repo: str, run_id: int) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_workflow_run_details_sync, repo, run_id)

    def get_latest_release_sync(self, repo: str) -> Optional[Dict[str, Any]]:
        """Synchronously fetches the latest release from a repository and identifies the .ipa asset."""
        url = f"https://api.github.com/repos/{repo}/releases?per_page=1"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                releases = resp.json()
                if isinstance(releases, list) and releases:
                    rel = releases[0]
                    ipa_asset = None
                    for asset in rel.get("assets", []):
                        if asset.get("name", "").lower().endswith(".ipa"):
                            ipa_asset = asset
                            break
                    if not ipa_asset and rel.get("assets"):
                        ipa_asset = rel["assets"][0]
                    return {
                        "tagName": rel.get("tag_name", "Latest"),
                        "htmlUrl": rel.get("html_url", f"https://github.com/{repo}/releases"),
                        "asset": ipa_asset,
                    }
        except Exception as exc:
            logger.debug(f"Error fetching latest release for {repo}: {exc}")
        return None

    async def get_latest_release(self, repo: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_latest_release_sync, repo)

