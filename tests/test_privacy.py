"""
Unit Tests for Privacy & Masking Module
"""

import unittest
from src.privacy import mask_filename, mask_user_id

class TestPrivacy(unittest.TestCase):

    def test_mask_filename_enabled(self):
        self.assertEqual(mask_filename("secret.pdf", enabled=True), "se***t.pdf")
        self.assertEqual(mask_filename("a.b", enabled=True), "***.b")
        self.assertEqual(mask_filename("toolongfilenamehere.ipa", enabled=True), "to***e.ipa")

    def test_mask_filename_disabled(self):
        self.assertEqual(mask_filename("secret.pdf", enabled=False), "secret.pdf")

    def test_mask_user_id(self):
        self.assertEqual(mask_user_id(12345678, enabled=True), "12***")
        self.assertEqual(mask_user_id(12345678, enabled=False), "12345678")
        self.assertEqual(mask_user_id(5, enabled=True), "***")

if __name__ == "__main__":
    unittest.main()

