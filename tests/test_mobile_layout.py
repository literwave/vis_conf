import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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
        grid = table_area.controls[0].controls[0].content.controls[0]
        return [
            control
            for control in grid.content.controls
            if isinstance(control, ft.DragTarget)
        ]

    @staticmethod
    def _click_labeled(root, label):
        def walk(control, seen):
            if control is None or id(control) in seen:
                return None
            seen.add(id(control))
            if getattr(control, "content", None) == label and callable(
                getattr(control, "on_click", None)
            ):
                return control
            for child in getattr(control, "controls", None) or []:
                found = walk(child, seen)
                if found is not None:
                    return found
            return walk(getattr(control, "content", None), seen)

        walk(root, set()).on_click(None)

    @staticmethod
    def _row_ids(page):
        return [
            row.content.controls[1].content.value
            for row in MobileLayoutTests._table_rows(page)
        ]

    def test_horizontal_scrollbar_stays_at_visible_table_bottom(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        with patch("app_settings._load_app_settings", return_value=({}, None)):
            main(page)

        table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
        table_area = table_card.content.controls[3]
        horizontal_row = table_area.controls[0]
        scroll_host = horizontal_row.controls[0]
        vertical_column = scroll_host.content
        grid = vertical_column.controls[0]
        self.assertIsInstance(horizontal_row.scroll, ft.Scrollbar)
        self.assertTrue(horizontal_row.scroll.interactive)
        self.assertTrue(horizontal_row.scroll.thumb_visibility)
        self.assertTrue(horizontal_row.scroll.track_visibility)
        self.assertEqual(vertical_column.scroll, ft.ScrollMode.AUTO)
        self.assertEqual(scroll_host.width, grid.width)
        self.assertGreater(scroll_host.width, 0)
        self.assertTrue(horizontal_row.expand)
        self.assertIsNone(horizontal_row.height)
        self.assertIsNone(scroll_host.height)
        self.assertIsNone(vertical_column.height)
        self.assertEqual(
            horizontal_row.vertical_alignment, ft.CrossAxisAlignment.STRETCH
        )
        self.assertIsNone(getattr(table_area, "scroll", None))

        page.on_resize(None)
        self.assertIs(table_area.controls[0], horizontal_row)

    def test_phone_layout_hides_sidebar_and_recovers_on_wide_resize(self):
        page = FakePage(width=390)
        with patch("app_settings._load_app_settings", return_value=({}, None)):
            main(page)

        workspace = page.controls[0]
        sidebar = workspace.controls[0]
        sidebar_content = sidebar.content
        content = workspace.controls[1].content
        content_body = content.controls[1]
        metrics_row, table_card = content_body.content.controls
        footer_row = table_card.content.controls[-1]
        page_size_select = footer_row.controls[0].controls[1]
        self.assertIsInstance(page_size_select, ft.PopupMenuButton)
        self.assertEqual(page_size_select.content.height, 34)
        self.assertEqual(page_size_select.content.border_radius, 17)
        page_size_select.items[1].on_click(None)
        self.assertEqual(
            page_size_select.content.content.controls[0].value, "20 条/页"
        )
        self.assertEqual(page.theme.font_family, "Microsoft YaHei UI")
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
                    "app_settings._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(config_directory)},
                        None,
                    ),
                ),
                patch(
                    "app_settings._app_settings_path",
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
        with patch("app_settings._load_app_settings", return_value=({}, None)):
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
                    "app_settings._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(configuration_directory)},
                        None,
                    ),
                ),
                patch("app_settings._app_settings_path", return_value=settings_path),
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

    def test_missing_saved_directory_uses_default_without_notice(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_directory = root / "deleted-configs"
            current_directory = root / "tsv"
            current_directory.mkdir()
            (current_directory / "Hero.tsv").write_text("id\n", encoding="utf-8")
            settings_path = root / "settings.json"
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
                    "app_settings._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(missing_directory)},
                        None,
                    ),
                ),
                patch("app_settings._app_settings_path", return_value=settings_path),
                patch(
                    "config_directory.resolve_current_configuration_directory",
                    return_value=current_directory,
                ),
            ):
                main(page)

            self.assertEqual(page.dialogs, [])
            file_list = page.controls[0].controls[0].content.controls[6].content
            self.assertTrue(
                any(
                    getattr(control, "tooltip", None) == str(current_directory / "Hero.tsv")
                    for control in file_list.controls
                )
            )
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                original_settings,
            )

    def test_directory_picker_starts_from_fallback_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_directory = root / "deleted-configs"
            current_directory = root / "tsv"
            current_directory.mkdir()
            (current_directory / "Hero.tsv").write_text("id\n", encoding="utf-8")
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            picker = FakeDirectoryPicker()
            with (
                patch(
                    "app_settings._load_app_settings",
                    return_value=(
                        {"configuration_directory": str(missing_directory)},
                        None,
                    ),
                ),
                patch("editor_session.ft.FilePicker", return_value=picker),
                patch(
                    "config_directory.resolve_current_configuration_directory",
                    return_value=current_directory,
                ),
            ):
                main(page)
                header_actions = page.controls[0].controls[1].content.controls[0].content.controls[2]
                export_button = next(
                    control
                    for control in header_actions.controls
                    if getattr(control, "content", None) == "导出设置"
                )
                export_button.on_click(None)
                choose_directory = page.dialogs[-1].content.controls[1].controls[1]
                asyncio.run(choose_directory.on_click(None))

            self.assertEqual(
                picker.calls[0]["initial_directory"],
                str(current_directory),
            )

    def test_resolve_current_directory_prefers_nearby_tsv_folder(self):
        from app import resolve_current_configuration_directory

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            launch_directory = root / "vis_conf"
            table_directory = root / "tsv"
            launch_directory.mkdir()
            table_directory.mkdir()
            (table_directory / "Item.tsv").write_text("id\n", encoding="utf-8")

            self.assertEqual(
                resolve_current_configuration_directory(launch_directory),
                table_directory.resolve(),
            )

    def test_resolve_current_directory_finds_other_tsv_folder_under_parent(self):
        from app import resolve_current_configuration_directory

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            launch_directory = root / "vis_conf"
            table_directory = root / "configs"
            launch_directory.mkdir()
            table_directory.mkdir()
            (table_directory / "Hero.tsv").write_text("id\n", encoding="utf-8")

            self.assertEqual(
                resolve_current_configuration_directory(launch_directory),
                table_directory.resolve(),
            )

    def test_unset_configuration_directory_uses_parent_tsv_search(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            table_directory = root / "tsv"
            table_directory.mkdir()
            (table_directory / "Hero.tsv").write_text("id\n", encoding="utf-8")
            settings_path = root / "settings.json"
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            with (
                patch("app_settings._load_app_settings", return_value=({}, None)),
                patch("app_settings._app_settings_path", return_value=settings_path),
                patch(
                    "config_directory.resolve_current_configuration_directory",
                    return_value=table_directory,
                ),
            ):
                main(page)

            self.assertFalse(settings_path.exists())
            file_list = page.controls[0].controls[0].content.controls[6].content
            self.assertTrue(
                any(
                    getattr(control, "tooltip", None) == str(table_directory / "Hero.tsv")
                    for control in file_list.controls
                )
            )

    def test_agent_apply_writes_open_tsv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            table_path = root / "Hero.tsv"
            table_path.write_text(
                "id\tname\ttype\trarity\tprice\n"
                "integer\tstring\tstring\tstring\tinteger\n"
                "both\tboth\tboth\tboth\tboth\n"
                "标识\t名称\t类型\t品质\t价格\n"
                "1001\t新手长剑\t武器\t普通\t10\n",
                encoding="utf-8",
            )
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS
            response = json.dumps(
                {
                    "message": "建议统一名称。",
                    "changes": [{"row": 1, "column": "name", "value": "长剑"}],
                },
                ensure_ascii=False,
            )
            with (
                patch(
                    "app_settings._load_app_settings",
                    return_value=(
                        {
                            "configuration_directory": str(root),
                            "agent": {"provider": "cursor", "cursor_mode": "agent"},
                        },
                        None,
                    ),
                ),
                patch(
                    "app_settings._app_settings_path",
                    return_value=root / "settings.json",
                ),
                patch(
                    "agent_ui.request_cursor_proposal",
                    new=AsyncMock(return_value=response),
                ),
            ):
                main(page)
                file_list = page.controls[0].controls[0].content.controls[6].content
                next(
                    control
                    for control in file_list.controls
                    if control.tooltip == str(table_path)
                ).on_click(None)
                header_actions = (
                    page.controls[0].controls[1].content.controls[0].content.controls[2]
                )
                agent_button = next(
                    control
                    for control in header_actions.controls
                    if getattr(control, "content", None) == "AI Agent"
                )
                agent_button.on_click(None)
                dialog = page.dialogs[-1]
                prompt_input, send_button = dialog.content.controls[3].controls
                prompt_input.value = "缩短名称"
                asyncio.run(send_button.on_click(None))

            unchanged = table_path.read_text(encoding="utf-8")
            self.assertIn("新手长剑", unchanged)
            next(
                action for action in dialog.actions if action.content == "应用到当前表"
            ).on_click(None)

            saved = table_path.read_text(encoding="utf-8")
            self.assertIn("长剑", saved)
            self.assertNotIn("新手长剑", saved)
            table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
            undo_button = table_card.content.controls[1].controls[0].controls[3]
            undo_button.on_click(None)
            restored = table_path.read_text(encoding="utf-8")
            self.assertIn("新手长剑", restored)

    def test_agent_previews_changes_and_applies_only_after_confirmation(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        response = json.dumps(
            {
                "message": "建议统一名称。",
                "changes": [
                    {"row": 1, "column": "name", "value": "长剑"},
                ],
            },
            ensure_ascii=False,
        )
        with (
            patch("app_settings._load_app_settings", return_value=({}, None)),
            patch(
                "agent_ui.request_cursor_proposal",
                new=AsyncMock(return_value=response),
            ),
        ):
            main(page)
            header_actions = page.controls[0].controls[1].content.controls[0].content.controls[2]
            agent_button = next(
                control
                for control in header_actions.controls
                if getattr(control, "content", None) == "AI Agent"
            )
            agent_button.on_click(None)

            dialog = page.dialogs[-1]
            messages_view = dialog.content.controls[1]
            pending_preview = dialog.content.controls[2]
            prompt_input, send_button = dialog.content.controls[3].controls
            self.assertFalse(dialog.scrollable)
            self.assertIsNone(dialog.content.scroll)
            self.assertIsNone(dialog.content.height)
            self.assertFalse(messages_view.expand)
            self.assertGreaterEqual(messages_view.height, 100)
            self.assertLessEqual(messages_view.height + 460, page.height)
            self.assertEqual(messages_view.scroll, ft.ScrollMode.AUTO)
            self.assertEqual(len(dialog.content.controls), 4)
            self.assertEqual(dialog.title.controls[-1].tooltip, "关闭")
            self.assertEqual(dialog.actions[0].content, "完成")
            dialog.actions[0].on_click(None)
            self.assertNotIn(dialog, page.dialogs)
            agent_button.on_click(None)
            dialog = page.dialogs[-1]
            messages_view = dialog.content.controls[1]
            pending_preview = dialog.content.controls[2]
            prompt_input, send_button = dialog.content.controls[3].controls
            self.assertTrue(prompt_input.shift_enter)
            self.assertIs(prompt_input.on_submit, send_button.on_click)
            prompt_input.value = "缩短名称"
            asyncio.run(send_button.on_click(None))

            self.assertEqual(
                messages_view.controls[-1].value,
                "建议统一名称。",
            )
            self.assertTrue(
                any(
                    isinstance(control, ft.Text)
                    and "新手长剑 → 长剑" in control.value
                    for control in pending_preview.controls
                )
            )
            self.assertEqual(self._table_rows(page)[0].content.controls[2].content.value, "新手长剑")
            self.assertFalse(
                any(action.content == "应用到当前表" for action in dialog.actions)
            )
            self.assertEqual(dialog.actions[0].content, "完成")

    def test_agent_adds_and_deletes_columns_after_confirmation(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        response = json.dumps(
            {
                "message": "调整列。",
                "changes": [{"row": 1, "column": "desc", "value": "新手武器"}],
                "column_additions": [
                    {
                        "name": "desc",
                        "type": "string",
                        "target": "both",
                        "annotation": "描述",
                        "default": "",
                    }
                ],
                "column_deletions": ["rarity"],
            },
            ensure_ascii=False,
        )

        def text_values(control, seen=None):
            if seen is None:
                seen = set()
            if control is None or id(control) in seen:
                return []
            seen.add(id(control))
            found = []
            if isinstance(control, ft.Text) and isinstance(control.value, str):
                found.append(control.value)
            for child in getattr(control, "controls", None) or []:
                found.extend(text_values(child, seen))
            found.extend(text_values(getattr(control, "content", None), seen))
            return found

        with (
            patch(
                "app_settings._load_app_settings",
                return_value=(
                    {"agent": {"provider": "cursor", "cursor_mode": "agent"}},
                    None,
                ),
            ),
            patch("agent_ui.request_cursor_proposal", new=AsyncMock(return_value=response)),
            patch(
                "app_settings._app_settings_path",
                return_value=Path(tempfile.mkdtemp()) / "settings.json",
            ),
        ):
            main(page)
            header_actions = page.controls[0].controls[1].content.controls[0].content.controls[2]
            agent_button = next(
                control
                for control in header_actions.controls
                if getattr(control, "content", None) == "AI Agent"
            )
            agent_button.on_click(None)
            dialog = page.dialogs[-1]
            pending_preview = dialog.content.controls[2]
            prompt_input, send_button = dialog.content.controls[3].controls
            prompt_input.value = "删掉品质并加描述"
            asyncio.run(send_button.on_click(None))

            preview_text = " ".join(text_values(pending_preview))
            self.assertIn("删除列 · rarity", preview_text)
            self.assertIn("新增列 · desc", preview_text)
            table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
            self.assertIn("rarity", text_values(table_card))
            self.assertNotIn("desc", text_values(table_card))

            next(
                action for action in dialog.actions if action.content == "应用到当前表"
            ).on_click(None)

        table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
        applied = text_values(table_card)
        self.assertNotIn("rarity", applied)
        self.assertIn("desc", applied)
        self.assertIn("新手武器", applied)
        undo_button = table_card.content.controls[1].controls[0].controls[3]
        undo_button.on_click(None)
        restored = text_values(table_card)
        self.assertIn("rarity", restored)
        self.assertNotIn("desc", restored)

    def test_title_close_drops_unapplied_preview(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        response = json.dumps(
            {
                "message": "已建议新增描述列。",
                "changes": [],
                "column_additions": [
                    {
                        "name": "desc",
                        "type": "字符串",
                        "target": "前后端",
                        "annotation": "描述",
                        "default": "",
                    }
                ],
                "column_deletions": [],
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch("app_settings._load_app_settings", return_value=({}, None)),
                patch("agent_ui.request_cursor_proposal", new=AsyncMock(return_value=response)),
                patch(
                    "app_settings._app_settings_path",
                    return_value=Path(temporary_directory) / "settings.json",
                ),
            ):
                main(page)
                header_actions = page.controls[0].controls[1].content.controls[0].content.controls[2]
                agent_button = next(
                    control
                    for control in header_actions.controls
                    if getattr(control, "content", None) == "AI Agent"
                )
                agent_button.on_click(None)
                dialog = page.dialogs[-1]
                prompt_input, send_button = dialog.content.controls[3].controls
                prompt_input.value = "加一列描述"
                asyncio.run(send_button.on_click(None))

                def text_values(control, seen=None):
                    if seen is None:
                        seen = set()
                    if control is None or id(control) in seen:
                        return []
                    seen.add(id(control))
                    found = []
                    if isinstance(control, ft.Text) and isinstance(control.value, str):
                        found.append(control.value)
                    for child in getattr(control, "controls", None) or []:
                        found.extend(text_values(child, seen))
                    found.extend(text_values(getattr(control, "content", None), seen))
                    return found

                table_card = page.controls[0].controls[1].content.controls[1].content.controls[1]
                next(action for action in dialog.actions if action.content == "完成").on_click(
                    None
                )
                self.assertNotIn(dialog, page.dialogs)
                self.assertNotIn("desc", text_values(table_card))


if __name__ == "__main__":
    unittest.main()
