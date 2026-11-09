"""
Unit Tests for URL Ingestion, GitHub Artifact Handling & Config Parsing
"""

import os
import unittest
import tempfile
import zipfile
from unittest.mock import patch

from src.config import load_config
from src.formatters import (
    parse_artifact_url,
    sanitize_filename,
    extract_single_file_from_zip,
)

class TestUrlIngestion(unittest.TestCase):

    def test_config_url_parameters(self):
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "abcdef0123456789",
            "DOWNLOAD_URL": "https://github.com/DexterDevKH/ytkace/actions/runs/42453711687/artifacts/13606462977",
            "IS_ARTIFACT": "true",
            "ARTIFACT_ID": "13606462977",
            "ARTIFACT_REPO": "DexterDevKH/ytkace",
            "FILE_NAME": "YTKACE-deb-rootless.zip",
            "FILE_SIZE": "2093699",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            cfg = load_config()
            self.assertEqual(cfg.download_url, "https://github.com/DexterDevKH/ytkace/actions/runs/42453711687/artifacts/13606462977")
            self.assertTrue(cfg.is_artifact)
            self.assertEqual(cfg.artifact_id, "13606462977")
            self.assertEqual(cfg.artifact_repo, "DexterDevKH/ytkace")
            self.assertEqual(cfg.file_name, "YTKACE-deb-rootless.zip")
            self.assertEqual(cfg.file_size, 2093699)

    def test_extract_single_file_from_zip(self):
        """Tests that a zip is unzipped and only the file inside is extracted."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "YTKACE-deb-rootless.zip")
            inner_name = "YTKACE-deb-rootless.deb"
            content = b"Simulated deb binary payload"

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(inner_name, content)

            res = extract_single_file_from_zip(zip_path, tmp_dir)
            self.assertIsNotNone(res)
            extracted_path, extracted_name, extracted_size, ext_dir = res

            self.assertEqual(extracted_name, "YTKACE-deb-rootless.deb")
            self.assertEqual(extracted_size, len(content))
            self.assertTrue(os.path.exists(extracted_path))
            with open(extracted_path, "rb") as f:
                self.assertEqual(f.read(), content)

    def test_extract_zip_with_subfolder_and_junk(self):
        """Tests that zip with subfolder and macOS junk extracts only the target file inside."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "archive.zip")

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("__MACOSX/._app.ipa", b"junk")
                zf.writestr(".DS_Store", b"junk")
                zf.writestr("packages/output/DexTube.ipa", b"IPA payload content")

            res = extract_single_file_from_zip(zip_path, tmp_dir)
            self.assertIsNotNone(res)
            extracted_path, extracted_name, extracted_size, _ = res

            self.assertEqual(extracted_name, "DexTube.ipa")
            self.assertEqual(extracted_size, len(b"IPA payload content"))

    def test_extract_zip_prioritizes_package(self):
        """Tests that zip with a package (.deb/.ipa) and text file extracts the package."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "bundle.zip")

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("README.md", b"documentation file")
                zf.writestr("tweak.deb", b"actual deb package")

            res = extract_single_file_from_zip(zip_path, tmp_dir)
            self.assertIsNotNone(res)
            extracted_path, extracted_name, _, _ = res
            self.assertEqual(extracted_name, "tweak.deb")

    def test_extract_empty_or_invalid_zip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_zip = os.path.join(tmp_dir, "empty.zip")
            with zipfile.ZipFile(empty_zip, "w"):
                pass
            self.assertIsNone(extract_single_file_from_zip(empty_zip, tmp_dir))
            self.assertIsNone(extract_single_file_from_zip("non_existent_file.zip", tmp_dir))

if __name__ == "__main__":
    unittest.main()

