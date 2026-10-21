import copy
import flet as ft
import json
from typing import Any
from schema import DATA_TYPES, EXPORT_TARGETS, MAX_ROW_UNDO, PAGE_SIZES
from table_file import (
    _display_value_for_type,
    insert_row_copy,
    move_row,
    parse_data_value,
)


def _cell_save_error(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return (
            "无法保存：JSON 格式不正确"
            f"（第 {exc.lineno} 行，第 {exc.colno} 个字符）。"
            '请使用双引号，例如 {"name": 1}。'
        )
    message = str(exc).strip()
    if message.startswith("invalid literal for int()"):
        return "无法保存：请输入整数。"
    if "could not convert string to float" in message:
        return "无法保存：请输入数字。"
    if not message:
        return "无法保存：内容格式不正确。"
    return f"无法保存：{message}"


class EditorRows:
    def snapshot_active_table(self) -> dict[str, Any]:
        return {
            "columns": self.columns.copy(),
            "data_types": self.data_types.copy(),
            "targets": self.targets.copy(),
            "annotations": self.annotations.copy(),
            "rows": copy.deepcopy(self.rows),
            "key_columns": self.key_columns.copy(),
        }

    def cache_active_table(self):
        if self.active_table_path is None:
            return
        path_key = self.table_path_key(self.active_table_path)
        self.table_states[path_key] = self.snapshot_active_table()

    def mark_active_table_modified(self):
        if self.active_table_path is None:
            return
        path_key = self.table_path_key(self.active_table_path)
        self.modified_table_paths.add(path_key)
        self.table_states[path_key] = self.snapshot_active_table()
        if not self.mobile_platform:
            message = self.persist_active_table()
            if "失败" in message:
                self.notify(message, error=True)
        self.refresh_configuration_files()

    def row_history_key(self) -> str:
        if self.active_table_path is not None:
            return self.table_path_key(self.active_table_path)
        return f"sample:{self.source_name}"

    def update_row_action_buttons(self):
        selected_exists = (
            self.selected_row_index is not None
            and 0 <= self.selected_row_index < len(self.rows)
        )
        self.selected_row_status.value = (
            f"目标：第 {self.selected_row_index + 1} 行"
            if selected_exists
            else "点行号选择目标；Ctrl+C 复制，Ctrl+V 插入到目标行前；Ctrl+Z 撤销"
        )
        if self.row_copy_button is not None:
            self.row_copy_button.disabled = not selected_exists
        if self.row_paste_button is not None:
            self.row_paste_button.disabled = not (
                selected_exists
                and self.copied_row is not None
                and (self.copied_row_table_key == self.row_history_key())
            )
        if self.row_undo_button is not None:
            self.row_undo_button.disabled = not self.row_undo_history.get(
                self.row_history_key()
            )

    def record_row_undo(self):
        history = self.row_undo_history.setdefault(self.row_history_key(), [])
        history.append(
            {
                "rows": copy.deepcopy(self.rows),
                "current_page": self.current_page,
                "selected_row_index": self.selected_row_index,
                "columns": self.columns.copy(),
                "data_types": self.data_types.copy(),
                "targets": self.targets.copy(),
                "annotations": self.annotations.copy(),
                "key_columns": self.key_columns.copy(),
            }
        )
        del history[:-MAX_ROW_UNDO]
        self.update_row_action_buttons()

    def select_row(self, row_index: int):
        if not 0 <= row_index < len(self.rows):
            return
        self.selected_row_index = row_index
        self.update_row_action_buttons()
        self.refresh_table()

    def copy_selected_row(self, _):
        if self.selected_row_index is None or not 0 <= self.selected_row_index < len(
            self.rows
        ):
            self.notify("请先点击行号选择要复制的行。", error=True)
            return
        self.copied_row = copy.deepcopy(self.rows[self.selected_row_index])
        self.copied_row_table_key = self.row_history_key()
        self.update_row_action_buttons()
        self.refresh_table()
        self.notify(f"已复制第 {self.selected_row_index + 1} 行")

    def paste_copied_row(self, _):
        if (
            self.selected_row_index is None
            or not 0 <= self.selected_row_index < len(self.rows)
            or self.copied_row is None
            or (self.copied_row_table_key != self.row_history_key())
        ):
            self.notify("请先在当前配置表中选择行并复制。", error=True)
            return
        self.record_row_undo()
        self.selected_row_index = insert_row_copy(
            self.rows, self.copied_row, self.selected_row_index
        )
        self.current_page = self.selected_row_index // self.page_size
        self.mark_active_table_modified()
        self.refresh_table()
        self.notify(f"已插入到第 {self.selected_row_index + 1} 行，原行下移")

    def _row_shortcuts_should_wait(self) -> bool:
        if getattr(self, "text_entry_focused", False):
            return True
        dialogs = getattr(self.page, "dialogs", None)
        if dialogs is None:
            holder = getattr(self.page, "_dialogs", None)
            dialogs = getattr(holder, "controls", ())
        for dialog in dialogs:
            if isinstance(dialog, ft.SnackBar):
                continue
            if getattr(dialog, "open", False):
                return True
        return False

    def handle_row_shortcuts(self, event: ft.KeyboardEvent):
        handler = getattr(self, "plugin_keyboard_handler", None)
        if callable(handler) and handler(event):
            return
        if self._row_shortcuts_should_wait():
            return
        key = event.key.casefold()
        if not (event.ctrl or event.meta) or event.alt or event.shift:
            return
        if key == "c":
            self.copy_selected_row(event)
        elif key == "v":
            self.paste_copied_row(event)
        elif key == "z":
            self.undo_row_action(event)

    def undo_row_action(self, _):
        history = self.row_undo_history.get(self.row_history_key())
        if not history:
            self.notify("当前配置表没有可撤销的操作。")
            return
        previous_state = history.pop()
        self.rows[:] = copy.deepcopy(previous_state["rows"])
        self.current_page = previous_state["current_page"]
        self.selected_row_index = previous_state["selected_row_index"]
        if "columns" in previous_state:
            self.columns[:] = previous_state["columns"]
            self.data_types[:] = previous_state["data_types"]
            self.targets[:] = previous_state["targets"]
            self.annotations[:] = previous_state["annotations"]
            self.key_columns[:] = previous_state["key_columns"]
        self.mark_active_table_modified()
        if self.active_table_path is not None:
            self.persist_active_table()
        self.update_row_action_buttons()
        self.refresh_table()
        self.notify("已撤销上一步操作")

    def reorder_row(self, event: ft.DragTargetEvent, target_index: int):
        try:
            source_index = int(event.src.data)
        except (AttributeError, TypeError, ValueError) as exc:
            self.notify(f"无法识别拖动的配置行：{exc}", error=True)
            return
        if not 0 <= source_index < len(self.rows) or not 0 <= target_index < len(
            self.rows
        ):
            self.notify("拖动位置已失效，请重试。", error=True)
            return
        if source_index == target_index:
            return
        self.record_row_undo()
        move_row(self.rows, source_index, target_index)
        self.selected_row_index = target_index
        self.current_page = target_index // self.page_size
        self.mark_active_table_modified()
        self.refresh_table()
        self.notify(f"已将配置行移动到第 {target_index + 1} 行")

    def edit_cell(self, row: dict[str, Any], column: str):
        column_index = self.columns.index(column)
        original = row.get(column)
        data_type = self.data_types[column_index]
        value_input = ft.TextField(
            label=column,
            value=_display_value_for_type(original, data_type),
            autofocus=True,
            multiline=data_type in {"json", "lua_array", "lua_object"},
            min_lines=1,
            max_lines=6 if data_type in {"json", "lua_array", "lua_object"} else 1,
            error_max_lines=4,
            width=self.dialog_width(460),
        )

        def save_value(_):
            try:
                updated_value = parse_data_value(value_input.value or "", data_type)
            except (ValueError, json.JSONDecodeError) as exc:
                value_input.error = _cell_save_error(exc)
                self.page.update()
                return
            if row.get(column) != updated_value:
                self.record_row_undo()
                row[column] = updated_value
                self.mark_active_table_modified()
            self.page.pop_dialog()
            self.refresh_table()

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"编辑「{column}」"),
                content=value_input,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button("保存", on_click=save_value),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def edit_column_name(self, index: int):
        current = self.columns[index]
        name_input = ft.TextField(
            label="字段名",
            value=current,
            autofocus=True,
            width=self.dialog_width(400),
        )

        def save_name(_):
            name = (name_input.value or "").strip()
            if not name or any(character in name for character in "\t\r\n"):
                name_input.error = "请输入有效的字段名。"
                self.page.update()
                return
            if name != current and name in self.columns:
                name_input.error = f"字段名「{name}」已存在。"
                self.page.update()
                return
            if name != current:
                self.record_row_undo()
                self.columns[index] = name
                for row in self.rows:
                    row[name] = row.pop(current) if current in row else None
                self.key_columns[:] = [
                    name if key == current else key for key in self.key_columns
                ]
                if (
                    self.copied_row is not None
                    and self.copied_row_table_key == self.row_history_key()
                    and current in self.copied_row
                ):
                    self.copied_row[name] = self.copied_row.pop(current)
                self.mark_active_table_modified()
                self.save_export_settings()
            self.page.pop_dialog()
            self.refresh_table()

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"编辑字段名「{current}」"),
                content=name_input,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button("保存", on_click=save_name),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def edit_annotation(self, index: int):
        annotation_input = ft.TextField(
            label=f"{self.columns[index]} 的注释",
            value=self.annotations[index],
            autofocus=True,
            multiline=True,
            min_lines=2,
            max_lines=5,
            width=self.dialog_width(400),
        )

        def save_annotation(_):
            annotation = annotation_input.value or ""
            if self.annotations[index] != annotation:
                self.annotations[index] = annotation
                self.mark_active_table_modified()
            self.page.pop_dialog()
            self.refresh_table()

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("编辑字段注释"),
                content=annotation_input,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button("保存", on_click=save_annotation),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def set_column_type(self, index: int, data_type: str):
        if data_type not in DATA_TYPES:
            raise ValueError(f"不支持的数据类型：{data_type}")
        if self.data_types[index] != data_type:
            self.data_types[index] = data_type
            self.mark_active_table_modified()

    def set_column_target(self, index: int, target: str):
        if target not in EXPORT_TARGETS:
            raise ValueError(f"不支持的导出端：{target}")
        if self.targets[index] != target:
            self.targets[index] = target
            self.mark_active_table_modified()

    def toggle_key_column(self, index: int):
        column = self.columns[index]
        previous_key_columns = self.key_columns.copy()
        if column in self.key_columns:
            self.key_columns.remove(column)
        else:
            self.key_columns.append(column)
        self.key_columns[:] = [
            name for name in self.columns if name in self.key_columns
        ]
        if self.key_columns != previous_key_columns:
            self.mark_active_table_modified()
        self.save_export_settings()
        self.refresh_table()

    def open_export_rule(self, _):
        rule_summary = ft.Text(size=12, color="#667085")
        key_checkboxes = {
            column: ft.Checkbox(label=column, value=column in self.key_columns)
            for column in self.columns
        }

        def update_rule(_):
            previous_key_columns = self.key_columns.copy()
            self.key_columns[:] = [
                column for column in self.columns if key_checkboxes[column].value
            ]
            if self.key_columns != previous_key_columns:
                self.mark_active_table_modified()
            rule_summary.value = (
                "当前规则：" + " → ".join(self.key_columns) + "（末级输出完整记录）"
                if self.key_columns
                else "当前规则：记录数组（未按字段建立索引）"
            )
            self.save_export_settings()
            self.page.update()

        for checkbox in key_checkboxes.values():
            checkbox.on_change = update_rule
        update_rule(None)
        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("导表规则"),
                content=ft.Column(
                    [
                        ft.Text(
                            "勾选字段作为导出 key；多个字段按当前表格列顺序逐层嵌套。默认使用 id，末级保留完整记录。",
                            size=12,
                            color="#667085",
                        ),
                        rule_summary,
                        ft.Container(
                            content=ft.Column(
                                list(key_checkboxes.values()),
                                spacing=0,
                                scroll=ft.ScrollMode.AUTO,
                            ),
                            width=self.dialog_width(420),
                            height=300,
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                            padding=ft.Padding(10, 4, 10, 4),
                        ),
                    ],
                    tight=True,
                    spacing=12,
                    width=440,
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: self.page.pop_dialog())
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def add_row(self, _):
        self.record_row_undo()
        self.rows.append(
            {
                column: "" if self.data_types[index] == "string" else None
                for index, column in enumerate(self.columns)
            }
        )
        self.selected_row_index = len(self.rows) - 1
        self.mark_active_table_modified()
        self.current_page = (len(self.rows) - 1) // self.page_size
        self.refresh_table()

    def confirm_delete_row(self, row: dict[str, Any]):
        row_number = next(
            (
                index + 1
                for index, current_row in enumerate(self.rows)
                if current_row is row
            ),
            None,
        )
        if row_number is None:
            return

        def delete_row(_):
            row_index = next(
                (
                    index
                    for index, current_row in enumerate(self.rows)
                    if current_row is row
                ),
                None,
            )
            if row_index is None:
                self.page.pop_dialog()
                return
            self.record_row_undo()
            self.rows.pop(row_index)
            if self.selected_row_index == row_index:
                self.selected_row_index = None
            elif (
                self.selected_row_index is not None
                and self.selected_row_index > row_index
            ):
                self.selected_row_index -= 1
            self.mark_active_table_modified()
            self.page.pop_dialog()
            self.refresh_table()
            self.notify(f"已删除第 {row_number} 行")

        self.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除数据行"),
                content=ft.Text(
                    f"确定删除第 {row_number} 行吗？删除会立即写回 TSV，并更新已配置的前后端文件。"
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(
                        "删除",
                        icon=ft.Icons.DELETE_OUTLINE,
                        style=ft.ButtonStyle(bgcolor="#D92D20", color="#FFFFFF"),
                        on_click=delete_row,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def change_page(self, delta: int):
        total_pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.current_page = min(max(0, self.current_page + delta), total_pages - 1)
        self.refresh_table()

    def set_page_size(self, selected_size: int):
        if selected_size not in PAGE_SIZES:
            self.notify("每页显示条数无效。", error=True)
            return
        self.page_size = selected_size
        self.page_size_label.value = f"{selected_size} 条/页"
        self.current_page = 0
        self.refresh_table()
