import os

import flet as ft

from app_settings import _app_settings_path, _load_app_settings
from config_directory import resolve_current_configuration_directory
from desktop_runtime import _prepare_flet_desktop_runtime, _rename_flet_cache_directory
from editor_session import main
from export_data import (
    build_export_archive,
    export_json_data,
    export_lua,
    prepare_export_files,
)
from table_file import (
    insert_row_copy,
    load_table,
    move_row,
    new_configuration_table_bytes,
)

__all__ = [
    "_app_settings_path",
    "_load_app_settings",
    "_prepare_flet_desktop_runtime",
    "_rename_flet_cache_directory",
    "build_export_archive",
    "export_json_data",
    "export_lua",
    "insert_row_copy",
    "load_table",
    "main",
    "move_row",
    "new_configuration_table_bytes",
    "prepare_export_files",
    "resolve_current_configuration_directory",
]


if __name__ == "__main__":
    if os.name == "nt":
        _prepare_flet_desktop_runtime()
    ft.run(main, view=ft.AppView.FLET_APP)
