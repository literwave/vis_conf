from pathlib import Path
import asyncio
import logging
import shutil
import sys
import threading
import time

logger = logging.getLogger(__name__)

_IGNORED_CLIENT_STDERR = (
    b"libpng warning: iCCP: known incorrect sRGB profile",
    b"Failed to update ui::AXTree",
)
_client_stderr_tasks = set()


async def _forward_client_stderr(stream, output=None):
    output = output or sys.stderr.buffer
    while True:
        line = await stream.readline()
        if not line:
            return
        if any(ignored in line for ignored in _IGNORED_CLIENT_STDERR):
            continue
        output.write(line)
        output.flush()


def _centered_origin(window_width, window_height, work_left, work_top, work_right, work_bottom):
    width = max(int(window_width), 0)
    height = max(int(window_height), 0)
    left = int(work_left) + max((int(work_right) - int(work_left) - width) // 2, 0)
    top = int(work_top) + max((int(work_bottom) - int(work_top) - height) // 2, 0)
    return left, top


def _center_client_window(pid, find_window, sleep, timeout=5.0, is_visible=None):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    if is_visible is None:
        is_visible = user32.IsWindowVisible
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = find_window(pid)
        if hwnd and _place_window_at_center(user32, wintypes, hwnd) and is_visible(hwnd):
            return
        sleep(0.005)


def _place_window_at_center(user32, wintypes, hwnd):
    import ctypes

    window = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(window)):
        return False
    width = window.right - window.left
    height = window.bottom - window.top
    if width <= 0 or height <= 0:
        return False
    work = wintypes.RECT()
    if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
        return False
    left, top = _centered_origin(
        width, height, work.left, work.top, work.right, work.bottom
    )
    if abs(window.left - left) <= 1 and abs(window.top - top) <= 1:
        return True
    user32.SetWindowPos(hwnd, 0, left, top, 0, 0, 0x0001 | 0x0004 | 0x0010)
    return True


def _start_center_client_window(pid):
    from flet_desktop.win_taskbar import _find_top_window

    threading.Thread(
        target=_center_client_window,
        args=(pid, _find_top_window, time.sleep),
        daemon=True,
    ).start()


def _install_flet_client_stderr_filter():
    import flet_desktop

    locate_client = getattr(flet_desktop, "__locate_and_unpack_flet_view")
    apply_taskbar_props = getattr(flet_desktop, "__apply_taskbar_props", None)

    async def open_flet_view_async(page_url, assets_dir, hidden):
        args, flet_env, pid_file = locate_client(page_url, assets_dir, hidden)
        process = await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            env=flet_env,
            stderr=asyncio.subprocess.PIPE,
        )
        _start_center_client_window(process.pid)
        task = asyncio.create_task(_forward_client_stderr(process.stderr))
        _client_stderr_tasks.add(task)
        task.add_done_callback(_client_stderr_tasks.discard)
        if apply_taskbar_props is not None:
            apply_taskbar_props(process.pid)
        return process, pid_file

    flet_desktop.open_flet_view_async = open_flet_view_async


def _rename_flet_cache_directory(source, target, original_rename, sleep=time.sleep):
    source = Path(source)
    target = Path(target)
    is_flet_cache_rename = (
        source.parent == target.parent
        and target.name.startswith("flet-desktop-")
        and source.name.startswith(f"{target.name}.")
    )
    if not is_flet_cache_rename:
        return original_rename(source, target)
    max_attempts = 7
    for attempt in range(max_attempts):
        try:
            return original_rename(source, target)
        except PermissionError:
            cached_client = target / "flet" / "flet.exe"
            if cached_client.is_file():
                shutil.rmtree(source, ignore_errors=True)
                logger.warning(
                    "Flet runtime cache already exists; using the completed cache at %s",
                    target,
                )
                return target
            if attempt == max_attempts - 1:
                raise
            delay = min(0.25 * 2**attempt, 2.0)
            logger.warning(
                "Flet runtime cache rename was denied; retrying in %.2f seconds", delay
            )
            sleep(delay)


def _prepare_flet_desktop_runtime():
    import flet_desktop

    original_rename = Path.rename
    Path.rename = lambda source, target: _rename_flet_cache_directory(
        source, target, original_rename
    )
    try:
        flet_desktop.ensure_client_cached()
    finally:
        Path.rename = original_rename
    _install_flet_client_stderr_filter()
