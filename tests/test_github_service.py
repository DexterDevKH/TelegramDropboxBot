"""
Unit Tests for GitHubService Secret Management & Actions API
"""

import json
import base64
import unittest
from unittest.mock import patch, MagicMock

from nacl import public
from src.github_service import GitHubService

class TestGitHubService(unittest.TestCase):

    def setUp(self):
        self.service = GitHubService(pat="ghp_mock_token_12345")

    def test_missing_pat_returns_error(self):
        svc = GitHubService(pat="")
        success, code, msg = svc.update_repository_secret_sync("owner/repo", "TWEAK_URL", "https://tweak.deb")
        self.assertFalse(success)
        self.assertEqual(code, 401)
        self.assertIn("Missing GH_PAT", msg)

    @patch("requests.put")
    @patch("requests.get")
    def test_update_repository_secret_success(self, mock_get, mock_put):
        # Generate an authentic X25519 key pair for test verification
        private_key = public.PrivateKey.generate()
        public_key_b64 = base64.b64encode(bytes(private_key.public_key)).decode("utf-8")

        # Mock GET public-key response
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {
            "key_id": "key_id_99999",
            "key": public_key_b64,
        }
        mock_get.return_value = mock_get_resp

        # Mock PUT secret response
        mock_put_resp = MagicMock()
        mock_put_resp.status_code = 201
        mock_put.return_value = mock_put_resp

        secret_value = "https://dropbox.com/s/12345/ytkace.deb?dl=1"
        success, code, msg = self.service.update_repository_secret_sync(
            "DexterDevKH/DTKACE", "TWEAK_URL", secret_value
        )

        self.assertTrue(success)
        self.assertEqual(code, 201)

        # Verify GET was called for public-key
        mock_get.assert_called_once_with(
            "https://api.github.com/repos/DexterDevKH/DTKACE/actions/secrets/public-key",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Telegram-Dropbox-Dispatcher",
                "Authorization": "Bearer ghp_mock_token_12345",
                "Content-Type": "application/json",
            },
            timeout=15,
        )

        # Verify PUT was called with encrypted value and key_id
        mock_put.assert_called_once()
        put_call_args = mock_put.call_args
        put_url = put_call_args[0][0]
        self.assertEqual(put_url, "https://api.github.com/repos/DexterDevKH/DTKACE/actions/secrets/TWEAK_URL")

        put_body = put_call_args[1]["json"]
        self.assertEqual(put_body["key_id"], "key_id_99999")
        self.assertIn("encrypted_value", put_body)

        # Verify that the encrypted value can be decrypted by our private key (SealedBox)
        sealed_box = public.SealedBox(private_key)
        encrypted_bytes = base64.b64decode(put_body["encrypted_value"])
        decrypted_plaintext = sealed_box.decrypt(encrypted_bytes).decode("utf-8")
        self.assertEqual(decrypted_plaintext, secret_value)

if __name__ == "__main__":
    unittest.main()
