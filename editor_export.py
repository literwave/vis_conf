from pathlib import Path
import flet as ft
import json
import os
import app_settings
from agent_ui import agent_provider_label as format_agent_provider_label
from table_file import export_tsv, load_table
from export_data import (
    build_export_archive,
    checked_export_directory,
    export_content_changed,
    server_enum_directory,
    prepare_export_files,
    remove_stale_export_files,
    resolve_key_columns,
    store_directory_key_rules,
    write_export_files,
)


class EditorExport:
    def agent_provider_label(self) -> str:
        return format_agent_provider_label(self.agent_settings)

    def refresh_agent_provider_labels(self):
        label = self.agent_provider_label()
        for text in self.agent_provider_labels:
            text.value = label

    def persist_active_table(self) -> str:
        path = self.active_table_path
        if path is None:
            return "当前没有打开的配置文件，只更新了编辑器里的表。"
        file_path = Path(path)
        try:
            file_path.write_bytes(
                export_tsv(
                    self.columns,
                    self.data_types,
                    self.targets,
                    self.annotations,
                    self.rows,
                )
            )
        except OSError as exc:
            return f"表格已更新，但写入 {file_path.name} 失败：{exc}"
        export_note = self._write_active_table_exports(file_path)
        if export_note:
            return f"已保存到 {file_path.name}，{export_note}"
        return f"已保存到 {file_path.name}。"

    def _write_active_table_exports(self, file_path: Path) -> str:
        if self.mobile_platform:
            return ""
        backend = self.export_paths.get("backend")
        frontend = self.export_paths.get("frontend")
        needs_backend = any(target in {"backend", "both"} for target in self.targets)
        needs_frontend = any(target in {"frontend", "both"} for target in self.targets)
        if (needs_backend and not backend) or (needs_frontend and not frontend):
            return ""
        if not needs_backend and not needs_frontend:
            return ""
        try:
            written = write_export_files(
                self.columns,
                self.data_types,
                self.targets,
                self.rows,
                self.source_name,
                self.backend_format_select.value or "lua",
                self.frontend_format_select.value or "json",
                backend,
                frontend,
                self.key_columns,
            )
        except (OSError, TypeError, ValueError) as exc:
            return f"导出前后端文件失败：{exc}"
        if not written:
            return ""
        self.modified_table_paths.discard(self.table_path_key(file_path))
        self.refresh_configuration_files()
        return f"并更新了 {len(written)} 个导出文件。"

    def save_export_settings(self):
        self.key_rules_by_table[self.source_name] = self.key_columns.copy()
        settings = {
            "export_paths": self.export_paths,
            "configuration_directory": self.configuration_directory,
            "ui_directory": self.ui_directory,
            "backend_format": self.backend_format_select.value or "lua",
            "frontend_format": self.frontend_format_select.value or "json",
            "key_rules": self.key_rules_by_table,
            "agent": self.agent_settings,
        }
        plugin_settings = getattr(self, "plugin_settings", None)
        if plugin_settings:
            settings["plugin_settings"] = plugin_settings
        settings_path = app_settings._app_settings_path()
        temporary_path = settings_path.with_suffix(".tmp")
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_path.replace(settings_path)
            store_directory_key_rules(
                self.configuration_directory, self.key_rules_by_table
            )
        except OSError as exc:
            self.notify(f"保存导出设置失败：{exc}", error=True)

    async def export_tables(
        self, incremental: bool, selected_table_paths: list[Path] | None = None
    ):
        if not self.configuration_paths():
            self.notify(
                (
                    "请先在导出设置中选择 TSV 配置文件。"
                    if self.mobile_platform
                    else "请先在导出设置中选择 TSV 配置目录。"
                ),
                error=True,
            )
            return
        selected_backend_format = self.backend_format_select.value or "lua"
        selected_frontend_format = self.frontend_format_select.value or "json"
        archive_saved_path: str | None = None
        removed_exports: list[Path] = []
        try:
            if incremental:
                paths = selected_table_paths or sorted(
                    (Path(path) for path in self.modified_table_paths),
                    key=lambda path: path.name.casefold(),
                )
                if not paths:
                    self.notify("本次会话没有修改过的配置表。")
                    return
            else:
                paths = self.configuration_paths()
                if not paths:
                    self.notify(
                        (
                            "没有已选择的 TSV 文件。"
                            if self.mobile_platform
                            else "配置目录中没有 TSV 文件。"
                        ),
                        error=True,
                    )
                    return
            prepared_outputs: list[tuple[Path, bytes]] = []
            table_output_paths: list[tuple[Path, list[Path]]] = []
            exported_path_keys: set[str] = set()
            output_backend_directory = (
                "backend" if self.mobile_platform else self.export_paths["backend"]
            )
            output_frontend_directory = (
                "frontend" if self.mobile_platform else self.export_paths["frontend"]
            )
            for path in paths:
                path_key = self.table_path_key(path)
                state = self.table_states.get(path_key)
                if state is None:
                    table_columns, table_types, table_targets, _, table_rows = (
                        load_table(path, self.mobile_file_bytes.get(path_key))
                    )
                    saved_keys = self.key_rules_by_table.get(path.name)
                    table_keys = resolve_key_columns(table_columns, saved_keys)
                else:
                    table_columns = state["columns"]
                    table_types = state["data_types"]
                    table_targets = state["targets"]
                    table_rows = state["rows"]
                    table_keys = state["key_columns"]
                try:
                    table_outputs = prepare_export_files(
                        columns=table_columns,
                        data_types=table_types,
                        targets=table_targets,
                        rows=table_rows,
                        source_name=path.name,
                        backend_format=selected_backend_format,
                        frontend_format=selected_frontend_format,
                        backend_directory=output_backend_directory,
                        frontend_directory=output_frontend_directory,
                        key_columns=table_keys,
                        validate_directories=not self.mobile_platform,
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"配置表「{path.name}」：{exc}") from exc
                prepared_outputs.extend(table_outputs)
                table_output_paths.append(
                    (path, [output_path for output_path, _ in table_outputs])
                )
                exported_path_keys.add(path_key)
            output_keys = [
                os.path.normcase(str(path.resolve())) for path, _ in prepared_outputs
            ]
            if len(output_keys) != len(set(output_keys)):
                raise ValueError(
                    "多个配置表生成了相同的导出路径，请检查配置表名称、导出目录和格式。"
                )
            if self.mobile_platform and prepared_outputs:
                archive_data = build_export_archive(prepared_outputs)
                archive_saved_path = await self.picker.save_file(
                    dialog_title="保存导出配置 ZIP",
                    file_name="game_config_export.zip",
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["zip"],
                    src_bytes=archive_data,
                )
                if archive_saved_path is None:
                    return
            else:
                for path, _ in prepared_outputs:
                    if path.parent.name == "enum":
                        path.parent.mkdir(parents=True, exist_ok=True)
                    if not path.parent.is_dir():
                        raise ValueError(f"导出目录不存在：{path.parent}")
                for path, data in prepared_outputs:
                    if path.is_file() and not export_content_changed(path, data):
                        continue
                    path.write_bytes(data)
                if not incremental:
                    kept_outputs = {
                        os.path.normcase(str(path.resolve()))
                        for path, _ in prepared_outputs
                    }
                    removed_exports.extend(
                        remove_stale_export_files(
                            self.export_paths.get("backend"),
                            selected_backend_format,
                            kept_outputs,
                        )
                    )
                    removed_exports.extend(
                        remove_stale_export_files(
                            self.export_paths.get("frontend"),
                            selected_frontend_format,
                            kept_outputs,
                        )
                    )
                    backend_directory = self.export_paths.get("backend")
                    if backend_directory:
                        removed_exports.extend(
                            remove_stale_export_files(
                                str(server_enum_directory(backend_directory)),
                                "lua",
                                kept_outputs,
                            )
                        )
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            self.notify(f"导出失败：{exc}", error=True)
            return
        self.modified_table_paths.difference_update(exported_path_keys)
        self.refresh_configuration_files()
        self.page.update()
        label = "增量导出" if incremental else "全量导出"

        def describe_output(output_path: Path) -> tuple[str, str, str]:
            parent_name = output_path.parent.name.casefold()
            if parent_name == "enum":
                return "枚举", "#F4F3FF", "#5925DC"
            backend_directory = self.export_paths.get("backend")
            frontend_directory = self.export_paths.get("frontend")
            try:
                resolved = output_path.resolve()
                if backend_directory and resolved.is_relative_to(
                    Path(backend_directory).resolve()
                ):
                    return "服务端", "#EFF8FF", "#175CD3"
                if frontend_directory and resolved.is_relative_to(
                    Path(frontend_directory).resolve()
                ):
                    return "客户端", "#FFF7ED", "#C2410C"
            except (OSError, ValueError):
                pass
            if parent_name in {"backend", "server"}:
                return "服务端", "#EFF8FF", "#175CD3"
            if parent_name in {"frontend", "client"}:
                return "客户端", "#FFF7ED", "#C2410C"
            return "文件", "#F2F4F7", "#344054"

        table_items = []
        for table_path, output_paths in table_output_paths:
            if output_paths:
                file_rows = []
                for output_path in output_paths:
                    kind, background, color = describe_output(output_path)
                    file_rows.append(
                        ft.Row(
                            [
                                ft.Container(
                                    content=ft.Text(
                                        kind,
                                        size=10,
                                        color=color,
                                        weight=ft.FontWeight.W_600,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    width=52,
                                    bgcolor=background,
                                    border_radius=4,
                                    padding=ft.Padding(0, 2, 0, 2),
                                    alignment=ft.Alignment(0, 0),
                                ),
                                ft.Text(
                                    output_path.name,
                                    size=12,
                                    color="#344054",
                                    tooltip=str(output_path),
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        )
                    )
                details = ft.Column(file_rows, spacing=4)
            else:
                details = ft.Text(
                    "未生成文件",
                    size=12,
                    color="#98A2B3",
                )
            table_items.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                table_path.stem,
                                size=13,
                                color="#101828",
                                weight=ft.FontWeight.W_600,
                            ),
                            details,
                        ],
                        spacing=6,
                    ),
                    padding=ft.Padding(12, 10, 12, 10),
                    border=ft.Border.only(bottom=ft.BorderSide(1, "#EAECF0")),
                )
            )
        summary_text = (
            f"共处理 {len(paths)} 张配置表，生成 {len(prepared_outputs)} 个文件。"
        )
        if archive_saved_path is not None:
            summary_text += f"\nZIP 已保存至：{archive_saved_path}"
        if removed_exports:
            removed_names = [path.name for path in removed_exports]
            shown_names = "、".join(removed_names[:8])
            if len(removed_names) > 8:
                shown_names += f" 等 {len(removed_names)} 个"
            summary_text += f"\n已删除没有对应配置表的文件：{shown_names}"
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"{label}完成"),
                content=ft.Column(
                    [
                        ft.Text(summary_text, size=12, color="#475467"),
                        ft.Container(
                            content=ft.Column(
                                table_items, spacing=0, scroll=ft.ScrollMode.AUTO
                            ),
                            width=self.dialog_width(460),
                            height=min(460, max(140, len(table_items) * 78)),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                        ),
                    ],
                    tight=True,
                    spacing=12,
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: self.page.pop_dialog())
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def export_all_files(self, _):
        await self.export_tables(incremental=False)

    def export_incremental_files(self, _):
        dirty_paths = sorted(
            (Path(path) for path in self.modified_table_paths),
            key=lambda path: (path.name.casefold(), str(path).casefold()),
        )
        if not dirty_paths:
            self.notify("本次会话没有修改过的配置表。")
            return
        error_text = ft.Text("", size=12, color="#D92D20")
        table_checkboxes: dict[str, ft.Checkbox] = {}
        for path in dirty_paths:
            path_key = self.table_path_key(path)
            table_checkboxes[path_key] = ft.Checkbox(label=path.name, value=True)

        async def export_selected_tables(_):
            selected_paths = [
                path
                for path in dirty_paths
                if table_checkboxes[self.table_path_key(path)].value
            ]
            if not selected_paths:
                error_text.value = "请至少勾选一张配置表。"
                self.page.update()
                return
            self.page.pop_dialog()
            await self.export_tables(
                incremental=True, selected_table_paths=selected_paths
            )

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("选择增量导出的配置表"),
                content=ft.Column(
                    [
                        ft.Text(
                            "仅显示本次会话中修改过的表；未勾选的表会保留在增量队列中。",
                            size=12,
                            color="#667085",
                        ),
                        error_text,
                        ft.Container(
                            content=ft.Column(
                                list(table_checkboxes.values()),
                                spacing=0,
                                scroll=ft.ScrollMode.AUTO,
                            ),
                            width=self.dialog_width(420),
                            height=min(360, max(100, len(dirty_paths) * 52)),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                            padding=ft.Padding(10, 4, 10, 4),
                        ),
                    ],
                    tight=True,
                    spacing=10,
                    width=self.dialog_width(440),
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(
                        "导出所选",
                        icon=ft.Icons.DOWNLOAD,
                        on_click=export_selected_tables,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def open_export_settings(self, _):
        if self.mobile_platform:
            settings_controls = [
                ft.Text(
                    "从手机文件中选择一个或多个 TSV。导出时会保存为 ZIP，内部保留前后端目录结构；修改仅保留在当前会话中。",
                    size=12,
                    color="#667085",
                ),
                ft.OutlinedButton(
                    "选择 TSV 文件",
                    icon=ft.Icons.FILE_OPEN,
                    on_click=self.choose_mobile_configuration_files,
                ),
                self.configuration_table_count,
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "每列的“导出端”下拉项控制字段输出到前端、后端或两端。",
                    size=12,
                    color="#667085",
                ),
                ft.Text("后端", size=13, weight=ft.FontWeight.W_600, color="#344054"),
                self.backend_format_select,
                ft.Text("前端", size=13, weight=ft.FontWeight.W_600, color="#344054"),
                self.frontend_format_select,
            ]
            settings_actions = [
                ft.TextButton("完成", on_click=lambda _: self.page.pop_dialog())
            ]
        else:
            settings_controls = [
                ft.Text(
                    "全量导出处理目录中的全部 TSV；增量导出仅处理本次在工具中修改过、还没导出的表。桌面端编辑单元格、行列或导出端后会立即写回当前 TSV，并更新已配置的前后端文件。手机上的修改仍只留在当前会话。",
                    size=12,
                    color="#667085",
                ),
                ft.Row(
                    [
                        self.configuration_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self.choose_configuration_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                self.configuration_table_count,
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "每列的“导出端”下拉项控制字段输出到前端、后端或两端。",
                    size=12,
                    color="#667085",
                ),
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text("后端", size=13, weight=ft.FontWeight.W_600, color="#344054"),
                self.backend_format_select,
                ft.Row(
                    [
                        self.backend_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self.choose_backend_export_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text("前端", size=13, weight=ft.FontWeight.W_600, color="#344054"),
                self.frontend_format_select,
                ft.Row(
                    [
                        self.frontend_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self.choose_frontend_export_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text("UI", size=13, weight=ft.FontWeight.W_600, color="#344054"),
                ft.Text(
                    "用来显示单元格里的图标。目录例如 D:\\code\\game_demo_client\\assets\\resources\\ui，路径写成 ui/item_icons/speed_up。",
                    size=12,
                    color="#667085",
                ),
                ft.Row(
                    [
                        self.ui_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self.choose_ui_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
            ]
            form_error = ft.Text("", size=12, color="#D92D20", visible=False)
            settings_controls.append(form_error)

            def show_form_error(message: str) -> None:
                form_error.value = message
                form_error.visible = True
                self.page.update()
                self.notify(message, error=True)

            def save_settings(_):
                try:
                    configuration = checked_export_directory(
                        "配置文件目录", self.configuration_directory_field.value
                    )
                    backend = checked_export_directory(
                        "后端导出目录", self.backend_directory_field.value
                    )
                    frontend = checked_export_directory(
                        "前端导出目录", self.frontend_directory_field.value
                    )
                    ui_directory = checked_export_directory(
                        "UI 配置目录", self.ui_directory_field.value
                    )
                except ValueError as exc:
                    show_form_error(str(exc))
                    return
                if configuration is None:
                    self.configuration_directory = None
                    self.configuration_directory_field.value = "尚未选择"
                    self.configuration_table_count.value = "尚未选择配置目录"
                    self.configuration_count_metric.value = "—"
                    self.refresh_configuration_files()
                else:
                    message = self.apply_configuration_directory(configuration)
                    if message:
                        show_form_error(message)
                        return
                self.export_paths["backend"] = backend
                self.export_paths["frontend"] = frontend
                self.ui_directory = ui_directory
                self.backend_directory_field.value = backend or "尚未选择"
                self.frontend_directory_field.value = frontend or "尚未选择"
                self.ui_directory_field.value = ui_directory or "尚未选择"
                self.save_export_settings()
                self.refresh_table()
                self.page.pop_dialog()
                self.page.update()
                self.notify("导出设置已保存")

            settings_actions = [
                ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                ft.Button("保存", on_click=save_settings),
            ]

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("导出设置"),
                content=ft.Column(
                    settings_controls,
                    height=self.dialog_height(680, margin=112),
                    width=self.dialog_width(640),
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=settings_actions,
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )
