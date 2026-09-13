import os
import tempfile
import unittest

import main
from main import QuickCleanupWorker, format_size


class QuickCleanupRootTests(unittest.TestCase):
    def setUp(self):
        self.worker = QuickCleanupWorker()
        self.worker.allowed_roots = (
            r"c:\users\alex\appdata\local\temp",
            r"c:\users\alex\appdata\local\google\chrome\user data\default\cache",
            r"c:\windows\temp",
        )

    def test_temp_file_under_cache_root_is_candidate(self):
        path = (
            r"c:\users\alex\appdata\local\google\chrome\user data\default\cache\f_000001"
        )
        self.assertTrue(self.worker._is_safe_candidate(path))

    def test_extension_file_in_temp_root_is_candidate(self):
        path = r"c:\users\alex\appdata\local\temp\tmp_xyz.tmp"
        self.assertTrue(self.worker._is_safe_candidate(path))

    def test_executable_in_cache_root_is_blocked(self):
        path = (
            r"c:\users\alex\appdata\local\google\chrome\user data\default\cache\setup.exe"
        )
        self.assertFalse(self.worker._is_safe_candidate(path))

    def test_system32_path_is_blocked(self):
        path = r"c:\users\alex\appdata\local\microsoft\system32\cache\evil.dll"
        self.worker.allowed_roots = (r"c:\users\alex\appdata\local\microsoft",)
        self.assertFalse(self.worker._is_safe_candidate(path))

    def test_outside_roots_is_blocked(self):
        path = r"c:\users\alex\documents\project\notes.txt"
        self.assertFalse(self.worker._is_safe_candidate(path))

    def test_plain_txt_in_cache_root_is_candidate(self):
        path = (
            r"c:\users\alex\appdata\local\google\chrome\user data\default\cache\index"
        )
        self.assertTrue(self.worker._is_safe_candidate(path))

    def test_javascript_in_cache_root_is_blocked(self):
        path = (
            r"c:\users\alex\appdata\local\google\chrome\user data\default\cache\inject.js"
        )
        self.assertFalse(self.worker._is_safe_candidate(path))


class QuickCleanupDiscoveryTests(unittest.TestCase):
    def test_add_root_deduplicates_and_requires_dir(self):
        worker = QuickCleanupWorker()
        with tempfile.TemporaryDirectory() as base:
            roots = []
            seen = set()
            worker._add_root(roots, seen, base)
            worker._add_root(roots, seen, base)
            self.assertEqual(len(roots), 1)
            worker._add_root(roots, seen, os.path.join(base, "missing"))
            self.assertEqual(len(roots), 1)

    def test_discovery_finds_cache_folder_names(self):
        worker = QuickCleanupWorker()
        with tempfile.TemporaryDirectory() as base:

            def touch(rel):
                path = os.path.join(base, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as fh:
                    fh.write("x")

            touch(os.path.join("Browser", "profile", "Cache", "f_1"))
            touch(os.path.join("Browser", "profile", "Code Cache", "js", "f_1"))
            touch(os.path.join("App", "GPUCache", "data_0"))
            touch(os.path.join("App", "Crashpad", "reports", "dump.dmp"))
            touch(os.path.join("App", "templates", "not-a-cache.txt"))

            roots = []
            seen = set()
            worker._discover_cache_roots(base, roots, seen)

            found = {r.lower() for r in roots}
            self.assertTrue(any(r.endswith(os.sep + "cache") for r in found))
            self.assertTrue(any("code cache" in r for r in found))
            self.assertTrue(any("gpucache" in r for r in found))
            self.assertTrue(any("crashpad" in r for r in found))
            # "templates" must never be treated as a temp/cache root.
            self.assertFalse(any("templates" in r for r in found))

    def test_discovery_prunes_known_bulk_dirs(self):
        worker = QuickCleanupWorker()
        with tempfile.TemporaryDirectory() as base:
            # These are no longer pruned (they contain caches the full
            # scanner classifies as Temporary).  The test verifies the
            # truly-pruned dirs are still excluded.
            for dname in ("pnpm", "Programs", "Packages",
                          "isolatedstorage", "VirtualStore"):
                os.makedirs(os.path.join(base, dname, "inner"), exist_ok=True)
            os.makedirs(os.path.join(base, "Google", "Cache"), exist_ok=True)

            roots = []
            seen = set()
            worker._discover_cache_roots(base, roots, seen)

            found = " ".join(r.lower() for r in roots)
            self.assertIn("google", found)
            # "packages"/"pnpm"/"programs" are now traversed but have no
            # cache-named subdirs, so they do not appear as roots.
            for dname in ("packages", "pnpm", "programs"):
                self.assertNotIn(dname + os.sep, found)
            # Truly pruned dirs must never appear as roots.
            for dname in ("isolatedstorage", "virtualstore"):
                self.assertNotIn(dname + os.sep, found)


class FormatSizeTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(512), "512 B")

    def test_kib(self):
        self.assertEqual(format_size(2048), "2.0 KB")

    def test_mib(self):
        self.assertEqual(format_size(3 * 1024 * 1024), "3.0 MB")

    def test_gib(self):
        self.assertEqual(format_size(2 * 1024 * 1024 * 1024), "2.0 GB")


class QuickCleanupNameMatcherTests(unittest.TestCase):
    def test_cache_prefix_names_are_roots(self):
        for name in ("cache", "Cache_Data", "cachestorage", "caches",
                     "cachedata", "cacheddata"):
            self.assertTrue(
                QuickCleanupWorker._is_cache_root_name(name),
                name,
            )

    def test_temp_prefix_names_are_roots(self):
        for name in ("temp", "TempData", "temporary"):
            self.assertTrue(
                QuickCleanupWorker._is_cache_root_name(name),
                name,
            )
        self.assertTrue(QuickCleanupWorker._is_cache_root_name("tmp"))

    def test_templates_never_a_root(self):
        for name in ("templates", "Template", "template", "Template_2"):
            self.assertFalse(
                QuickCleanupWorker._is_cache_root_name(name),
                name,
            )

    def test_specific_cache_markers_are_roots(self):
        for name in ("code cache", "Code Cache_2", "shadercache",
                     "shader cache", "crashdumps", "crashdump", "crashpad",
                     "gpucache", "gputemp", "webcache", "webdata",
                     ".cache"):
            self.assertTrue(
                QuickCleanupWorker._is_cache_root_name(name),
                name,
            )

    def test_personal_or_system_names_are_not_roots(self):
        for name in ("documents", "pictures", "downloads", "projects",
                     "node_modules", "winsxs", "system32", "windows",
                     "program files"):
            self.assertFalse(
                QuickCleanupWorker._is_cache_root_name(name),
                name,
            )

    def test_skip_temp_is_conservative(self):
        self.assertFalse(
            QuickCleanupWorker._is_cache_root_name("temp", skip_temp=True)
        )
        self.assertFalse(
            QuickCleanupWorker._is_cache_root_name("tmp", skip_temp=True)
        )
        self.assertTrue(
            QuickCleanupWorker._is_cache_root_name("cache", skip_temp=True)
        )


if __name__ == "__main__":
    unittest.main()