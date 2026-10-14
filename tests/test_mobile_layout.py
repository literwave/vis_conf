import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import flet as ft

from app import main


class FakePage:
    def __init__(self, width: int):
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.platform = ft.PagePlatform.ANDROID
        self.width = width
        self.height = 844
        self.window = SimpleNamespace()
        self.services = []
        self.controls = []
        self.dialogs = []
        self.web = False

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()


class FakeDirectoryPicker:
    def __init__(self):
        self.calls = []

    async def get_directory_path(self, **kwargs):
        self.calls.append(kwargs)
        return None


class MobileLayoutTests(unittest.TestCase):
    @staticmethod
    def _table_rows(page):
        table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
        table_area = table_card.content.controls[3]
        grid = table_area.controls[0].controls[0]
        return [
            control
            for control in grid.content.controls
            if isinstance(control, ft.DragTarget)
        ]

    @staticmethod
    def _row_ids(page):
        return [
            row.content.controls[1].content.value
            for row in MobileLayoutTests._table_rows(page)
        ]

    def test_phone_layout_hides_sidebar_and_recovers_on_wide_resize(self):
        page = FakePage(width=390)
        with patch("app._load_app_settings", return_value=({}, None)):
            main(page)

        workspace = page.controls[0]
        sidebar = workspace.controls[0]
        sidebar_content = sidebar.content
        content = workspace.controls[1].content
        content_body = content.controls[1]
        metrics_row, table_card = content_body.content.controls
        footer_row = table_card.content.controls[-1]
        page_size_select = footer_row.controls[0].controls[1]
        self.assertEqual(page_size_select.width, 104)
        self.assertEqual(page_size_select.menu_width, 112)
        self.assertFalse(sidebar.visible)
        self.assertIsNone(sidebar_content.scroll)
        configuration_file_list_container = sidebar_content.controls[6]
        bottom_spacer = sidebar_content.controls[7]
        self.assertEqual(configuration_file_list_container.height, 240)
        self.assertTrue(bottom_spacer.expand)
        self.assertEqual(
            sidebar_content.controls[-2].content.controls[1].value,
            "小提示",
        )
        self.assertEqual(
            sidebar_content.controls[-1].controls[1].controls[0].value,
            "游戏配置助手",
        )
        self.assertTrue(metrics_row.wrap)
        self.assertTrue(footer_row.wrap)
        configuration_actions = sidebar.content.controls[4]
        self.assertEqual(
            [control.tooltip for control in configuration_actions.controls[1:]],
            ["新建配置表", "删除当前配置表"],
        )

        page.width = 1024
        page.on_resize(None)
        self.assertTrue(sidebar.visible)
        self.assertEqual(configuration_file_list_container.height, 240)
        self.assertTrue(bottom_spacer.expand)
        self.assertFalse(metrics_row.wrap)
        self.assertFalse(footer_row.wrap)

        page.height = 620
        page.on_resize(None)
        self.assertEqual(configuration_file_list_container.height, 120)
        self.assertTrue(bottom_spacer.expand)
        self.assertEqual(
            sidebar_content.controls[-2].content.controls[1].value,
            "小提示",
        )

    def test_sidebar_can_create_and_confirm_delete_configuration_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_directory = Path(temporary_directory) / "configs"
            config_directory.mkdir()
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            with (
                patch(
                    "app._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(config_directory)},
                        None,
                    ),
                ),
                patch(
                    "app._app_settings_path",
                    return_value=Path(temporary_directory) / "settings.json",
                ),
            ):
                main(page)

            sidebar = page.controls[0].controls[0]
            configuration_actions = sidebar.content.controls[4]
            add_button, delete_button = configuration_actions.controls[1:]
            add_button.on_click(None)

            create_dialog = page.dialogs[-1]
            create_dialog.content.controls[1].value = "created_config"
            create_dialog.actions[1].on_click(None)

            configuration_path = config_directory / "created_config.tsv"
            self.assertTrue(configuration_path.is_file())
            self.assertFalse(delete_button.disabled)

            delete_button.on_click(None)
            confirmation_dialog = page.dialogs[-1]
            confirmation_dialog.actions[1].on_click(None)
            self.assertFalse(configuration_path.exists())

    def test_drag_copy_paste_and_undo_row_actions(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        with patch("app._load_app_settings", return_value=({}, None)):
            main(page)

        table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
        row_action_section = table_card.content.controls[1]
        row_toolbar = row_action_section.controls[0]
        selected_status, copy_button, paste_button, undo_button = (
            row_toolbar.controls
        )
        self.assertEqual(paste_button.content, "插入行")
        self.assertIn("副本插在目标行前", row_action_section.controls[1].value)
        self.assertEqual(
            selected_status.value,
            "点行号选择目标；Ctrl+C 复制，Ctrl+V 插入到目标行前；Ctrl+Z 撤销",
        )
        self.assertTrue(all(button.visible is not False for button in (
            copy_button,
            paste_button,
            undo_button,
        )))

        first_target = self._table_rows(page)[0]
        first_target.on_accept(SimpleNamespace(src=SimpleNamespace(data="1")))
        self.assertEqual(self._row_ids(page)[:2], ["1002", "1001"])

        undo_button.on_click(None)
        self.assertEqual(self._row_ids(page)[:2], ["1001", "1002"])

        first_row_number = self._table_rows(page)[0].content.controls[0].content
        first_row_number.on_click(None)
        self.assertEqual(selected_status.value, "目标：第 1 行")
        self.assertFalse(copy_button.disabled)
        copy_button.on_click(None)
        self.assertFalse(paste_button.disabled)
        second_row_number = self._table_rows(page)[1].content.controls[0].content
        second_row_number.on_click(None)
        self.assertEqual(selected_status.value, "目标：第 2 行")
        paste_button.on_click(None)
        self.assertEqual(self._row_ids(page)[:3], ["1001", "1001", "1002"])
        self.assertEqual(selected_status.value, "目标：第 2 行")

        undo_button.on_click(None)
        self.assertEqual(self._row_ids(page)[:3], ["1001", "1002", "1003"])

        self._table_rows(page)[0].content.controls[0].content.on_click(None)
        page.on_keyboard_event(
            ft.KeyboardEvent(
                name="keyboard",
                control=page,
                key="c",
                shift=False,
                ctrl=True,
                alt=False,
                meta=False,
            )
        )
        self._table_rows(page)[1].content.controls[0].content.on_click(None)
        page.on_keyboard_event(
            ft.KeyboardEvent(
                name="keyboard",
                control=page,
                key="v",
                shift=False,
                ctrl=True,
                alt=False,
                meta=False,
            )
        )
        self.assertEqual(self._row_ids(page)[:3], ["1001", "1001", "1002"])
        page.on_keyboard_event(
            ft.KeyboardEvent(
                name="keyboard",
                control=page,
                key="z",
                shift=False,
                ctrl=True,
                alt=False,
                meta=False,
            )
        )
        self.assertEqual(self._row_ids(page)[:3], ["1001", "1002", "1003"])

    def test_image_path_cell_renders_thumbnail_and_remains_editable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            configuration_directory = Path(__file__).resolve().parents[1] / "test"
            settings_path = Path(temporary_directory) / "settings.json"
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            with (
                patch(
                    "app._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(configuration_directory)},
                        None,
                    ),
                ),
                patch("app._app_settings_path", return_value=settings_path),
            ):
                main(page)

            sidebar = page.controls[0].controls[0]
            file_list = sidebar.content.controls[6].content
            test_table_path = configuration_directory / "test_config.tsv"
            test_table_item = next(
                control
                for control in file_list.controls
                if control.tooltip == str(test_table_path)
            )
            test_table_item.on_click(None)

            icon_cell = self._table_rows(page)[0].content.controls[3]
            self.assertIsInstance(icon_cell.content, ft.Image)
            self.assertEqual(icon_cell.content.width, 28)
            self.assertEqual(
                Path(icon_cell.content.src),
                (configuration_directory / "../assets/assistant-icon.png").resolve(),
            )

            icon_cell.on_click(None)
            dialog = page.dialogs[-1]
            notification_count = len(page.dialogs) - 1
            self.assertEqual(
                dialog.title.controls[0].value,
                "编辑「icon_path」",
            )
            self.assertEqual(
                dialog.content.value,
                "../assets/assistant-icon.png",
            )
            dialog.content.value = "unsaved-change.png"
            close_button = dialog.title.controls[2]
            self.assertEqual(close_button.tooltip, "关闭")
            close_button.on_click(None)
            self.assertEqual(len(page.dialogs), notification_count)

            icon_cell.on_click(None)
            self.assertEqual(
                page.dialogs[-1].content.value,
                "../assets/assistant-icon.png",
            )
            page.dialogs[-1].title.controls[2].on_click(None)

    def test_unavailable_saved_directory_is_preserved_without_blocking_startup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_directory = Path(temporary_directory) / "deleted-configs"
            settings_path = Path(temporary_directory) / "settings.json"
            original_settings = {
                "configuration_directory": str(missing_directory),
                "export_paths": {"backend": "backend-output"},
            }
            settings_path.write_text(
                json.dumps(original_settings),
                encoding="utf-8",
            )
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            with (
                patch(
                    "app._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(missing_directory)},
                        None,
                    ),
                ),
                patch("app._app_settings_path", return_value=settings_path),
            ):
                main(page)

            self.assertEqual(len(page.controls), 1)
            self.assertEqual(len(page.dialogs), 1)
            self.assertEqual(page.dialogs[0].bgcolor, "#344054")
            self.assertIn("原路径已保留", page.dialogs[0].content.value)
            unavailable_notice = (
                page.controls[0]
                .controls[0]
                .content.controls[6]
                .content.controls[0]
            )
            self.assertEqual(
                unavailable_notice.controls[1].value,
                "配置目录暂不可用",
            )
            self.assertEqual(
                unavailable_notice.controls[2].value,
                "检查磁盘或网络，或重新选择目录。",
            )
            self.assertEqual(
                unavailable_notice.controls[3].content,
                "更换目录",
            )
            self.assertIsNotNone(unavailable_notice.controls[3].on_click)
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                original_settings,
            )

    def test_reselecting_unavailable_directory_does_not_reuse_stale_picker_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_directory = Path(temporary_directory) / "deleted-configs"
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            picker = FakeDirectoryPicker()
            with (
                patch(
                    "app._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(missing_directory)},
                        None,
                    ),
                ),
                patch("app.ft.FilePicker", return_value=picker),
            ):
                main(page)

            unavailable_notice = (
                page.controls[0]
                .controls[0]
                .content.controls[6]
                .content.controls[0]
            )
            asyncio.run(unavailable_notice.controls[3].on_click(None))

            self.assertEqual(len(picker.calls), 1)
            self.assertIsNone(picker.calls[0]["initial_directory"])
            self.assertEqual(len(page.dialogs), 1)


if __name__ == "__main__":
    unittest.main()
