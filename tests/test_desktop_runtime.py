import tempfile
import unittest
from pathlib import Path

from app import _rename_flet_cache_directory


class FletDesktopCacheTests(unittest.TestCase):
    def test_cache_rename_retries_transient_permission_errors(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "flet-desktop-full-1.0.4"
            source = parent / f"{target.name}.temporary"
            source.mkdir()
            (source / "payload").write_text("ready", encoding="utf-8")
            attempts = 0
            delays = []

            def rename_with_transient_errors(source_path, target_path):
                nonlocal attempts
                attempts += 1
                if attempts < 7:
                    raise PermissionError("cache directory is temporarily locked")
                return Path.rename(source_path, target_path)

            result = _rename_flet_cache_directory(
                source,
                target,
                rename_with_transient_errors,
                delays.append,
            )

            self.assertEqual(result, target)
            self.assertEqual((target / "payload").read_text(encoding="utf-8"), "ready")
            self.assertEqual(attempts, 7)
            self.assertEqual(delays, [0.25, 0.5, 1.0, 2.0, 2.0, 2.0])

    def test_cache_rename_reports_persistent_permission_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "flet-desktop-full-1.0.4"
            source = parent / f"{target.name}.temporary"
            source.mkdir()
            attempts = 0
            delays = []

            def deny_rename(source_path, target_path):
                nonlocal attempts
                attempts += 1
                raise PermissionError("cache directory remains locked")

            with self.assertRaisesRegex(PermissionError, "remains locked"):
                _rename_flet_cache_directory(
                    source,
                    target,
                    deny_rename,
                    delays.append,
                )

            self.assertEqual(attempts, 7)
            self.assertEqual(delays, [0.25, 0.5, 1.0, 2.0, 2.0, 2.0])

    def test_cache_rename_uses_completed_cache_after_access_denied(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "flet-desktop-full-1.0.4"
            source = parent / f"{target.name}.temporary"
            source.mkdir()
            executable = target / "flet" / "flet.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")

            def deny_rename(source_path, target_path):
                raise PermissionError("destination already populated")

            result = _rename_flet_cache_directory(
                source,
                target,
                deny_rename,
                lambda _: self.fail("completed cache should not be retried"),
            )

            self.assertEqual(result, target)
            self.assertTrue(executable.is_file())
            self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
