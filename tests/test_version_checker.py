"""
Unit Tests for iOS Version Monitor & Alert Service
"""

import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from src.version_checker import (
    fetch_ios_app_info,
    check_all_ios_versions,
    format_version_alert_text,
    format_version_status_text,
    load_version_cache,
    save_version_cache,
    send_telegram_alert_http,
)

class TestVersionChecker(unittest.TestCase):

    def test_format_version_alert_text(self):
        info = {
            "trackName": "YouTube: Watch, Listen, Stream",
            "bundleId": "com.google.ios.youtube",
            "version": "21.46.3",
            "releaseDate": "2026-11-15",
            "releaseNotes": "Fixed playback issues and optimized startup.",
            "icon": "📺",
        }
        text = format_version_alert_text(info, prev_version="21.45.2")
        self.assertIn("NEW IOS VERSION DETECTED!", text)
        self.assertIn("YouTube", text)
        self.assertIn("21.46.3", text)
        self.assertIn("21.45.2", text)
        self.assertIn("com.google.ios.youtube", text)

    def test_format_version_status_text(self):
        apps = [
            {
                "trackName": "YouTube",
                "bundleId": "com.google.ios.youtube",
                "version": "21.46.3",
                "releaseDate": "2026-11-15",
                "target_keys": ["dtkace", "dtlite"],
                "icon": "📺",
            },
            {
                "trackName": "YouTube Music",
                "bundleId": "com.google.ios.youtubemusic",
                "version": "9.46",
                "releaseDate": "2026-11-15",
                "target_keys": ["dtmusic"],
                "icon": "🎵",
            },
        ]
        text = format_version_status_text(apps)
        self.assertIn("IOS APP STORE VERSION MONITOR", text)
        self.assertIn("com.google.ios.youtube", text)
        self.assertIn("com.google.ios.youtubemusic", text)
        self.assertIn("DTKACE", text)
        self.assertIn("DTMUSIC", text)

    @patch("urllib.request.urlopen")
    def test_fetch_ios_app_info_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "results": [{
                "trackName": "YouTube",
                "bundleId": "com.google.ios.youtube",
                "version": "21.46.3",
                "currentVersionReleaseDate": "2026-11-15T17:07:14Z",
                "releaseNotes": "Minor bug fixes",
                "trackViewUrl": "https://apps.apple.com/app/id544007664",
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        info = fetch_ios_app_info("com.google.ios.youtube")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "21.46.3")
        self.assertEqual(info["releaseDate"], "2026-11-15")
        self.assertEqual(info["bundleId"], "com.google.ios.youtube")

    def test_check_all_ios_versions_triggers_alert_on_change(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            cache_path = tmp.name

        try:
            # Seed initial cache with version 21.45.0 for YouTube
            save_version_cache({
                "com.google.ios.youtube": {"version": "21.45.0"},
                "com.google.ios.youtubemusic": {"version": "9.46"},
            }, cache_path)

            mock_yt = {
                "trackName": "YouTube",
                "bundleId": "com.google.ios.youtube",
                "version": "21.46.3",
                "releaseDate": "2026-11-15",
            }
            mock_ytm = {
                "trackName": "YouTube Music",
                "bundleId": "com.google.ios.youtubemusic",
                "version": "9.46",
                "releaseDate": "2026-11-15",
            }

            def mock_fetch(bundle_id):
                if bundle_id == "com.google.ios.youtube":
                    return dict(mock_yt)
                elif bundle_id == "com.google.ios.youtubemusic":
                    return dict(mock_ytm)
                return None

            with patch("src.version_checker.fetch_ios_app_info", side_effect=mock_fetch):
                apps, alerts = check_all_ios_versions(cache_path=cache_path)

            self.assertEqual(len(apps), 2)
            self.assertEqual(len(alerts), 1)
            app_info, prev_ver = alerts[0]
            self.assertEqual(app_info["bundleId"], "com.google.ios.youtube")
            self.assertEqual(app_info["version"], "21.46.3")
            self.assertEqual(prev_ver, "21.45.0")

            # Check that cache was updated
            updated_cache = load_version_cache(cache_path)
            self.assertEqual(updated_cache["com.google.ios.youtube"]["version"], "21.46.3")
        finally:
            if os.path.exists(cache_path):
                os.remove(cache_path)

    @patch("urllib.request.urlopen")
    def test_send_telegram_alert_http(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        ok = send_telegram_alert_http("mock_token", [12345, 67890], "Test alert message")
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 2)

if __name__ == "__main__":
    unittest.main()
