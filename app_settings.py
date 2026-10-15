from pathlib import Path
import json
import os
import app_settings
from typing import Any


def _app_settings_path() -> Path:
    app_data = os.environ.get("APPDATA")
    settings_root = Path(app_data) if app_data else Path.home() / ".config"
    return settings_root / "GameConfigAssistant" / "settings.json"


def _load_app_settings() -> tuple[dict[str, Any], str | None]:
    settings_path = app_settings._app_settings_path()
    try:
        if not settings_path.exists():
            return ({}, None)
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return ({}, f"无法读取已保存的导出设置：{exc}")
    if not isinstance(settings, dict):
        return ({}, "已保存的导出设置格式无效，将使用默认设置。")
    return (settings, None)
