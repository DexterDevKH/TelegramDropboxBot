"""
Unit Tests for DropboxService FIFO Retention & Folder Routing
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.config import AppConfig
from src.dropbox_service import DropboxService
from dropbox.files import FileMetadata

class TestDropboxRetention(unittest.TestCase):

    def setUp(self):
        self.config = AppConfig(
            telegram_bot_token="123456:ABC-DEF",
            telegram_api_id=123456,
            telegram_api_hash="abcdef0123456789",
            dropbox_refresh_token="test_refresh_token",
            dropbox_app_key="test_key",
            dropbox_app_secret="test_secret",
            dropbox_ipa_folder="/IPA",
            dropbox_deb_folder="/DEB",
            max_files_in_folder=2,
            max_files_in_deb_folder=2,
            privacy_mode=False,
        )
        self.service = DropboxService(self.config)
        self.mock_client = MagicMock()
        self.service.client = self.mock_client

    def _create_mock_file(self, name: str, path_lower: str, timestamp_sec: int) -> FileMetadata:
        mock_file = MagicMock(spec=FileMetadata)
        mock_file.name = name
        mock_file.path_lower = path_lower
        mock_file.server_modified = datetime.fromtimestamp(timestamp_sec, tz=timezone.utc)
        return mock_file

    def test_enforce_retention_on_ipa_folder(self):
        """Tests that /IPA folder prunes oldest files when exceeding retention cap."""
        # 3 files in /IPA: cap is 2 -> oldest (file1) should be pruned
        f1 = self._create_mock_file("App1.ipa", "/ipa/app1.ipa", 1000)
        f2 = self._create_mock_file("App2.ipa", "/ipa/app2.ipa", 2000)
        f3 = self._create_mock_file("App3.ipa", "/ipa/app3.ipa", 3000)

        mock_result = MagicMock()
        mock_result.entries = [f2, f1, f3]  # unordered
        mock_result.has_more = False
        self.mock_client.files_list_folder.return_value = mock_result

        deleted = self.service.enforce_folder_retention("/IPA", max_files=2)
        self.assertEqual(deleted, ["App1.ipa"])
        self.mock_client.files_delete_v2.assert_called_once_with("/ipa/app1.ipa")

    def test_enforce_retention_on_deb_folder(self):
        """Tests that /DEB folder prunes oldest files when exceeding retention cap."""
        # 4 files in /DEB: cap is 2 -> oldest 2 (deb1, deb2) should be pruned
        d1 = self._create_mock_file("tweak1.deb", "/deb/tweak1.deb", 100)
        d2 = self._create_mock_file("tweak2.deb", "/deb/tweak2.deb", 200)
        d3 = self._create_mock_file("tweak3.deb", "/deb/tweak3.deb", 300)
        d4 = self._create_mock_file("tweak4.deb", "/deb/tweak4.deb", 400)

        mock_result = MagicMock()
        mock_result.entries = [d4, d2, d1, d3]
        mock_result.has_more = False
        self.mock_client.files_list_folder.return_value = mock_result

        deleted = self.service.enforce_folder_retention("/DEB", max_files=2)
        self.assertEqual(deleted, ["tweak1.deb", "tweak2.deb"])
        self.assertEqual(self.mock_client.files_delete_v2.call_count, 2)
        self.mock_client.files_delete_v2.assert_any_call("/deb/tweak1.deb")
        self.mock_client.files_delete_v2.assert_any_call("/deb/tweak2.deb")

    def test_enforce_all_retention_checks_both_vaults(self):
        """Tests that enforce_all_retention checks both /IPA and /DEB vaults."""
        # Setup entries for /IPA (3 files, prune 1)
        f1 = self._create_mock_file("App1.ipa", "/ipa/app1.ipa", 100)
        f2 = self._create_mock_file("App2.ipa", "/ipa/app2.ipa", 200)
        f3 = self._create_mock_file("App3.ipa", "/ipa/app3.ipa", 300)
        res_ipa = MagicMock(entries=[f1, f2, f3], has_more=False)

        # Setup entries for /DEB (3 files, prune 1)
        d1 = self._create_mock_file("tweak1.deb", "/deb/tweak1.deb", 10)
        d2 = self._create_mock_file("tweak2.deb", "/deb/tweak2.deb", 20)
        d3 = self._create_mock_file("tweak3.deb", "/deb/tweak3.deb", 30)
        res_deb = MagicMock(entries=[d1, d2, d3], has_more=False)

        def mock_list(path):
            if path == "/IPA":
                return res_ipa
            elif path == "/DEB":
                return res_deb
            return MagicMock(entries=[], has_more=False)

        self.mock_client.files_list_folder.side_effect = mock_list

        all_pruned = self.service.enforce_all_retention()
        self.assertIn("/IPA", all_pruned)
        self.assertEqual(all_pruned["/IPA"], ["App1.ipa"])
        self.assertIn("/DEB", all_pruned)
        self.assertEqual(all_pruned["/DEB"], ["tweak1.deb"])

    def test_retention_ignored_for_root_or_zero_cap(self):
        """Tests that root folder and zero/negative cap are protected from deletion."""
        self.assertEqual(self.service.enforce_folder_retention("/", max_files=2), [])
        self.assertEqual(self.service.enforce_folder_retention("", max_files=2), [])
        self.assertEqual(self.service.enforce_folder_retention("/DEB", max_files=0), [])
        self.mock_client.files_delete_v2.assert_not_called()

if __name__ == "__main__":
    unittest.main()

