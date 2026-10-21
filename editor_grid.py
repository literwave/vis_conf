import flet as ft
from typing import Any
from schema import DATA_TYPES, EXPORT_TARGETS
from table_file import _display_value_for_type, resolve_image_path


class EditorGrid:
    def refresh_table(self):
        total_pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, total_pages - 1)
        start = self.current_page * self.page_size
        visible_rows = self.rows[start : start + self.page_size]
        viewport_width = (
            getattr(self.page, "width", None)
            or getattr(self.page.window, "width", None)
            or 1280
        )
        available_width = max(600, viewport_width - 320)
        row_number_width = 82
        column_width = max(
            120, (available_width - row_number_width) / max(1, len(self.columns))
        )
        grid_width = row_number_width + column_width * len(self.columns)
        grid_border = "#E4E7EC"

        def metadata_selector(
            value: str, options: dict[str, str], on_change, kind: str
        ):
            if kind == "type":
                background, foreground = ("#EEF2FF", "#4F46E5")
            else:
                background, foreground = {
                    "both": ("#ECFDF3", "#027A48"),
                    "backend": ("#EFF8FF", "#175CD3"),
                    "frontend": ("#FFF7ED", "#C2410C"),
                }[value]

            def select_option(selected: str):
                on_change(selected)
                self.refresh_table()

            return ft.PopupMenuButton(
                content=ft.Container(
                    content=ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    options[value],
                                    size=10,
                                    color=foreground,
                                    weight=ft.FontWeight.W_500,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Icon(
                                    ft.Icons.KEYBOARD_ARROW_DOWN,
                                    size=14,
                                    color=foreground,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=1,
                            tight=True,
                        ),
                        bgcolor=background,
                        border_radius=12,
                        padding=ft.Padding(8, 3, 6, 3),
                        border=ft.Border.all(
                            1,
                            (
                                "#C7D2FE"
                                if kind == "type"
                                else {
                                    "both": "#ABEFC6",
                                    "backend": "#B2DDFF",
                                    "frontend": "#FED7AA",
                                }[value]
                            ),
                        ),
                    ),
                    width=column_width,
                    alignment=ft.Alignment(0, 0),
                ),
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row(
                            [
                                ft.Container(width=16),
                                ft.Text(
                                    label,
                                    size=12,
                                    color="#344054",
                                    expand=True,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.CHECK,
                                        size=15,
                                        color="#5B6CFF",
                                        opacity=1 if key == value else 0,
                                    ),
                                    width=16,
                                    alignment=ft.Alignment(0, 0),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=0,
                        ),
                        height=34,
                        padding=ft.Padding(12, 0, 12, 0),
                        on_click=lambda _, selected=key: select_option(selected),
                    )
                    for key, label in options.items()
                ],
                menu_position=ft.PopupMenuPosition.UNDER,
                padding=0,
                bgcolor="#FFFFFF",
                shadow_color="#1018281A",
                elevation=3,
                menu_padding=4,
                size_constraints=ft.BoxConstraints(
                    min_width=column_width, max_width=column_width
                ),
                shape=ft.RoundedRectangleBorder(
                    side=ft.BorderSide(1, "#EAECF0"), radius=10
                ),
                width=column_width,
                height=30,
                tooltip="点击修改",
                style=ft.ButtonStyle(
                    padding=0,
                    bgcolor="transparent",
                    overlay_color={
                        ft.ControlState.HOVERED: (
                            "#E0E7FF" if kind == "type" else "#E4E7EC"
                        ),
                        ft.ControlState.PRESSED: (
                            "#C7D2FE" if kind == "type" else "#D0D5DD"
                        ),
                    },
                    shape=ft.RoundedRectangleBorder(radius=14),
                    mouse_cursor=ft.MouseCursor.CLICK,
                    enable_feedback=True,
                ),
            )

        header_cells = [
            ft.Container(
                content=ft.Text(
                    name,
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color="#475467",
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                width=column_width,
                height=42,
                alignment=ft.Alignment(0, 0),
                padding=ft.Padding(12, 0, 8, 0),
                bgcolor="#F8FAFC",
                tooltip="点击修改字段名",
                ink=True,
                on_click=lambda _, index=index: self.edit_column_name(index),
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for index, name in enumerate(self.columns)
        ]
        data_type_cells = [
            ft.Container(
                content=metadata_selector(
                    data_type,
                    DATA_TYPES,
                    lambda selected, index=index: self.set_column_type(index, selected),
                    "type",
                ),
                width=column_width,
                height=34,
                alignment=ft.Alignment(0, 0),
                bgcolor="#F8FAFC",
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for index, data_type in enumerate(self.data_types)
        ]
        target_cells = [
            ft.Container(
                content=metadata_selector(
                    target,
                    EXPORT_TARGETS,
                    lambda selected, index=index: self.set_column_target(
                        index, selected
                    ),
                    "target",
                ),
                width=column_width,
                height=34,
                alignment=ft.Alignment(0, 0),
                bgcolor="#F8FAFC",
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for index, target in enumerate(self.targets)
        ]
        annotation_cells = [
            ft.Container(
                content=ft.Text(
                    annotation or "点击添加注释",
                    size=11,
                    color="#667085" if annotation else "#98A2B3",
                    text_align=ft.TextAlign.CENTER,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                width=column_width,
                height=34,
                alignment=ft.Alignment(0, 0),
                bgcolor="#F8FAFC",
                on_click=lambda _, index=index: self.edit_annotation(index),
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for index, annotation in enumerate(self.annotations)
        ]

        def create_data_cell(
            row: dict[str, Any],
            column: str,
            column_index: int,
            row_index: int,
            is_selected: bool,
        ) -> ft.Container:
            value = row.get(column)
            image_path = resolve_image_path(
                value, self.active_table_path, getattr(self, "ui_directory", None)
            )
            cell_content: ft.Control
            if image_path is not None:
                cell_content = ft.Image(
                    src=str(image_path),
                    width=28,
                    height=28,
                    fit=ft.BoxFit.CONTAIN,
                    tooltip=str(value),
                    error_content=ft.Icon(
                        ft.Icons.BROKEN_IMAGE_OUTLINED, size=18, color="#98A2B3"
                    ),
                )
            else:
                cell_content = ft.Text(
                    _display_value_for_type(value, self.data_types[column_index]),
                    size=13,
                    color="#344054",
                    text_align=ft.TextAlign.CENTER,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            return ft.Container(
                content=cell_content,
                width=column_width,
                height=42,
                alignment=ft.Alignment(0, 0),
                bgcolor=(
                    "#EEF0FF"
                    if is_selected
                    else "#FFFFFF" if row_index % 2 == 0 else "#FCFCFD"
                ),
                on_click=lambda _, selected_row=row, selected_column=column: self.edit_cell(
                    selected_row, selected_column
                ),
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )

        grid_rows = []
        for index, row in enumerate(visible_rows):
            row_index = start + index
            is_selected = self.selected_row_index == row_index
            row_control = ft.Row(
                [
                    ft.Draggable(
                        content=ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.DRAG_INDICATOR,
                                        size=18,
                                        color="#667085",
                                        tooltip="按住并拖动以调整行顺序",
                                    ),
                                    ft.Text(
                                        str(row_index + 1),
                                        size=11,
                                        color="#4F46E5" if is_selected else "#98A2B3",
                                        expand=True,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        icon_size=14,
                                        icon_color="#98A2B3",
                                        tooltip="删除此行",
                                        on_click=lambda _, selected_row=row: self.confirm_delete_row(
                                            selected_row
                                        ),
                                        style=ft.ButtonStyle(
                                            padding=2,
                                            overlay_color={
                                                ft.ControlState.HOVERED: "#FEE4E2",
                                                ft.ControlState.PRESSED: "#FECDCA",
                                            },
                                            icon_color={
                                                ft.ControlState.HOVERED: "#D92D20",
                                                ft.ControlState.PRESSED: "#B42318",
                                            },
                                            enable_feedback=True,
                                        ),
                                    ),
                                ],
                                spacing=0,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            width=row_number_width,
                            height=42,
                            alignment=ft.Alignment(0, 0),
                            bgcolor="#EEF0FF" if is_selected else "#F8FAFC",
                            on_click=lambda _, selected_index=row_index: self.select_row(
                                selected_index
                            ),
                            border=ft.Border.only(
                                right=ft.BorderSide(1, grid_border),
                                bottom=ft.BorderSide(1, grid_border),
                            ),
                        ),
                        group="configuration-row",
                        data=str(row_index),
                        axis=ft.Axis.VERTICAL,
                        affinity=ft.Axis.VERTICAL,
                        content_feedback=ft.Container(
                            content=ft.Text(
                                f"第 {row_index + 1} 行", color="#344054", size=12
                            ),
                            bgcolor="#FFFFFF",
                            border=ft.Border.all(1, "#D0D5DD"),
                            border_radius=6,
                            padding=8,
                        ),
                    ),
                    *[
                        create_data_cell(
                            row, column, column_index, row_index, is_selected
                        )
                        for column_index, column in enumerate(self.columns)
                    ],
                ],
                spacing=0,
            )
            grid_rows.append(
                ft.DragTarget(
                    content=row_control,
                    group="configuration-row",
                    on_accept=lambda event, target_index=row_index: self.reorder_row(
                        event, target_index
                    ),
                )
            )
        add_row_control = ft.Row(
            [
                ft.Container(
                    content=ft.Icon(ft.Icons.ADD, size=16, color="#5B6CFF"),
                    width=row_number_width,
                    height=42,
                    alignment=ft.Alignment(0, 0),
                    bgcolor="#F8FAFC",
                    on_click=self.add_row,
                    border=ft.Border.only(
                        right=ft.BorderSide(1, grid_border),
                        bottom=ft.BorderSide(1, grid_border),
                    ),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ADD, size=15, color="#5B6CFF"),
                            ft.Text("新增一行", size=12, color="#5B6CFF"),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    width=column_width * max(1, len(self.columns)),
                    height=42,
                    alignment=ft.Alignment(0, 0),
                    bgcolor="#FFFFFF",
                    on_click=self.add_row,
                    border=ft.Border.only(bottom=ft.BorderSide(1, grid_border)),
                ),
            ],
            spacing=0,
        )
        grid = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.DRAG_INDICATOR,
                                            size=14,
                                            color="#98A2B3",
                                            tooltip="拖动行首手柄调整顺序",
                                        ),
                                        ft.Text("#", size=11, color="#98A2B3"),
                                    ],
                                    spacing=2,
                                    tight=True,
                                ),
                                width=row_number_width,
                                height=42,
                                alignment=ft.Alignment(0, 0),
                                bgcolor="#F8FAFC",
                                border=ft.Border.only(
                                    right=ft.BorderSide(1, grid_border),
                                    bottom=ft.BorderSide(1, grid_border),
                                ),
                            ),
                            *header_cells,
                        ],
                        spacing=0,
                    ),
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text("类型", size=10, color="#98A2B3"),
                                width=row_number_width,
                                height=34,
                                alignment=ft.Alignment(0, 0),
                                bgcolor="#F8FAFC",
                                border=ft.Border.only(
                                    right=ft.BorderSide(1, grid_border),
                                    bottom=ft.BorderSide(1, grid_border),
                                ),
                            ),
                            *data_type_cells,
                        ],
                        spacing=0,
                    ),
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text("导出端", size=10, color="#98A2B3"),
                                width=row_number_width,
                                height=34,
                                alignment=ft.Alignment(0, 0),
                                bgcolor="#F8FAFC",
                                border=ft.Border.only(
                                    right=ft.BorderSide(1, grid_border),
                                    bottom=ft.BorderSide(1, grid_border),
                                ),
                            ),
                            *target_cells,
                        ],
                        spacing=0,
                    ),
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text("注释", size=10, color="#98A2B3"),
                                width=row_number_width,
                                height=34,
                                alignment=ft.Alignment(0, 0),
                                bgcolor="#F8FAFC",
                                border=ft.Border.only(
                                    right=ft.BorderSide(1, grid_border),
                                    bottom=ft.BorderSide(1, grid_border),
                                ),
                            ),
                            *annotation_cells,
                        ],
                        spacing=0,
                    ),
                    *grid_rows,
                    add_row_control,
                ],
                spacing=0,
                tight=True,
            ),
            width=grid_width,
            border=ft.Border.all(1, grid_border),
            bgcolor="#FFFFFF",
        )
        horizontal_scroll = getattr(self, "table_horizontal_scroll", None)
        if horizontal_scroll is None:
            horizontal_scroll = ft.Row(
                expand=True,
                scroll=ft.Scrollbar(
                    thumb_visibility=True,
                    track_visibility=True,
                    interactive=True,
                    thickness=12,
                    radius=6,
                    orientation=ft.ScrollbarOrientation.BOTTOM,
                ),
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            self.table_horizontal_scroll = horizontal_scroll
        horizontal_scroll.controls = [
            ft.Container(
                width=grid_width,
                padding=ft.Padding.only(bottom=16),
                content=ft.Column(
                    [grid],
                    scroll=ft.ScrollMode.AUTO,
                    spacing=0,
                ),
            )
        ]
        self.table_area.controls = [horizontal_scroll]
        self.row_count_text.value = f"{len(self.rows):,}"
        self.column_count_text.value = str(len(self.columns))
        self.table_status.value = f"显示第 {(start + 1 if self.rows else 0)}–{start + len(visible_rows)} 行，共 {len(self.rows)} 行 · 点击单元格编辑"
        self.page_status.value = f"共 {len(self.rows)} 条记录"
        self.page_number_text.value = f"{self.current_page + 1} / {total_pages}"
        self.update_row_action_buttons()
        self.page.update()

    def apply_responsive_layout(self):
        width = self.page.width if self.page.width and self.page.width > 0 else 1024
        height = self.page.height if self.page.height and self.page.height > 0 else 768
        compact = width < 820
        self.configuration_file_list_container.height = max(
            96, min(240, int(height - 500))
        )
        self.sidebar.visible = not compact
        self.mobile_configuration_button.visible = compact
        self.header.padding = (
            ft.Padding(14, 16, 14, 12) if compact else ft.Padding(28, 22, 28, 18)
        )
        self.header_title.controls[0].size = 20 if compact else 23
        self.header_content.run_spacing = 8 if compact else 10
        self.header_content.wrap = compact
        self.header_spacer.visible = not compact
        self.header_actions.spacing = 6 if compact else 8
        self.content_body.padding = (
            ft.Padding(12, 0, 12, 12) if compact else ft.Padding(28, 0, 28, 24)
        )
        for card in self.metric_cards:
            card.expand = not compact
            card.width = max(132, int((width - 44) / 2)) if compact else None
            card.padding = 12 if compact else 18
        self.table_card.padding = 12 if compact else 18
        self.metrics_row.wrap = compact
        self.table_header_row.run_spacing = 6 if compact else 8
        self.table_header_row.wrap = compact
        self.table_header_spacer.visible = not compact
        self.table_footer_row.wrap = compact
        self.table_status.visible = not compact
        self.table_footer_status.expand = not compact

    def handle_resize(self, _):
        self.apply_responsive_layout()
        self.refresh_table()
