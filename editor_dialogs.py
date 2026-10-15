from pathlib import Path
import flet as ft
from typing import Callable


class EditorDialogs:
    def dialog_width(self, preferred: int) -> int:
        available_width = self.page.width
        if available_width is None or available_width <= 0:
            return preferred
        return max(220, min(preferred, int(available_width) - 96))

    def dialog_height(self, preferred: int, margin: int = 80) -> int:
        available_height = self.page.height
        if available_height is None or available_height <= 0:
            return preferred
        return max(240, min(preferred, int(available_height) - margin))

    def show_alert_dialog(
        self, dialog: ft.AlertDialog, on_close: Callable[[], None] | None = None
    ):

        def close_dialog(_):
            if on_close is not None:
                on_close()
            else:
                self.page.pop_dialog()

        dialog.title = ft.Row(
            [
                dialog.title or ft.Container(),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=18,
                    tooltip="关闭",
                    on_click=close_dialog,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.page.show_dialog(dialog)

    def available_initial_directory(self, directory: str | None) -> str | None:
        if not directory:
            return None
        return directory if Path(directory).is_dir() else None

    def notify(self, message: str, error: bool = False):
        self.page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor="#D92D20" if error else "#344054",
                duration=3000,
            )
        )

    def metric_card(self, label: str, value: ft.Control, icon: str, tint: str):
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [ft.Text(label, size=12, color="#667085"), value], spacing=8
                    ),
                    ft.Container(
                        content=ft.Icon(icon, color=tint, size=20),
                        bgcolor="#F2F4F7",
                        border_radius=12,
                        padding=12,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#FFFFFF",
            border=ft.Border.all(1, "#EAECF0"),
            border_radius=14,
            padding=18,
            expand=True,
        )
