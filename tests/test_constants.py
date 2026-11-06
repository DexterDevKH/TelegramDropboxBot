"""
Unit Tests for Constants & Targets Catalog
"""

import unittest
from src.constants import BUILD_TARGETS, EXTENSIONS_CONFIG, get_target, get_extensions

class TestConstants(unittest.TestCase):

    def test_targets_exist(self):
        self.assertIn("dtkace", BUILD_TARGETS)
        self.assertIn("dtlite", BUILD_TARGETS)
        self.assertIn("dtmusic", BUILD_TARGETS)

    def test_get_target(self):
        dtkace = get_target("dtkace")
        self.assertIsNotNone(dtkace)
        self.assertEqual(dtkace["repo"], "DexterDevKH/DTKACE")
        self.assertIsNone(get_target("nonexistent"))

    def test_get_extensions(self):
        exts_dtkace = get_extensions("dtkace")
        self.assertEqual(len(exts_dtkace), 13)
        exts_dtlite = get_extensions("dtlite")
        self.assertEqual(len(exts_dtlite), 10)
        exts_dtmusic = get_extensions("dtmusic")
        self.assertEqual(len(exts_dtmusic), 0)

if __name__ == "__main__":
    unittest.main()

