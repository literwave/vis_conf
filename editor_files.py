from pathlib import Path
import copy
import flet as ft
import json
import os
from table_file import load_table, new_configuration_table_bytes


class EditorFiles:
    def count_configuration_tables(self, directory: str) -> int:
        return sum(
            (
                path.is_file() and path.suffix.lower() == ".tsv"
                for path in Path(directory).iterdir()
            )
        )

    def table_path_key(self, path: Path) -> str:
        return os.path.normcase(str(path.resolve()))

    def configuration_paths(self) -> list[Path]:
        if self.mobile_platform:
            return sorted(
                self.mobile_configuration_paths, key=lambda path: path.name.casefold()
            )
        if not self.configuration_directory:
            return []
        return sorted(
            (
                path
                for path in Path(self.configuration_directory).iterdir()
                if path.is_file() and path.suffix.lower() == ".tsv"
            ),
            key=lambda path: path.name.casefold(),
        )

    def make_configuration_file_controls(
        self, tables: list[Path], query: str, close_dialog_on_select: bool = False
    ) -> list[ft.Control]:
        query = query.strip().casefold()

        def matches_query(filename: str) -> bool:
            if not query:
                return True
            candidate = filename.casefold()
            query_index = 0
            for character in candidate:
                if character == query[query_index]:
                    query_index += 1
                    if query_index == len(query):
                        return True
            return False

        tables = [path for path in tables if matches_query(path.name)]
        if not tables:
            empty_message = (
                "没有匹配的 TSV 文件。"
                if query
                else (
                    "请先选择 TSV 文件。"
                    if self.mobile_platform
                    else "此目录下没有 TSV 文件。"
                )
            )
            return [ft.Text(empty_message, size=11, color="#98A2B3")]

        def select_table(path: Path):
            self.load_configuration_file(path)
            if close_dialog_on_select:
                self.page.pop_dialog()

        return [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            size=15,
                            color=(
                                "#5B6CFF"
                                if self.active_table_path is not None
                                and self.table_path_key(path)
                                == self.table_path_key(self.active_table_path)
                                else "#98A2B3"
                            ),
                        ),
                        ft.Text(
                            path.name,
                            size=11,
                            color="#344054",
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                        ft.Container(
                            width=6,
                            height=6,
                            border_radius=3,
                            bgcolor="#F79009",
                            visible=self.table_path_key(path)
                            in self.modified_table_paths,
                            tooltip="本次会话中已修改",
                        ),
                    ],
                    spacing=8,
                ),
                bgcolor=(
                    "#EEF0FF"
                    if self.active_table_path is not None
                    and self.table_path_key(path)
                    == self.table_path_key(self.active_table_path)
                    else None
                ),
                border_radius=7,
                padding=ft.Padding(9, 7, 9, 7),
                ink=True,
                ink_color="#EEF0FF",
                on_click=lambda _, selected_path=path: select_table(selected_path),
                tooltip=path.name if self.mobile_platform else str(path),
            )
            for path in tables
        ]

    def refresh_configuration_files(self):
        tables = self.configuration_paths()
        self.configuration_file_list.controls = self.make_configuration_file_controls(
            tables, self.configuration_search_field.value or ""
        )
        self.mobile_configuration_file_list.controls = (
            self.make_configuration_file_controls(
                tables,
                self.mobile_configuration_search_field.value or "",
                close_dialog_on_select=True,
            )
        )
        if self.configuration_delete_button is not None:
            self.configuration_delete_button.disabled = self.active_table_path is None

    def load_configuration_file(self, path: Path):
        path_key = self.table_path_key(path)
        if (
            self.active_table_path is not None
            and self.table_path_key(self.active_table_path) == path_key
        ):
            return
        self.cache_active_table()
        try:
            if path_key in self.table_states:
                state = self.table_states[path_key]
                loaded_columns = state["columns"].copy()
                loaded_types = state["data_types"].copy()
                loaded_targets = state["targets"].copy()
                loaded_annotations = state["annotations"].copy()
                loaded_rows = copy.deepcopy(state["rows"])
                loaded_keys = state["key_columns"].copy()
            else:
                (
                    loaded_columns,
                    loaded_types,
                    loaded_targets,
                    loaded_annotations,
                    loaded_rows,
                ) = load_table(path, self.mobile_file_bytes.get(path_key))
                saved_keys = self.key_rules_by_table.get(path.name)
                loaded_keys = (
                    [column for column in loaded_columns if column in saved_keys]
                    if saved_keys is not None
                    else ["id"] if "id" in loaded_columns else []
                )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            self.notify(f"打开配置表失败：{exc}", error=True)
            return
        self.columns[:] = loaded_columns
        self.data_types[:] = loaded_types
        self.targets[:] = loaded_targets
        self.annotations[:] = loaded_annotations
        self.rows[:] = loaded_rows
        self.key_columns[:] = loaded_keys
        self.current_page = 0
        self.selected_row_index = None
        self.source_name = path.name
        self.active_table_path = path
        self.key_rules_by_table[self.source_name] = self.key_columns.copy()
        self.source_text.value = self.source_name
        self.save_export_settings()
        self.refresh_configuration_files()
        self.update_row_action_buttons()
        self.refresh_table()
        self.notify(f"已打开 {self.source_name}（{len(self.rows)} 条记录）")

    def reload_active_table(self) -> bool:
        path = self.active_table_path
        if path is None:
            return False
        path = Path(path)
        if not path.is_file():
            return False
        path_key = self.table_path_key(path)
        self.table_states.pop(path_key, None)
        try:
            (
                loaded_columns,
                loaded_types,
                loaded_targets,
                loaded_annotations,
                loaded_rows,
            ) = load_table(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            self.notify(f"重新读取配置表失败：{exc}", error=True)
            return False
        self.columns[:] = loaded_columns
        self.data_types[:] = loaded_types
        self.targets[:] = loaded_targets
        self.annotations[:] = loaded_annotations
        self.rows[:] = loaded_rows
        saved_keys = self.key_rules_by_table.get(path.name)
        self.key_columns[:] = (
            [column for column in loaded_columns if column in saved_keys]
            if saved_keys is not None
            else ["id"] if "id" in loaded_columns else []
        )
        page_count = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        if self.current_page >= page_count:
            self.current_page = page_count - 1
        self.table_states[path_key] = self.snapshot_active_table()
        self.refresh_table()
        return True

    async def choose_export_directory(self, target: str):
        field = (
            self.backend_directory_field
            if target == "backend"
            else self.frontend_directory_field
        )
        label = "后端" if target == "backend" else "前端"
        try:
            directory = await self.picker.get_directory_path(
                dialog_title=f"选择{label}导出目录",
                initial_directory=self.available_initial_directory(
                    self.export_paths[target]
                ),
            )
        except (OSError, RuntimeError) as exc:
            self.notify(f"选择{label}导出目录失败：{exc}", error=True)
            return
        if directory is None:
            return
        self.export_paths[target] = directory
        field.value = directory
        self.save_export_settings()
        self.page.update()

    async def choose_backend_export_directory(self, _):
        await self.choose_export_directory("backend")

    async def choose_frontend_export_directory(self, _):
        await self.choose_export_directory("frontend")

    async def choose_configuration_directory(self, _):
        try:
            directory = await self.picker.get_directory_path(
                dialog_title="选择 TSV 配置文件目录",
                initial_directory=self.available_initial_directory(
                    self.configuration_directory
                ),
            )
        except (OSError, RuntimeError) as exc:
            self.notify(f"选择配置文件目录失败：{exc}", error=True)
            return
        if directory is None:
            return
        self.apply_configuration_directory(directory)

    def apply_configuration_directory(self, directory: str) -> bool:
        try:
            table_count = self.count_configuration_tables(directory)
        except OSError as exc:
            self.notify(f"读取配置文件目录失败：{exc}", error=True)
            return False
        self.configuration_directory = directory
        self.configuration_directory_field.value = directory
        self.configuration_table_count.value = f"目录中有 {table_count} 张 TSV 配置表"
        self.configuration_count_metric.value = str(table_count)
        self.save_export_settings()
        try:
            self.refresh_configuration_files()
        except OSError as exc:
            self.notify(f"读取配置文件目录失败：{exc}", error=True)
            return False
        self.page.update()
        return True

    async def choose_mobile_configuration_files(self, _):
        try:
            selected_files = await self.picker.pick_files(
                dialog_title="选择 TSV 配置文件",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["tsv"],
                allow_multiple=True,
                with_data=True,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.notify(f"选择 TSV 配置文件失败：{exc}", error=True)
            return
        if not selected_files:
            return
        existing_names = {
            path.name.casefold() for path in self.mobile_configuration_paths
        }
        added_paths = []
        for selected_file in selected_files:
            if Path(selected_file.name).suffix.casefold() != ".tsv":
                continue
            if selected_file.name.casefold() in existing_names:
                self.notify(
                    f"已跳过重复文件名「{selected_file.name}」，请先移除同名配置表。",
                    error=True,
                )
                continue
            if not isinstance(selected_file.bytes, bytes):
                self.notify(
                    f"无法读取「{selected_file.name}」的文件内容，请重新选择。",
                    error=True,
                )
                continue
            path = Path("mobile-files") / selected_file.name
            path_key = self.table_path_key(path)
            self.mobile_file_bytes[path_key] = selected_file.bytes
            self.mobile_configuration_paths.append(path)
            existing_names.add(selected_file.name.casefold())
            added_paths.append(path)
        if added_paths:
            self.mobile_configuration_paths.sort(key=lambda path: path.name.casefold())
            self.configuration_table_count.value = (
                f"手机中已选择 {len(self.mobile_configuration_paths)} 张 TSV 配置表"
            )
            self.configuration_count_metric.value = str(
                len(self.mobile_configuration_paths)
            )
            self.refresh_configuration_files()
            self.page.update()
            self.notify(f"已添加 {len(added_paths)} 张 TSV 配置表。")
        elif not any(
            (
                Path(selected_file.name).suffix.casefold() == ".tsv"
                for selected_file in selected_files
            )
        ):
            self.notify("请选择 .tsv 配置文件。", error=True)

    def update_configuration_count(self):
        count = len(self.configuration_paths())
        self.configuration_count_metric.value = str(count)
        if self.mobile_platform:
            self.configuration_table_count.value = f"手机中有 {count} 张 TSV 配置表"
        elif self.configuration_directory:
            self.configuration_table_count.value = f"目录中有 {count} 张 TSV 配置表"
        else:
            self.configuration_table_count.value = "尚未选择配置目录"

    def create_configuration_file(self, _):
        name = (self.new_configuration_name.value or "").strip()
        if name.lower().endswith(".tsv"):
            name = name[:-4]
        invalid_characters = '<>:"/\\|?*'
        if (
            not name
            or name in {".", ".."}
            or name.endswith((".", " "))
            or any((character in invalid_characters for character in name))
            or any((ord(character) < 32 for character in name))
        ):
            self.new_configuration_name.error_text = "请输入有效的配置表文件名。"
            self.page.update()
            return
        filename = f"{name}.tsv"
        try:
            existing_names = {
                path.name.casefold() for path in self.configuration_paths()
            }
        except OSError as exc:
            self.notify(f"读取配置文件列表失败：{exc}", error=True)
            return
        if filename.casefold() in existing_names:
            self.new_configuration_name.error_text = (
                "该配置表已存在，请使用其他文件名。"
            )
            self.page.update()
            return
        path = (
            Path("mobile-files") / filename
            if self.mobile_platform
            else Path(self.configuration_directory or "") / filename
        )
        if not self.mobile_platform and (not self.configuration_directory):
            self.notify("请先在导出设置中选择 TSV 配置目录。", error=True)
            return
        try:
            initial_content = new_configuration_table_bytes()
            if self.mobile_platform:
                self.mobile_configuration_paths.append(path)
                self.mobile_file_bytes[self.table_path_key(path)] = initial_content
            else:
                with path.open("xb") as new_file:
                    new_file.write(initial_content)
        except OSError as exc:
            self.notify(f"新建配置表失败：{exc}", error=True)
            return
        self.page.pop_dialog()
        self.load_configuration_file(path)
        if self.active_table_path is not None and self.table_path_key(
            self.active_table_path
        ) == self.table_path_key(path):
            self.mark_active_table_modified()
        self.update_configuration_count()
        self.refresh_configuration_files()
        self.page.update()
        self.notify(f"已新建配置表「{filename}」")

    def open_new_configuration_dialog(self, _):
        if not self.mobile_platform and (not self.configuration_directory):
            self.notify("请先在导出设置中选择 TSV 配置目录。", error=True)
            return
        self.new_configuration_name.value = ""
        self.new_configuration_name.error_text = None
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("新建配置表"),
                content=ft.Column(
                    [
                        ft.Text(
                            "将创建一个包含默认 id 字段的空 TSV 配置表。",
                            size=12,
                            color="#667085",
                        ),
                        self.new_configuration_name,
                    ],
                    tight=True,
                    width=self.dialog_width(380),
                    spacing=12,
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(
                        "新建",
                        icon=ft.Icons.ADD,
                        on_click=self.create_configuration_file,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def delete_active_configuration_file(self, _):
        path = self.active_table_path
        if path is None or all(
            (
                self.table_path_key(item) != self.table_path_key(path)
                for item in self.configuration_paths()
            )
        ):
            self.notify("请先从左侧选择要删除的配置表。", error=True)
            return
        if self.mobile_platform:
            description = f"从本次会话中移除「{path.name}」？手机原始文件不会被删除。"
        else:
            description = f"确定从配置目录中永久删除「{path.name}」吗？此操作无法撤销。"

        def confirm_delete(_):
            path_key = self.table_path_key(path)
            try:
                if self.mobile_platform:
                    self.mobile_configuration_paths[:] = [
                        item
                        for item in self.mobile_configuration_paths
                        if self.table_path_key(item) != path_key
                    ]
                    self.mobile_file_bytes.pop(path_key, None)
                else:
                    configuration_root = Path(
                        self.configuration_directory or ""
                    ).resolve()
                    resolved_path = path.resolve()
                    if (
                        path.suffix.lower() != ".tsv"
                        or resolved_path.parent != configuration_root
                    ):
                        raise ValueError("只能删除所选配置目录中的 TSV 文件。")
                    path.unlink()
            except (OSError, ValueError) as exc:
                self.page.pop_dialog()
                self.notify(f"删除配置表失败：{exc}", error=True)
                return
            self.table_states.pop(path_key, None)
            self.modified_table_paths.discard(path_key)
            if (
                self.active_table_path is not None
                and self.table_path_key(self.active_table_path) == path_key
            ):
                self.active_table_path = None
                self.source_name = "未选择配置表"
                self.columns.clear()
                self.data_types.clear()
                self.targets.clear()
                self.annotations.clear()
                self.rows.clear()
                self.key_columns.clear()
                self.source_text.value = self.source_name
            self.page.pop_dialog()
            self.update_configuration_count()
            self.refresh_configuration_files()
            remaining_paths = self.configuration_paths()
            if remaining_paths:
                self.load_configuration_file(remaining_paths[0])
            else:
                self.current_page = 0
                self.refresh_table()
            self.page.update()
            self.notify(f"已删除配置表「{path.name}」")

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除配置表"),
                content=ft.Text(description),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(
                        "删除",
                        icon=ft.Icons.DELETE_OUTLINE,
                        style=ft.ButtonStyle(bgcolor="#D92D20", color="#FFFFFF"),
                        on_click=confirm_delete,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def open_mobile_configuration_list(self, _):
        self.refresh_configuration_files()
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("选择配置表"),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                self.mobile_configuration_section_title,
                                ft.IconButton(
                                    icon=ft.Icons.ADD,
                                    tooltip="新建配置表",
                                    on_click=self.open_new_configuration_dialog,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.FILE_OPEN,
                                    tooltip="从手机导入 TSV",
                                    on_click=self.choose_mobile_configuration_files,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    tooltip="删除当前配置表",
                                    on_click=self.delete_active_configuration_file,
                                    disabled=self.active_table_path is None,
                                ),
                            ],
                            spacing=2,
                        ),
                        self.mobile_configuration_search_field,
                        ft.Container(
                            content=self.mobile_configuration_file_list,
                            width=self.dialog_width(440),
                            height=self.dialog_height(440, margin=240),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                            padding=6,
                        ),
                    ],
                    tight=True,
                    spacing=10,
                    width=self.dialog_width(440),
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: self.page.pop_dialog())
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )
