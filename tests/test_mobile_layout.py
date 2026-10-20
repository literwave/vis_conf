import asyncio
from contextlib import contextmanager
import json
import shutil
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import flet as ft

from app import main


@contextmanager
def _installed_table_agent():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        source = Path(__file__).resolve().parents[1] / "plugin_catalog" / "table_agent.py"
        shutil.copyfile(source, target / source.name)
        with patch("plugin_host.user_plugin_directory", return_value=target):
            yield


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
    def _find_labeled(root, label):
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

        found = walk(root, set())
        if found is None:
            raise AssertionError(f"找不到 {label}")
        return found

    @staticmethod
    def _click_labeled(root, label):
        MobileLayoutTests._find_labeled(root, label).on_click(None)

    @staticmethod
    def _conversation_dropdown(dialog):
        def walk(control, seen):
            if control is None or id(control) in seen:
                return None
            seen.add(id(control))
            if isinstance(control, ft.Dropdown) and control.options:
                return control
            for child in getattr(control, "controls", None) or []:
                found = walk(child, seen)
                if found is not None:
                    return found
            return walk(getattr(control, "content", None), seen)

        found = walk(dialog, set())
        if found is None:
            raise AssertionError("找不到对话列表")
        return found

    @staticmethod
    def _open_ai_agent(page):
        MobileLayoutTests._click_labeled(page, "插件")
        dialog = page.dialogs[-1]
        asyncio.run(MobileLayoutTests._find_labeled(dialog, "打开").on_click(None))

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

    def test_agent_runs_in_the_configuration_directory_and_reloads_the_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            table_path = root / 'Hero.tsv'
            table_path.write_text(
                'id\tname\ttype\trarity\tprice\n'
                'integer\tstring\tstring\tstring\tinteger\n'
                'both\tboth\tboth\tboth\tboth\n'
                '标识\t名称\t类型\t品质\t价格\n'
                '1001\t新手长剑\t武器\t普通\t10\n',
                encoding='utf-8',
            )
            page = FakePage(width=1260)
            page.platform = ft.PagePlatform.WINDOWS

            async def run_agent(workspace, prompt, **kwargs):
                self.assertEqual(Path(workspace), root)
                self.assertIn('缩短名称', prompt)
                self.assertNotIn('只返回一个 JSON', prompt)
                self.assertEqual(kwargs['mode'], 'agent')
                self.assertEqual(Path(kwargs['active_table']), table_path)
                table_path.write_text(
                    table_path.read_text(encoding='utf-8').replace('新手长剑', '长剑'),
                    encoding='utf-8',
                )
                return '已把名称改成短名。'

            with (
                _installed_table_agent(),
                patch(
                    'app_settings._load_app_settings',
                    return_value=(
                        {'configuration_directory': str(root)},
                        None,
                    ),
                ),
                patch(
                    'app_settings._app_settings_path',
                    return_value=root / 'settings.json',
                ),
                patch('ai_agent.run_cursor_workspace', new=run_agent),
            ):
                main(page)
                file_list = page.controls[0].controls[0].content.controls[6].content
                next(
                    control
                    for control in file_list.controls
                    if control.tooltip == str(table_path)
                ).on_click(None)
                self._open_ai_agent(page)
                dialog = page.dialogs[-1]
                prompt_input, send_button = dialog.content.controls[2].controls
                prompt_input.value = '缩短名称'
                asyncio.run(send_button.on_click(None))

            self.assertIn('长剑', table_path.read_text(encoding='utf-8'))
            self.assertNotIn('新手长剑', table_path.read_text(encoding='utf-8'))
            messages = dialog.content.controls[1]
            self.assertEqual(messages.controls[1].value, '已把名称改成短名。')
            self.assertEqual(messages.controls[2].value, '已重新读取当前配置表。')

    def test_agent_shows_the_reply_without_a_json_apply_step(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS

        async def run_agent(workspace, prompt, **kwargs):
            self.assertIn('看看这张表', prompt)
            return '这张表有一件武器。'

        with (
            _installed_table_agent(),
            patch('app_settings._load_app_settings', return_value=({'configuration_directory': 'D:/tables'}, None)),
            patch('app_settings._app_settings_path', return_value=Path(tempfile.gettempdir()) / 'vis-conf-agent-test-settings.json'),
            patch('ai_agent.run_cursor_workspace', new=run_agent),
        ):
            main(page)
            self._open_ai_agent(page)
            dialog = page.dialogs[-1]
            self.assertEqual(dialog.title.controls[0].controls[0].value, "AI Agent")
            prompt_input, send_button = dialog.content.controls[2].controls
            prompt_input.value = '看看这张表'
            asyncio.run(send_button.on_click(None))
            self.assertEqual(dialog.content.controls[1].controls[1].value, '这张表有一件武器。')
            self.assertFalse(any(getattr(action, 'content', None) == '应用到当前表' for action in dialog.actions))

    def test_agent_keeps_separate_conversations(self):
        page = FakePage(width=1260)
        page.platform = ft.PagePlatform.WINDOWS
        seen_history = []

        async def run_agent(workspace, prompt, **kwargs):
            seen_history.append(list(kwargs.get("history") or []))
            return f"回复：{prompt}"

        def message_text(column):
            values = []

            def walk(control, seen):
                if control is None or id(control) in seen:
                    return
                seen.add(id(control))
                value = getattr(control, "value", None)
                if isinstance(value, str):
                    values.append(value)
                for child in getattr(control, "controls", None) or []:
                    walk(child, seen)
                walk(getattr(control, "content", None), seen)

            walk(column, set())
            return values

        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            with (
                _installed_table_agent(),
                patch(
                    "app_settings._load_app_settings",
                    return_value=({"configuration_directory": "D:/tables"}, None),
                ),
                patch("app_settings._app_settings_path", return_value=settings_path),
                patch("ai_agent.run_cursor_workspace", new=run_agent),
            ):
                main(page)
                self._open_ai_agent(page)
                dialog = page.dialogs[-1]
                self.assertEqual(len(self._conversation_dropdown(dialog).options), 1)
                self._click_labeled(dialog, "新对话")
                self.assertEqual(len(self._conversation_dropdown(dialog).options), 2)
                prompt_input, send_button = dialog.content.controls[2].controls
                prompt_input.value = "第一段"
                asyncio.run(send_button.on_click(None))
                self._click_labeled(dialog, "新对话")
                self.assertEqual(dialog.content.controls[1].controls, [])
                prompt_input.value = "第二段"
                asyncio.run(send_button.on_click(None))
                self.assertEqual(seen_history[1], [])
                dropdown = self._conversation_dropdown(dialog)
                dropdown.value = next(option.key for option in dropdown.options if option.text == "第一段")
                dropdown.on_select(SimpleNamespace(control=dropdown))
                shown = message_text(dialog.content.controls[1])
                self.assertIn("第一段", shown)
                self.assertIn("回复：第一段", shown)
                self.assertNotIn("第二段", shown)

                page.pop_dialog()
                self._open_ai_agent(page)
                dialog = page.dialogs[-1]
                shown = message_text(dialog.content.controls[1])
                self.assertIn("回复：第一段", shown)
                self.assertNotIn("第二段", shown)
                dropdown = self._conversation_dropdown(dialog)
                dropdown.value = next(option.key for option in dropdown.options if option.text == "第二段")
                dropdown.on_select(SimpleNamespace(control=dropdown))
                shown = message_text(dialog.content.controls[1])
                self.assertIn("回复：第二段", shown)
                self.assertNotIn("第一段", shown)


if __name__ == "__main__":
    unittest.main()
