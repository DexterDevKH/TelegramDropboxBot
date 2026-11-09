"""
Unit Tests for Metric, Time, URL & Bitmask Formatters
"""

import unittest
import time
from src.formatters import (
    format_size,
    format_eta,
    render_progress_bar,
    sanitize_filename,
    normalize_url,
    encode_bitmask,
    decode_bitmask,
    SpeedTracker,
    parse_artifact_url,
    parse_run_url,
    parse_content_disposition_filename,
    extract_filename_from_url,
    resolve_dropbox_destination,
)

class TestFormatters(unittest.TestCase):

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(500), "500.00 B")
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1048576), "1.00 MB")
        self.assertEqual(format_size(1073741824), "1.00 GB")

    def test_format_eta(self):
        self.assertEqual(format_eta(0), "0s")
        self.assertEqual(format_eta(45), "45s")
        self.assertEqual(format_eta(65), "1m 5s")
        self.assertEqual(format_eta(3665), "1h 1m")
        self.assertEqual(format_eta(-5), "Calculating...")
        self.assertEqual(format_eta(100000), "Calculating...")

    def test_render_progress_bar(self):
        bar_0 = render_progress_bar(0.0)
        self.assertIn("[░░░░░░░░░░░░] 0.0%", bar_0)

        bar_50 = render_progress_bar(50.0)
        self.assertIn("50.0%", bar_50)
        self.assertIn("██████░░░░░░", bar_50)

        bar_100 = render_progress_bar(100.0)
        self.assertIn("[████████████] 100.0%", bar_100)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("clean_file.ipa"), "clean_file.ipa")
        self.assertEqual(sanitize_filename("bad:name*?.zip"), "badname.zip")
        self.assertTrue(sanitize_filename("").startswith("payload_"))

    def test_normalize_url(self):
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(
            normalize_url("https://www.dropbox.com/s/123/file.ipa?dl=0"),
            "https://www.dropbox.com/s/123/file.ipa?dl=1"
        )
        self.assertEqual(
            normalize_url("https://www.dropbox.com/s/123/file.ipa"),
            "https://www.dropbox.com/s/123/file.ipa?dl=1"
        )
        self.assertEqual(
            normalize_url("https://example.com/file.ipa"),
            "https://example.com/file.ipa"
        )

    def test_bitmask_codec(self):
        exts = [
            {"key": "a", "name": "Ext A"},
            {"key": "b", "name": "Ext B"},
            {"key": "c", "name": "Ext C"},
        ]
        # All enabled -> mask = 7 (0b111) -> "7"
        encoded_all = encode_bitmask([], exts)
        self.assertEqual(encoded_all, "7")
        decoded_all = decode_bitmask("7", exts)
        self.assertEqual(decoded_all["enabled_count"], 3)
        self.assertEqual(decoded_all["disabled"], [])
        self.assertTrue(decoded_all["is_enabled"]("a"))

        # Disable 'b' (index 1) -> mask = 5 (0b101) -> "5"
        encoded_b_disabled = encode_bitmask(["b"], exts)
        self.assertEqual(encoded_b_disabled, "5")
        decoded_b = decode_bitmask("5", exts)
        self.assertEqual(decoded_b["enabled_count"], 2)
        self.assertIn("b", decoded_b["disabled"])
        self.assertTrue(decoded_b["is_enabled"]("a"))
        self.assertFalse(decoded_b["is_enabled"]("b"))
        self.assertTrue(decoded_b["is_enabled"]("c"))

    def test_speed_tracker(self):
        tracker = SpeedTracker(alpha=0.5)
        # First tick initializes
        s0 = tracker.update(0)
        self.assertEqual(s0, 0.0)

        time.sleep(0.05)
        s1 = tracker.update(1024 * 1024)
        self.assertGreater(s1, 0.0)

    def test_parse_artifact_url(self):
        # User requested link
        target_url = "https://github.com/DexterDevKH/ytkace/actions/runs/42453711687/artifacts/13606462977"
        parsed = parse_artifact_url(target_url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["owner"], "DexterDevKH")
        self.assertEqual(parsed["repo"], "ytkace")
        self.assertEqual(parsed["repo_full_name"], "DexterDevKH/ytkace")
        self.assertEqual(parsed["artifact_id"], "13606462977")

        # Suite URL
        suite_url = "https://github.com/owner/repo/suites/98765/artifacts/54321"
        parsed_suite = parse_artifact_url(suite_url)
        self.assertIsNotNone(parsed_suite)
        self.assertEqual(parsed_suite["owner"], "owner")
        self.assertEqual(parsed_suite["repo"], "repo")
        self.assertEqual(parsed_suite["artifact_id"], "54321")

        # API URL
        api_url = "https://api.github.com/repos/owner/repo/actions/artifacts/112233"
        parsed_api = parse_artifact_url(api_url)
        self.assertIsNotNone(parsed_api)
        self.assertEqual(parsed_api["artifact_id"], "112233")

        # Non-artifact URL
        self.assertIsNone(parse_artifact_url("https://example.com/file.zip"))
        self.assertIsNone(parse_artifact_url(""))

    def test_parse_run_url(self):
        run_url = "https://github.com/DexterDevKH/ytkace/actions/runs/42453711687"
        parsed = parse_run_url(run_url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["owner"], "DexterDevKH")
        self.assertEqual(parsed["repo"], "ytkace")
        self.assertEqual(parsed["run_id"], "42453711687")

        self.assertIsNone(parse_run_url("https://github.com/DexterDevKH/ytkace"))

    def test_parse_content_disposition(self):
        self.assertEqual(
            parse_content_disposition_filename('attachment; filename="YouTube_v20.10.1.ipa"'),
            "YouTube_v20.10.1.ipa"
        )
        self.assertEqual(
            parse_content_disposition_filename("attachment; filename=tweak.deb"),
            "tweak.deb"
        )
        self.assertEqual(
            parse_content_disposition_filename("attachment; filename*=UTF-8''my%20app%20v1.ipa"),
            "my app v1.ipa"
        )
        self.assertIsNone(parse_content_disposition_filename(""))
        self.assertIsNone(parse_content_disposition_filename(None))

    def test_extract_filename_from_url(self):
        self.assertEqual(
            extract_filename_from_url("https://example.com/files/MyApp.ipa"),
            "MyApp.ipa"
        )
        self.assertEqual(
            extract_filename_from_url("https://example.com/downloads/my%20archive.zip?auth=xyz"),
            "my archive.zip"
        )
        self.assertEqual(
            extract_filename_from_url("https://example.com/"),
            "downloaded_file.bin"
        )

    def test_resolve_dropbox_destination(self):
        # .ipa file goes inside the configured folder
        dest_ipa, ret_ipa, vault_ipa = resolve_dropbox_destination("MyApp.ipa", "/IPA")
        self.assertEqual(dest_ipa, "/IPA/MyApp.ipa")
        self.assertEqual(ret_ipa, "/IPA")
        self.assertEqual(vault_ipa, "/IPA")

        # Uppercase .IPA also goes inside folder
        dest_ipa_upper, _, _ = resolve_dropbox_destination("YouTube.IPA", "/IPA")
        self.assertEqual(dest_ipa_upper, "/IPA/YouTube.IPA")

        # Non-ipa files (deb, pdf, mp4, etc.) go outside the folder to root /
        dest_deb, ret_deb, vault_deb = resolve_dropbox_destination("YTKACE-deb-rootless.deb", "/IPA")
        self.assertEqual(dest_deb, "/YTKACE-deb-rootless.deb")
        self.assertEqual(ret_deb, "")  # Root is protected from retention pruning
        self.assertEqual(vault_deb, "/ (Root)")

        dest_pdf, ret_pdf, vault_pdf = resolve_dropbox_destination("document.pdf", "/IPA")
        self.assertEqual(dest_pdf, "/document.pdf")
        self.assertEqual(ret_pdf, "")
        self.assertEqual(vault_pdf, "/ (Root)")

        dest_zip, ret_zip, vault_zip = resolve_dropbox_destination("archive.zip", "/IPA")
        self.assertEqual(dest_zip, "/archive.zip")
        self.assertEqual(ret_zip, "")

if __name__ == "__main__":
    unittest.main()
