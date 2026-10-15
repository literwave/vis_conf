import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import _rename_flet_cache_directory
from desktop_runtime import _center_client_window, _centered_origin, _forward_client_stderr


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


class FletClientStderrTests(unittest.TestCase):
    def test_libpng_srgb_warning_is_dropped_but_other_errors_pass(self):
        async def forward():
            stream = asyncio.StreamReader()
            stream.feed_data(
                b"libpng warning: iCCP: known incorrect sRGB profile\r\n"
                b"real client error\r\n"
            )
            stream.feed_eof()
            output = io.BytesIO()
            await _forward_client_stderr(stream, output)
            return output.getvalue()

        self.assertEqual(asyncio.run(forward()), b"real client error\r\n")


class WindowCenterTests(unittest.TestCase):
    def test_origin_uses_the_work_area_center(self):
        self.assertEqual(_centered_origin(800, 600, 0, 0, 1920, 1080), (560, 240))
        self.assertEqual(_centered_origin(2000, 600, 100, 50, 2020, 1130), (100, 290))

    def test_window_is_placed_before_it_becomes_visible(self):
        placed = []
        visible = {"value": False}

        def find_window(pid):
            self.assertEqual(pid, 42)
            return 7

        def place_window(user32, wintypes, hwnd):
            placed.append(visible["value"])
            visible["value"] = True
            return True

        with patch("desktop_runtime._place_window_at_center", place_window):
            _center_client_window(
                42,
                find_window,
                lambda delay: None,
                timeout=1,
                is_visible=lambda hwnd: visible["value"],
            )

        self.assertEqual(placed, [False])


if __name__ == "__main__":
    unittest.main()
