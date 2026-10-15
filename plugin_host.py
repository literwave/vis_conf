"""星图插件。

可安装的插件放在 plugin_catalog。安装后复制到用户目录才会加载：

```text
%APPDATA%\\GameConfigAssistant\\plugins
```

每个插件是一个 .py 文件，提供 ``register(ctx) -> list[PluginAction]``。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class PluginAction:
    label: str
    on_click: Callable[..., Any]
    icon: Any = None
    tooltip: str = ""
    desktop_only: bool = True
    plugin_id: str = ""


class PluginContext:
    """传给插件的能力。插件不直接改星图界面，只通过这里调用。"""

    def __init__(self, plugin_id: str, host: Any):
        self.plugin_id = plugin_id
        self._host = host

    def notify(self, message: str, error: bool = False) -> None:
        self._host.notify(message, error)

    def show_text(self, title: str, text: str) -> None:
        self._host.show_text(title, text)

    def show_dialog(self, dialog: Any, on_close: Any = None) -> None:
        self._host.show_dialog(dialog, on_close)

    def listen_keyboard(self, handler: Any) -> None:
        self._host.listen_keyboard(handler)

    def stop_keyboard(self) -> None:
        self._host.stop_keyboard()

    def focus(self, control: Any) -> None:
        self._host.focus(control)

    def pop_dialog(self) -> None:
        self._host.pop_dialog()

    def update(self) -> None:
        self._host.update()

    def dialog_width(self, preferred: int) -> int:
        return self._host.dialog_width(preferred)

    def dialog_height(self, preferred: int, margin: int = 80) -> int:
        return self._host.dialog_height(preferred, margin)

    async def pick_directory(
        self, title: str, initial: str | None = None
    ) -> str | None:
        return await self._host.pick_directory(title, initial)

    def configuration_directory(self) -> str | None:
        return self._host.configuration_directory()

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._host.get_setting(self.plugin_id, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._host.set_setting(self.plugin_id, key, value)

    @property
    def app_directory(self) -> Path:
        return self._host.app_directory


def _runtime_directory(name: str) -> Path:
    candidates = [Path(__file__).resolve().parent / name]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.append(executable_dir / "_internal" / name)
        candidates.append(executable_dir / name)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def catalog_directory() -> Path:
    return _runtime_directory("plugin_catalog")


def user_plugin_directory() -> Path:
    app_data = os.environ.get("APPDATA")
    settings_root = Path(app_data) if app_data else Path.home() / ".config"
    return settings_root / "GameConfigAssistant" / "plugins"


def iter_plugin_files(directories: list[Path] | None = None) -> list[Path]:
    if directories is None:
        directories = [user_plugin_directory()]
    ordered: list[Path] = []
    index: dict[str, int] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_") or path.name == "__init__.py":
                continue
            if path.stem in index:
                ordered[index[path.stem]] = path
            else:
                index[path.stem] = len(ordered)
                ordered.append(path)
    return ordered


def load_plugins(
    host: Any, directories: list[Path] | None = None
) -> tuple[list[PluginAction], list[str]]:
    actions: list[PluginAction] = []
    errors: list[str] = []
    for path in iter_plugin_files(directories):
        try:
            module = _load_plugin_module(path)
            register = getattr(module, "register", None)
            if not callable(register):
                continue
            registered = register(PluginContext(path.stem, host)) or []
            for action in registered:
                action.plugin_id = path.stem
            actions.extend(registered)
        except Exception as exc:
            errors.append(f"{path.name}：{exc}")
    return actions, errors


def _load_plugin_module(path: Path):
    module_name = f"vis_conf_plugin_{path.stem}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件 {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class PluginPackage:
    plugin_id: str
    title: str
    description: str
    installed: bool
    outdated: bool = False


def read_plugin_metadata(path: Path) -> tuple[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return path.stem, ""
    title = path.stem
    description = (ast.get_docstring(tree) or "").strip().splitlines()
    summary = description[0] if description else ""
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "PLUGIN_TITLE":
                title = node.value.value
            elif target.id == "PLUGIN_DESCRIPTION":
                summary = node.value.value
    return title, summary


def list_plugin_packages(
    catalog: Path | None = None, installed: Path | None = None
) -> list[PluginPackage]:
    catalog_dir = catalog if catalog is not None else catalog_directory()
    installed_dir = installed if installed is not None else user_plugin_directory()
    installed_paths = {path.stem: path for path in iter_plugin_files([installed_dir])}
    packages: list[PluginPackage] = []
    seen: set[str] = set()
    if catalog_dir.is_dir():
        for path in sorted(catalog_dir.glob("*.py")):
            if path.name.startswith("_") or path.name == "__init__.py":
                continue
            title, description = read_plugin_metadata(path)
            installed_path = installed_paths.get(path.stem)
            outdated = False
            if installed_path is not None:
                try:
                    outdated = installed_path.read_bytes() != path.read_bytes()
                except OSError:
                    outdated = True
            packages.append(
                PluginPackage(
                    path.stem,
                    title,
                    description,
                    installed_path is not None,
                    outdated,
                )
            )
            seen.add(path.stem)
    for path in iter_plugin_files([installed_dir]):
        if path.stem in seen:
            continue
        title, description = read_plugin_metadata(path)
        packages.append(PluginPackage(path.stem, title, description, True))
    return packages


def install_plugin(
    plugin_id: str,
    catalog: Path | None = None,
    destination: Path | None = None,
) -> Path:
    source = (catalog if catalog is not None else catalog_directory()) / f"{plugin_id}.py"
    if not source.is_file():
        raise FileNotFoundError(f"找不到插件 {plugin_id}")
    target_dir = destination if destination is not None else user_plugin_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copyfile(source, target)
    return target


def uninstall_plugin(plugin_id: str, destination: Path | None = None) -> None:
    target_dir = destination if destination is not None else user_plugin_directory()
    target = target_dir / f"{plugin_id}.py"
    if target.is_file():
        target.unlink()
