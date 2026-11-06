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

if __name__ == "__main__":
    unittest.main()
