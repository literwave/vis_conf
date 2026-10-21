from pathlib import Path
import inspect
import flet as ft
import app_settings
from plugin_host import install_plugin, list_plugin_packages, load_plugins, uninstall_plugin
import config_directory
from agent_ui import create_agent_dialogs, load_agent_settings
from schema import (
    DATA_TYPES,
    EXPORT_TARGETS,
    PAGE_SIZES,
    SAMPLE_ANNOTATIONS,
    SAMPLE_COLUMNS,
    SAMPLE_ROWS,
    SAMPLE_TARGETS,
    SAMPLE_TYPES,
)
from table_file import _display_value, parse_data_value
from editor_dialogs import EditorDialogs
from editor_rows import EditorRows
from editor_columns import EditorColumns
from editor_grid import EditorGrid
from editor_files import EditorFiles
from editor_export import EditorExport


class Workspace(
    EditorDialogs, EditorRows, EditorColumns, EditorGrid, EditorFiles, EditorExport
):
    def __init__(self, page):
        self.page = page
        self.page.title = "星图 · 游戏配置导表工具"
        self.page.bgcolor = "#F5F7FB"
        self.page.padding = 0
        self.page.theme = ft.Theme(
            color_scheme_seed="#5B6CFF",
            font_family="Microsoft YaHei UI",
            popup_menu_theme=ft.PopupMenuTheme(
                color="#FFFFFF",
                shadow_color="#1018281A",
                label_text_style=ft.TextStyle(size=12, color="#344054"),
                elevation=3,
                shape=ft.RoundedRectangleBorder(
                    side=ft.BorderSide(1, "#EAECF0"), radius=10
                ),
                menu_padding=4,
            ),
        )
        self.mobile_platform = self.page.platform.is_mobile()
        if not self.mobile_platform:
            prepare_desktop_window(self.page)
        self.columns = SAMPLE_COLUMNS.copy()
        self.data_types = SAMPLE_TYPES.copy()
        self.targets = SAMPLE_TARGETS.copy()
        self.annotations = SAMPLE_ANNOTATIONS.copy()
        self.rows = [row.copy() for row in SAMPLE_ROWS]
        saved_settings, settings_load_error = app_settings._load_app_settings()
        self.agent_settings = load_agent_settings(saved_settings.get("agent"))
        self.agent_provider_labels = []
        saved_export_paths = saved_settings.get("export_paths", {})
        if not isinstance(saved_export_paths, dict):
            saved_export_paths = {}
        self.export_paths = {
            target: directory if isinstance(directory, str) and directory else None
            for target, directory in saved_export_paths.items()
            if target in {"backend", "frontend"}
        }
        self.export_paths.setdefault("backend", None)
        self.export_paths.setdefault("frontend", None)
        self.configuration_directory = saved_settings.get("configuration_directory")
        if (
            not isinstance(self.configuration_directory, str)
            or not self.configuration_directory
        ):
            self.configuration_directory = None
        if (
            self.configuration_directory is not None
            and not self.mobile_platform
            and not Path(self.configuration_directory).is_dir()
        ):
            self.configuration_directory = None
        if self.configuration_directory is None and (not self.mobile_platform):
            discovered = config_directory.resolve_current_configuration_directory()
            if config_directory.directory_contains_tsv(discovered):
                self.configuration_directory = str(discovered)
        self.ui_directory = saved_settings.get("ui_directory")
        if not isinstance(self.ui_directory, str) or not self.ui_directory:
            self.ui_directory = None
        if (
            self.ui_directory is not None
            and not self.mobile_platform
            and not Path(self.ui_directory).is_dir()
        ):
            self.ui_directory = None
        saved_plugin_settings = saved_settings.get("plugin_settings")
        self.plugin_settings = (
            saved_plugin_settings if isinstance(saved_plugin_settings, dict) else {}
        )
        self.plugin_errors: list[str] = []
        self.plugin_actions: list = []
        saved_backend_format = saved_settings.get("backend_format")
        saved_frontend_format = saved_settings.get("frontend_format")
        backend_format = (
            saved_backend_format
            if isinstance(saved_backend_format, str)
            and saved_backend_format in {"lua", "json"}
            else "lua"
        )
        frontend_format = (
            saved_frontend_format
            if isinstance(saved_frontend_format, str)
            and saved_frontend_format in {"lua", "json"}
            else "json"
        )
        saved_key_rules = saved_settings.get("key_rules", {})
        if not isinstance(saved_key_rules, dict):
            saved_key_rules = {}
        saved_table_keys = saved_key_rules.get("item_config.tsv", [])
        if not isinstance(saved_table_keys, list):
            saved_table_keys = []
        self.key_columns = (
            [column for column in self.columns if column in saved_table_keys]
            if "item_config.tsv" in saved_key_rules
            else ["id"] if "id" in self.columns else []
        )
        self.current_page = 0
        self.page_size = 10
        self.source_name = "item_config.tsv"
        self.active_table_path = None
        self.selected_row_index = None
        self.copied_row = None
        self.copied_row_table_key = None
        self.row_undo_history = {}
        self.row_copy_button = None
        self.row_paste_button = None
        self.row_undo_button = None
        self.mobile_configuration_paths = []
        self.mobile_file_bytes = {}
        self.modified_table_paths = set()
        self.table_states = {}
        self.configuration_delete_button = None
        self.key_rules_by_table = {
            name: [key for key in keys if isinstance(key, str)]
            for name, keys in saved_key_rules.items()
            if isinstance(name, str) and isinstance(keys, list)
        }
        self.picker = ft.FilePicker()
        self.page.services.append(self.picker)
        self.configuration_directory_field = ft.TextField(
            label="配置文件目录",
            value=self.configuration_directory or "尚未选择",
            hint_text="选择目录，或直接粘贴路径",
            width=410,
        )
        self.configuration_table_count = ft.Text(
            "请先选择 TSV 配置文件" if self.mobile_platform else "尚未选择配置目录"
        )
        self.configuration_count_metric = ft.Text("—")
        configuration_section_title = ft.Text(
            "TSV 配置表",
            size=11,
            color="#98A2B3",
            weight=ft.FontWeight.W_600,
            expand=True,
        )
        self.mobile_configuration_section_title = ft.Text(
            "配置表", size=11, color="#98A2B3", weight=ft.FontWeight.W_600, expand=True
        )
        self.new_configuration_name = ft.TextField(
            label="配置表名称", hint_text="例如：item_config", autofocus=True
        )
        self.configuration_search_field = ft.TextField(
            hint_text="搜索配置表…",
            prefix_icon=ft.Icons.SEARCH,
            text_size=12,
            dense=True,
            height=40,
            content_padding=ft.Padding(10, 8, 10, 8),
            border={
                ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                    border_radius=8, side=ft.BorderSide(color="#EAECF0")
                ),
                ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                    border_radius=8, side=ft.BorderSide(color="#7A83FF")
                ),
            },
        )
        self.configuration_file_list = ft.Column(
            [ft.Text("请先在导出设置中选择 TSV 目录。", size=11, color="#98A2B3")],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
        )
        self.mobile_configuration_search_field = ft.TextField(
            hint_text="搜索配置表…",
            prefix_icon=ft.Icons.SEARCH,
            text_size=12,
            dense=True,
            height=40,
            content_padding=ft.Padding(10, 8, 10, 8),
            border={
                ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                    border_radius=8, side=ft.BorderSide(color="#EAECF0")
                ),
                ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                    border_radius=8, side=ft.BorderSide(color="#7A83FF")
                ),
            },
        )
        self.mobile_configuration_file_list = ft.Column(
            spacing=4, scroll=ft.ScrollMode.AUTO, expand=True
        )
        self.backend_directory_field = ft.TextField(
            label="后端导出目录",
            value=self.export_paths["backend"] or "尚未选择",
            hint_text="选择目录，或直接粘贴路径",
            width=410,
        )
        self.frontend_directory_field = ft.TextField(
            label="前端导出目录",
            value=self.export_paths["frontend"] or "尚未选择",
            hint_text="选择目录，或直接粘贴路径",
            width=410,
        )
        self.ui_directory_field = ft.TextField(
            label="UI 配置目录",
            value=self.ui_directory or "尚未选择",
            hint_text=r"例如 D:\code\game_demo_client\assets\resources\ui",
            width=410,
        )
        self.backend_format_select = ft.Dropdown(
            label="后端文件格式",
            value=backend_format,
            options=[
                ft.DropdownOption(key="lua", text="Lua"),
                ft.DropdownOption(key="json", text="JSON"),
            ],
            width=220,
        )
        self.frontend_format_select = ft.Dropdown(
            label="前端文件格式",
            value=frontend_format,
            options=[
                ft.DropdownOption(key="lua", text="Lua"),
                ft.DropdownOption(key="json", text="JSON"),
            ],
            width=220,
        )
        self.table_area = ft.Column(expand=True, spacing=0)
        self.table_status = ft.Text(
            color="#667085",
            size=12,
            expand=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.selected_row_status = ft.Text(
            "先点行号选择一行",
            color="#667085",
            size=12,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.page_status = ft.Text(color="#667085", size=12)
        self.column_manager_refresh = None
        self.page_size_label = ft.Text(
            f"{self.page_size} 条/页", size=12, color="#344054"
        )
        page_size_select = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row(
                    [
                        self.page_size_label,
                        ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color="#667085"),
                    ],
                    spacing=2,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                height=34,
                padding=ft.Padding(14, 0, 8, 0),
                border=ft.Border.all(1, "#D0D5DD"),
                border_radius=17,
                alignment=ft.Alignment(0, 0),
            ),
            items=[
                ft.PopupMenuItem(
                    content=ft.Text(f"{size} 条/页", size=12, color="#344054"),
                    height=36,
                    on_click=lambda _, size=size: self.set_page_size(size),
                )
                for size in PAGE_SIZES
            ],
            menu_position=ft.PopupMenuPosition.UNDER,
            tooltip="选择每页显示条数",
        )
        self.page_number_text = ft.Text(
            color="#344054", size=13, weight=ft.FontWeight.W_600
        )
        self.source_text = ft.Text(self.source_name, color="#344054", size=13)
        self.row_count_text = ft.Text()
        self.column_count_text = ft.Text()
        self.configuration_search_field.on_change = (
            lambda _: self.refresh_configuration_files()
        )
        self.mobile_configuration_search_field.on_change = (
            lambda _: self.refresh_configuration_files()
        )
        self.text_entry_focused = False

        def mark_text_entry(focused: bool):
            self.text_entry_focused = focused

        self.configuration_search_field.on_focus = lambda _: mark_text_entry(True)
        self.configuration_search_field.on_blur = lambda _: mark_text_entry(False)
        self.mobile_configuration_search_field.on_focus = lambda _: mark_text_entry(True)
        self.mobile_configuration_search_field.on_blur = lambda _: mark_text_entry(False)
        self.backend_format_select.on_select = lambda _: self.save_export_settings()
        self.frontend_format_select.on_select = lambda _: self.save_export_settings()
        self.configuration_delete_button = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE,
            icon_size=18,
            tooltip="删除当前配置表",
            on_click=self.delete_active_configuration_file,
            disabled=self.active_table_path is None,
        )
        self.configuration_file_list_container = ft.Container(
            content=self.configuration_file_list,
            height=240,
            border=ft.Border.all(1, "#EAECF0"),
            border_radius=9,
            padding=6,
        )
        self.sidebar = ft.Container(
            width=226,
            bgcolor="#FFFFFF",
            padding=ft.Padding(18, 24, 18, 20),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.AUTO_AWESOME, color="#FFFFFF", size=19
                                ),
                                bgcolor="#5B6CFF",
                                border_radius=10,
                                padding=9,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "星图",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color="#101828",
                                    ),
                                    ft.Text(
                                        "GAME DATA STUDIO", size=9, color="#98A2B3"
                                    ),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Container(height=26),
                    ft.Text(
                        "工作空间", size=11, color="#98A2B3", weight=ft.FontWeight.W_600
                    ),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.TABLE_VIEW, color="#5B6CFF", size=18),
                                ft.Text(
                                    "配置表管理",
                                    size=13,
                                    color="#344054",
                                    weight=ft.FontWeight.W_600,
                                ),
                            ],
                            spacing=11,
                        ),
                        bgcolor="#EEF0FF",
                        border_radius=9,
                        padding=12,
                    ),
                    ft.Row(
                        [
                            configuration_section_title,
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                icon_size=18,
                                tooltip="刷新配置表",
                                on_click=self.reload_configuration_files,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_size=18,
                                tooltip="新建配置表",
                                on_click=self.open_new_configuration_dialog,
                            ),
                            self.configuration_delete_button,
                        ],
                        spacing=2,
                    ),
                    self.configuration_search_field,
                    self.configuration_file_list_container,
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(
                                    ft.Icons.TIPS_AND_UPDATES_OUTLINED,
                                    color="#5B6CFF",
                                    size=20,
                                ),
                                ft.Text("小提示", size=12, weight=ft.FontWeight.W_600),
                                ft.Text(
                                    "配置表使用 TSV；导出时可分别设置前后端目录和格式。",
                                    size=11,
                                    color="#667085",
                                ),
                            ],
                            spacing=8,
                        ),
                        bgcolor="#F8F9FC",
                        border_radius=12,
                        padding=14,
                    ),
                    ft.Row(
                        [
                            ft.CircleAvatar(
                                content=ft.Icon(
                                    ft.Icons.SMART_TOY, size=17, color="#FFFFFF"
                                ),
                                bgcolor="#98A2B3",
                                radius=17,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "游戏配置助手",
                                        size=12,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text("本地工作区", size=10, color="#98A2B3"),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=12,
                expand=True,
            ),
        )
        self.mobile_configuration_button = ft.OutlinedButton(
            "配置表",
            icon=ft.Icons.TABLE_VIEW,
            on_click=self.open_mobile_configuration_list,
            visible=False,
        )
        self.header_actions = ft.Row(
            [
                self.mobile_configuration_button,
                ft.OutlinedButton(
                    "插件",
                    icon=ft.Icons.EXTENSION_OUTLINED,
                    on_click=self.open_plugin_manager,
                    visible=not self.mobile_platform,
                    tooltip="安装或卸载插件",
                ),
                ft.OutlinedButton(
                    "导出设置",
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    on_click=self.open_export_settings,
                ),
                ft.Button(
                    "全量导出", icon=ft.Icons.DOWNLOAD, on_click=self.export_all_files
                ),
                ft.OutlinedButton(
                    "增量导出",
                    icon=ft.Icons.CHANGE_CIRCLE_OUTLINED,
                    on_click=self.export_incremental_files,
                ),
            ],
            spacing=8,
            wrap=True,
            run_spacing=8,
        )
        self.refresh_plugin_actions()
        self.header_title = ft.Column(
            [
                ft.Text(
                    "配置表管理", size=23, weight=ft.FontWeight.BOLD, color="#101828"
                ),
                ft.Text("查看、扩展并导出游戏配置数据", size=12, color="#667085"),
            ],
            spacing=5,
        )
        self.header_spacer = ft.Container(expand=True)
        self.header_content = ft.Row(
            [self.header_title, self.header_spacer, self.header_actions],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=False,
            run_spacing=10,
        )
        self.header = ft.Container(
            content=self.header_content, padding=ft.Padding(28, 22, 28, 18)
        )
        table_header_title = ft.Column(
            [
                ft.Text(
                    "配置表编辑", size=16, weight=ft.FontWeight.W_600, color="#101828"
                ),
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.DESCRIPTION_OUTLINED, size=14, color="#667085"
                        ),
                        self.source_text,
                        ft.Container(
                            content=ft.Text(
                                "点行号选择 · 拖动排序 · 单元格编辑",
                                size=10,
                                color="#3538CD",
                            ),
                            bgcolor="#EEF4FF",
                            border_radius=12,
                            padding=ft.Padding(8, 3, 8, 3),
                        ),
                    ],
                    spacing=7,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
            ],
            spacing=8,
        )
        table_header_actions = ft.Row(
            [
                ft.OutlinedButton(
                    "导表规则",
                    icon=ft.Icons.KEY_OUTLINED,
                    on_click=self.open_export_rule,
                ),
                ft.OutlinedButton(
                    "管理列",
                    icon=ft.Icons.VIEW_COLUMN_OUTLINED,
                    on_click=self.open_column_manager,
                ),
            ],
            spacing=8,
            wrap=True,
            alignment=ft.MainAxisAlignment.END,
        )
        self.row_copy_button = ft.OutlinedButton(
            "复制行",
            icon=ft.Icons.CONTENT_COPY,
            on_click=self.copy_selected_row,
            disabled=True,
            tooltip="复制选中行（Ctrl+C）",
        )
        self.row_paste_button = ft.OutlinedButton(
            "插入行",
            icon=ft.Icons.CONTENT_PASTE,
            on_click=self.paste_copied_row,
            disabled=True,
            tooltip="在选中行之前插入副本，原行下移（Ctrl+V）",
        )
        self.row_undo_button = ft.OutlinedButton(
            "撤销",
            icon=ft.Icons.UNDO,
            on_click=self.undo_row_action,
            disabled=True,
            tooltip="撤销最近一次行或单元格数据操作（Ctrl+Z）",
        )
        self.update_row_action_buttons()
        self.table_header_spacer = ft.Container(expand=True)
        self.table_header_row = ft.Row(
            [table_header_title, self.table_header_spacer, table_header_actions],
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=False,
            run_spacing=8,
        )
        row_action_toolbar = ft.Row(
            [
                self.selected_row_status,
                self.row_copy_button,
                self.row_paste_button,
                self.row_undo_button,
            ],
            alignment=ft.MainAxisAlignment.START,
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
            run_spacing=4,
        )
        row_action_section = ft.Column(
            [
                row_action_toolbar,
                ft.Text(
                    "用法：选中源行按 Ctrl+C；再选目标行按 Ctrl+V，副本插在目标行前、原行下移；Ctrl+Z 撤销。",
                    size=10,
                    color="#667085",
                ),
            ],
            spacing=4,
        )
        self.table_footer_status = ft.Row(
            [self.table_status, page_size_select],
            expand=True,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        table_footer_pagination = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    tooltip="上一页",
                    on_click=lambda _: self.change_page(-1),
                ),
                self.page_number_text,
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    tooltip="下一页",
                    on_click=lambda _: self.change_page(1),
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.table_footer_row = ft.Row(
            [self.table_footer_status, table_footer_pagination],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=False,
            run_spacing=4,
        )
        self.table_card = ft.Container(
            content=ft.Column(
                [
                    self.table_header_row,
                    row_action_section,
                    ft.Divider(height=1, color="#EAECF0"),
                    self.table_area,
                    ft.Divider(height=1, color="#EAECF0"),
                    self.table_footer_row,
                ],
                expand=True,
                spacing=12,
            ),
            bgcolor="#FFFFFF",
            border=ft.Border.all(1, "#EAECF0"),
            border_radius=14,
            padding=18,
            expand=True,
        )
        self.metric_cards = [
            self.metric_card(
                "配置行数",
                self.row_count_text,
                ft.Icons.FORMAT_LIST_NUMBERED,
                "#5B6CFF",
            ),
            self.metric_card(
                "配置列数",
                self.column_count_text,
                ft.Icons.VIEW_COLUMN_OUTLINED,
                "#12B76A",
            ),
            self.metric_card(
                "当前分页", self.page_status, ft.Icons.AUTO_STORIES_OUTLINED, "#F79009"
            ),
            self.metric_card(
                "配置表数量",
                self.configuration_count_metric,
                ft.Icons.TABLE_VIEW,
                "#7F56D9",
            ),
        ]
        self.metrics_row = ft.Row(
            self.metric_cards, spacing=14, wrap=False, run_spacing=8
        )
        self.content_body = ft.Container(
            content=ft.Column(
                [self.metrics_row, self.table_card], spacing=18, expand=True
            ),
            padding=ft.Padding(28, 0, 28, 24),
            expand=True,
        )
        content = ft.Column([self.header, self.content_body], spacing=0, expand=True)
        workspace = ft.Row(
            [self.sidebar, ft.Container(content=content, expand=True)],
            spacing=0,
            expand=True,
        )
        self.page.add(workspace)
        self.page.on_resize = self.handle_resize
        self.page.on_keyboard_event = self.handle_row_shortcuts
        self.apply_responsive_layout()
        self.refresh_table()
        startup_errors = []
        if self.configuration_directory and (not self.mobile_platform):
            try:
                table_count = self.count_configuration_tables(
                    self.configuration_directory
                )
                self.configuration_table_count.value = (
                    f"目录中有 {table_count} 张 TSV 配置表"
                )
                self.configuration_count_metric.value = str(table_count)
                self.refresh_configuration_files()
            except OSError as exc:
                self.configuration_file_list.controls = [
                    ft.Text("无法读取配置目录。", size=11, color="#B42318")
                ]
                startup_errors.append(f"读取已保存的配置目录失败：{exc}")
        elif self.mobile_platform:
            self.refresh_configuration_files()
        if settings_load_error:
            startup_errors.append(settings_load_error)
        startup_errors.extend(
            f"插件加载失败：{message}" for message in self.plugin_errors
        )
        if startup_errors:
            self.notify("；".join(startup_errors), error=True)

    def open_table_agent(self, _=None):
        opener = getattr(self, "_open_ai_agent", None)
        if opener is None:
            class _AgentHost:
                pass

            agent_host = _AgentHost()
            agent_host.page = self.page
            agent_host.agent_settings = self.agent_settings
            agent_host.agent_provider_labels = self.agent_provider_labels
            agent_host.columns = self.columns
            agent_host.data_types = self.data_types
            agent_host.targets = self.targets
            agent_host.annotations = self.annotations
            agent_host.key_columns = self.key_columns
            agent_host.rows = self.rows
            agent_host.source_text = self.source_text
            agent_host.type_labels = DATA_TYPES
            agent_host.target_labels = EXPORT_TARGETS
            agent_host.source_name = lambda: self.source_name
            agent_host.current_page = lambda: self.current_page
            agent_host.page_size = lambda: self.page_size
            agent_host.column_manager_refresh = lambda: self.column_manager_refresh
            agent_host.dialog_width = self.dialog_width
            agent_host.dialog_height = self.dialog_height
            agent_host.show_alert_dialog = self.show_alert_dialog
            agent_host.notify = self.notify
            agent_host.save_export_settings = self.save_export_settings
            agent_host.refresh_agent_provider_labels = self.refresh_agent_provider_labels
            agent_host.record_row_undo = self.record_row_undo
            agent_host.mark_active_table_modified = self.mark_active_table_modified
            agent_host.persist_active_table = self.persist_active_table
            agent_host.refresh_table = self.refresh_table
            agent_host.parse_data_value = parse_data_value
            agent_host.display_value = _display_value
            _, opener = create_agent_dialogs(agent_host)
            self._open_ai_agent = opener
        opener(None)

    def refresh_plugin_actions(self, update: bool = False):
        try:
            actions, errors = load_plugins(_PluginHost(self))
        except Exception as exc:
            actions, errors = [], [str(exc)]
        self.plugin_actions = actions
        self.plugin_errors = errors
        if update:
            self.page.update()

    def open_plugin_manager(self, _):
        try:
            packages = list_plugin_packages()
        except OSError as exc:
            self.notify(f"读取插件失败：{exc}", error=True)
            return
        if packages:
            rows = [self.plugin_package_row(package) for package in packages]
        else:
            rows = [ft.Text("没有可安装的插件。", size=12, color="#667085")]
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("插件"),
                content=ft.Column(
                    [
                        ft.Text(
                            "安装后点「打开」使用。插件都从这里进入，不占顶栏。",
                            size=12,
                            color="#667085",
                        ),
                        *rows,
                    ],
                    spacing=12,
                    width=self.dialog_width(520),
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: self.page.pop_dialog())
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def plugin_package_row(self, package):
        def install(_):
            updating = package.installed
            try:
                install_plugin(package.plugin_id)
            except (OSError, FileNotFoundError) as exc:
                self.notify(f"安装失败：{exc}", error=True)
                return
            self.refresh_plugin_actions(update=True)
            self.page.pop_dialog()
            self.open_plugin_manager(None)
            verb = "更新" if updating else "安装"
            self.notify(f"已{verb}「{package.title}」")

        def uninstall(_):
            try:
                uninstall_plugin(package.plugin_id)
            except OSError as exc:
                self.notify(f"卸载失败：{exc}", error=True)
                return
            self.refresh_plugin_actions(update=True)
            self.page.pop_dialog()
            self.open_plugin_manager(None)
            self.notify(f"已卸载「{package.title}」")

        async def open_plugin(_):
            action = next(
                (
                    item
                    for item in self.plugin_actions
                    if item.plugin_id == package.plugin_id
                ),
                None,
            )
            if action is None:
                self.notify(f"请先安装「{package.title}」。", error=True)
                return
            self.page.pop_dialog()
            try:
                result = action.on_click(_)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.notify(f"打开「{package.title}」失败：{exc}", error=True)

        actions = []
        if package.installed and not package.outdated:
            actions.append(ft.Button("打开", on_click=open_plugin))
        if package.outdated:
            actions.append(ft.Button("更新", on_click=install))
        actions.append(
            ft.OutlinedButton("卸载", on_click=uninstall)
            if package.installed
            else ft.Button("安装", on_click=install)
        )
        status = "有新版本" if package.outdated else "已安装" if package.installed else "未安装"
        status_color = "#B54708" if package.outdated else "#027A48" if package.installed else "#98A2B3"
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(package.title, size=14, weight=ft.FontWeight.W_600),
                            ft.Text(package.description, size=12, color="#667085"),
                            ft.Text(status, size=11, color=status_color),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    ft.Row(actions, spacing=8),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border=ft.Border.all(1, "#EAECF0"),
            border_radius=12,
            padding=12,
        )

class _PluginHost:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def notify(self, message: str, error: bool = False) -> None:
        self.workspace.notify(message, error)

    def show_dialog(self, dialog, on_close=None) -> None:
        self.workspace.show_alert_dialog(dialog, on_close=on_close)

    def listen_keyboard(self, handler) -> None:
        self.workspace.plugin_keyboard_handler = handler

    def stop_keyboard(self) -> None:
        self.workspace.plugin_keyboard_handler = None

    def focus(self, control) -> None:
        focus = getattr(control, "focus", None)
        if focus is None:
            return
        result = focus()
        run_task = getattr(self.workspace.page, "run_task", None)
        if result is not None and run_task is not None:
            async def runner():
                await result

            run_task(runner)

    def pop_dialog(self) -> None:
        self.workspace.page.pop_dialog()

    def update(self) -> None:
        self.workspace.page.update()

    def dialog_width(self, preferred: int) -> int:
        return self.workspace.dialog_width(preferred)

    def dialog_height(self, preferred: int, margin: int = 80) -> int:
        return self.workspace.dialog_height(preferred, margin)

    def show_text(self, title: str, text: str) -> None:
        self.workspace.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(title),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                text,
                                selectable=True,
                                size=12,
                                color="#344054",
                            )
                        ],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    width=self.workspace.dialog_width(720),
                    height=self.workspace.dialog_height(420),
                ),
            )
        )

    async def pick_directory(self, title: str, initial: str | None = None) -> str | None:
        try:
            return await self.workspace.picker.get_directory_path(
                dialog_title=title,
                initial_directory=self.workspace.available_initial_directory(initial),
            )
        except (OSError, RuntimeError) as exc:
            self.workspace.notify(f"选择目录失败：{exc}", error=True)
            return None

    def configuration_directory(self) -> str | None:
        return self.workspace.configuration_directory

    def open_table_agent(self) -> None:
        self.workspace.open_table_agent()

    def active_table_path(self) -> str | None:
        path = self.workspace.active_table_path
        return str(path) if path is not None else None

    def reload_active_table(self) -> bool:
        return self.workspace.reload_active_table()

    def get_setting(self, plugin_id: str, key: str, default=None):
        bucket = self.workspace.plugin_settings.get(plugin_id)
        if not isinstance(bucket, dict):
            return default
        return bucket.get(key, default)

    def set_setting(self, plugin_id: str, key: str, value) -> None:
        bucket = self.workspace.plugin_settings.get(plugin_id)
        if not isinstance(bucket, dict):
            bucket = {}
            self.workspace.plugin_settings[plugin_id] = bucket
        bucket[key] = value
        self.workspace.save_export_settings()

    @property
    def app_directory(self) -> Path:
        return Path(__file__).resolve().parent


def prepare_desktop_window(page):
    platform = getattr(page, "platform", None)
    if platform is not None and platform.is_mobile():
        return
    page.window.min_width = 960
    page.window.min_height = 680


def main(page):
    Workspace(page)
