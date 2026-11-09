"""
GitHub Actions Workflow Dispatcher & Release Inspector
"""

import logging
import asyncio
from typing import Tuple, Optional, Dict, Any, List, Callable
import requests
from src.formatters import parse_content_disposition_filename, extract_filename_from_url

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

    def get_artifact_metadata_sync(self, repo: str, artifact_id: Any) -> Optional[Dict[str, Any]]:
        """Synchronously fetches artifact metadata (name, size, expired) from GitHub REST API."""
        url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=15)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Failed to fetch artifact {artifact_id} from {repo}: HTTP {resp.status_code}")
        except Exception as exc:
            logger.error(f"Error fetching artifact metadata for {artifact_id}: {exc}")
        return None

    async def get_artifact_metadata(self, repo: str, artifact_id: Any) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_artifact_metadata_sync, repo, artifact_id)

    def get_run_artifacts_sync(self, repo: str, run_id: Any) -> List[Dict[str, Any]]:
        """Synchronously fetches all artifacts for a specific workflow run."""
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=15)
            if resp.status_code == 200:
                return resp.json().get("artifacts", [])
        except Exception as exc:
            logger.error(f"Error fetching run artifacts for run {run_id}: {exc}")
        return []

    async def get_run_artifacts(self, repo: str, run_id: Any) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_run_artifacts_sync, repo, run_id)

    def download_artifact_zip_sync(
        self,
        repo: str,
        artifact_id: Any,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Downloads the artifact zip archive from GitHub Actions.
        Follows the redirect safely without leaking Authorization header to storage servers.
        """
        if not self.pat:
            return False, "Missing GH_PAT. GitHub Actions artifacts require authentication."

        api_url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
        headers = self._get_headers()

        try:
            resp = requests.get(api_url, headers=headers, allow_redirects=False, timeout=20)
            if resp.status_code in [301, 302, 307, 308]:
                download_url = resp.headers.get("Location")
            elif resp.status_code == 200:
                download_url = api_url
            else:
                return False, f"GitHub API error HTTP {resp.status_code}: {resp.text[:200]}"

            if not download_url:
                return False, "Failed to obtain download URL from GitHub redirect."

            # Download binary blob (do not send GitHub Authorization token to Amazon/Azure storage)
            dl_headers = {"User-Agent": "Telegram-Dropbox-Sync"}
            if download_url == api_url:
                dl_headers = headers

            with requests.get(download_url, headers=dl_headers, stream=True, timeout=30) as dl_resp:
                if dl_resp.status_code != 200:
                    return False, f"Storage download failed: HTTP {dl_resp.status_code}"

                total_bytes = int(dl_resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 512 * 1024  # 512 KB

                with open(dest_path, "wb") as f:
                    for chunk in dl_resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_bytes)

            return True, ""
        except Exception as exc:
            return False, str(exc)

    async def download_artifact_zip(
        self,
        repo: str,
        artifact_id: Any,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, str]:
        return await asyncio.to_thread(
            self.download_artifact_zip_sync, repo, artifact_id, dest_path, progress_callback
        )

    def download_stream_url_sync(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, str, Optional[str], int]:
        """
        Downloads any arbitrary HTTP/HTTPS URL with streaming and progress reporting.
        Returns: (success, error_message, detected_filename, total_bytes)
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
            }
            with requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=30) as resp:
                if resp.status_code >= 400:
                    return False, f"HTTP error {resp.status_code}", None, 0

                detected_name = None
                cd = resp.headers.get("Content-Disposition", "")
                if cd:
                    detected_name = parse_content_disposition_filename(cd)

                if not detected_name:
                    detected_name = extract_filename_from_url(resp.url)

                total_bytes = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 512 * 1024  # 512 KB

                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_bytes)

                return True, "", detected_name, downloaded
        except Exception as exc:
            return False, str(exc), None, 0

    async def download_stream_url(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[bool, str, Optional[str], int]:
        return await asyncio.to_thread(
            self.download_stream_url_sync, url, dest_path, progress_callback
        )

