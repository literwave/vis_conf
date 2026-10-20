import flet as ft
import json
from schema import DATA_TYPES, EXPORT_TARGETS
from table_file import parse_data_value


def _set_field_error(field: ft.TextField | ft.Dropdown, message: str | None) -> None:
    if isinstance(field, ft.TextField):
        field.error = message
        field.error_max_lines = 3
    else:
        field.error_text = message


def _clear_field_error(field: ft.TextField | ft.Dropdown) -> None:
    _set_field_error(field, None)


class EditorColumns:
    def open_column_manager(self, _):
        pending_column: str | None = None
        column_list = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO)
        manager_status = ft.Text(
            "删除字段会同时移除该列的全部数据。", size=12, color="#667085"
        )

        def remove_column(column: str):
            index = self.columns.index(column)
            self.columns.pop(index)
            self.data_types.pop(index)
            self.targets.pop(index)
            self.annotations.pop(index)
            self.key_columns[:] = [key for key in self.key_columns if key != column]
            for row in self.rows:
                row.pop(column, None)
            self.mark_active_table_modified()
            self.save_export_settings()
            self.refresh_table()
            manager_status.value = f"已删除列「{column}」。"
            render_columns()

        def request_delete(column: str):
            nonlocal pending_column
            pending_column = column
            render_columns()

        def cancel_delete():
            nonlocal pending_column
            pending_column = None
            render_columns()

        def render_columns():
            column_list.controls = []
            manager_status.value = (
                f"共 {len(self.columns)} 列。删除字段会同时移除该列的全部数据。"
            )
            if not self.columns:
                column_list.controls.append(
                    ft.Container(
                        content=ft.Text(
                            "还没有字段，点击“添加列”创建。",
                            size=12,
                            color="#98A2B3",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=24,
                    )
                )
                self.page.update()
                return
            for index, column in enumerate(self.columns):
                if pending_column == column:
                    content = ft.Row(
                        [
                            ft.Text(
                                f"删除「{column}」及其所有行数据？",
                                size=11,
                                color="#B42318",
                                expand=True,
                                max_lines=2,
                            ),
                            ft.TextButton(
                                "取消",
                                on_click=lambda _, callback=cancel_delete: callback(),
                            ),
                            ft.Button(
                                "删除",
                                icon=ft.Icons.DELETE_OUTLINE,
                                style=ft.ButtonStyle(
                                    bgcolor="#D92D20", color="#FFFFFF"
                                ),
                                on_click=lambda _, name=column: remove_column(name),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    background = "#FEF3F2"
                else:
                    content = ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        column,
                                        size=13,
                                        color="#344054",
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        f"{DATA_TYPES[self.data_types[index]]} · {EXPORT_TARGETS[self.targets[index]]}",
                                        size=11,
                                        color="#98A2B3",
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=17,
                                icon_color="#98A2B3",
                                tooltip=f"删除「{column}」列",
                                mouse_cursor=ft.MouseCursor.CLICK,
                                on_click=lambda _, name=column: request_delete(name),
                                style=ft.ButtonStyle(
                                    overlay_color={
                                        ft.ControlState.HOVERED: "#FEE4E2",
                                        ft.ControlState.PRESSED: "#FECDCA",
                                    },
                                    icon_color={
                                        ft.ControlState.HOVERED: "#D92D20",
                                        ft.ControlState.PRESSED: "#B42318",
                                    },
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                    enable_feedback=True,
                                ),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    background = "#FFFFFF"
                column_list.controls.append(
                    ft.Container(
                        content=content,
                        bgcolor=background,
                        padding=ft.Padding(12, 8, 8, 8),
                        border=ft.Border.only(bottom=ft.BorderSide(1, "#EAECF0")),
                    )
                )
            self.page.update()

        def close_manager(_):
            self.column_manager_refresh = None
            self.page.pop_dialog()

        render_columns()
        self.column_manager_refresh = render_columns
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("管理列"),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                manager_status,
                                ft.Button(
                                    "添加列",
                                    icon=ft.Icons.ADD,
                                    on_click=self.add_column,
                                    style=ft.ButtonStyle(
                                        bgcolor="#EEF0FF", color="#4F5FE8"
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color="#EAECF0"),
                        ft.Container(
                            content=column_list,
                            width=self.dialog_width(460),
                            height=380,
                        ),
                    ],
                    tight=True,
                    spacing=8,
                ),
                actions=[ft.TextButton("完成", on_click=close_manager)],
                actions_alignment=ft.MainAxisAlignment.END,
            ),
            on_close=lambda: close_manager(None),
        )

    def add_column(self, _):
        form_error = ft.Text("", size=12, color="#D92D20", visible=False)
        name_input = ft.TextField(
            label="列名",
            hint_text="例如：description",
            autofocus=True,
            on_change=lambda _: self.clear_column_form_error(form_error, name_input),
        )
        type_input = ft.Dropdown(
            label="数据类型",
            value="string",
            options=[
                ft.DropdownOption(key=key, text=label)
                for key, label in DATA_TYPES.items()
            ],
            width=self.dialog_width(360),
        )
        target_input = ft.Dropdown(
            label="导出端",
            value="both",
            options=[
                ft.DropdownOption(key=key, text=label)
                for key, label in EXPORT_TARGETS.items()
            ],
            width=self.dialog_width(360),
        )
        annotation_input = ft.TextField(label="注释", hint_text="说明该字段的用途")
        default_input = ft.TextField(
            label="默认值",
            hint_text="留空表示空值",
            on_change=lambda _: self.clear_column_form_error(form_error, default_input),
        )
        type_input.on_select = lambda _: self.clear_column_form_error(
            form_error, type_input
        )
        target_input.on_select = lambda _: self.clear_column_form_error(
            form_error, target_input
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("添加新列"),
            content=ft.Column(
                [
                    form_error,
                    name_input,
                    type_input,
                    target_input,
                    annotation_input,
                    default_input,
                ],
                tight=True,
                width=self.dialog_width(400),
                spacing=14,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                ft.Button(
                    "添加列",
                    icon=ft.Icons.ADD,
                    on_click=lambda _: self.commit_column(
                        name_input,
                        type_input,
                        target_input,
                        annotation_input,
                        default_input,
                        form_error,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.show_alert_dialog(dialog)

    def clear_column_form_error(
        self, error_text: ft.Text, field: ft.TextField | ft.Dropdown | None = None
    ):
        if field is not None:
            _clear_field_error(field)
        error_text.value = ""
        error_text.visible = False

    def commit_column(
        self,
        name_input: ft.TextField,
        type_input: ft.Dropdown,
        target_input: ft.Dropdown,
        annotation_input: ft.TextField,
        default_input: ft.TextField,
        form_error: ft.Text,
    ):
        for field in (name_input, type_input, target_input, default_input):
            _clear_field_error(field)
        self.clear_column_form_error(form_error)

        def show_error(message: str, field: ft.TextField | ft.Dropdown | None = None):
            if field is not None:
                _set_field_error(field, message)
            form_error.value = message
            form_error.visible = True
            self.page.update()

        name = (name_input.value or "").strip()
        if not name:
            show_error("请输入列名。", name_input)
            return
        if name in self.columns:
            show_error(f"列「{name}」已存在，请使用其他列名。", name_input)
            return
        if type_input.value not in DATA_TYPES:
            show_error("请选择有效的数据类型。", type_input)
            return
        if target_input.value not in EXPORT_TARGETS:
            show_error("请选择有效的导出端。", target_input)
            return
        self.columns.append(name)
        self.data_types.append(type_input.value)
        self.targets.append(target_input.value)
        self.annotations.append(annotation_input.value or "")
        try:
            default_value = parse_data_value(
                default_input.value or "", type_input.value
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self.columns.pop()
            self.data_types.pop()
            self.targets.pop()
            self.annotations.pop()
            show_error(f"默认值与数据类型不匹配：{exc}", default_input)
            return
        for row in self.rows:
            row[name] = default_value
        if name == "id" and (not self.key_columns):
            self.key_columns.append(name)
        self.mark_active_table_modified()
        self.save_export_settings()
        self.page.pop_dialog()
        self.refresh_table()
        if self.column_manager_refresh is not None:
            self.column_manager_refresh()
        self.notify(f"已添加列「{name}」")
