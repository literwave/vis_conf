import copy
from typing import Any, Callable

import flet as ft

from agent_apply import prepare_agent_edit
from ai_agent import (
    list_cursor_models,
    load_api_key,
    parse_agent_proposal,
    request_api_proposal,
    request_cursor_proposal,
    save_api_key,
    validate_api_settings,
)


def load_agent_settings(saved: dict[str, Any] | None) -> dict[str, Any]:
    saved_agent_settings = saved if isinstance(saved, dict) else {}
    return {
        "provider": (
            saved_agent_settings.get("provider")
            if saved_agent_settings.get("provider") in {"cursor", "api"}
            else "cursor"
        ),
        "base_url": (
            saved_agent_settings.get("base_url")
            if isinstance(saved_agent_settings.get("base_url"), str)
            else "https://api.openai.com/v1"
        ),
        "model": (
            saved_agent_settings.get("model")
            if isinstance(saved_agent_settings.get("model"), str)
            else ""
        ),
        "cursor_mode": (
            saved_agent_settings.get("cursor_mode")
            if saved_agent_settings.get("cursor_mode") in {"ask", "agent"}
            else "ask"
        ),
        "cursor_model": (
            saved_agent_settings.get("cursor_model")
            if isinstance(saved_agent_settings.get("cursor_model"), str)
            else ""
        ),
    }


def agent_provider_label(agent_settings: dict[str, Any]) -> str:
    if agent_settings["provider"] == "cursor":
        mode_name = "Agent" if agent_settings["cursor_mode"] == "agent" else "Ask"
        model_name = agent_settings["cursor_model"].strip()
        if model_name:
            return f"Cursor Agent CLI（{mode_name} · {model_name}）"
        return f"Cursor Agent CLI（{mode_name}）"
    return f"OpenAI 兼容 API · {agent_settings['model'] or '未设置模型'}"


def create_agent_dialogs(editor) -> tuple[Callable, Callable]:
    """Build the connection dialog and the chat dialog for one editor session."""

    def open_agent_settings(_):
        agent_settings = editor.agent_settings
        provider_select = ft.Dropdown(
            label="连接方式",
            value=agent_settings["provider"],
            options=[
                ft.DropdownOption(key="cursor", text="Cursor Agent CLI"),
                ft.DropdownOption(key="api", text="OpenAI 兼容 API"),
            ],
            width=editor.dialog_width(420),
        )
        cursor_mode_select = ft.Dropdown(
            label="Cursor CLI 模式",
            value=agent_settings["cursor_mode"],
            options=[
                ft.DropdownOption(key="ask", text="Ask（只读问答）"),
                ft.DropdownOption(key="agent", text="Agent（可调用工具）"),
            ],
            width=editor.dialog_width(420),
            visible=agent_settings["provider"] == "cursor",
        )
        cursor_model_select = ft.Dropdown(
            label="Cursor 模型",
            value=agent_settings["cursor_model"].strip() or "auto",
            options=[
                ft.DropdownOption(
                    key=agent_settings["cursor_model"].strip() or "auto",
                    text=agent_settings["cursor_model"].strip() or "Auto（CLI 默认）",
                ),
            ],
            disabled=True,
            enable_filter=True,
            menu_height=320,
            width=editor.dialog_width(420),
            visible=agent_settings["provider"] == "cursor",
        )
        cursor_model_status = ft.Text(
            "正在读取可用模型…",
            size=12,
            color="#667085",
            visible=agent_settings["provider"] == "cursor",
        )
        base_url_input = ft.TextField(
            label="API 基础地址",
            value=agent_settings["base_url"],
            hint_text="例如 https://api.openai.com/v1",
            visible=agent_settings["provider"] == "api",
        )
        model_input = ft.TextField(
            label="模型名称",
            value=agent_settings["model"],
            hint_text="例如 gpt-4o-mini",
            visible=agent_settings["provider"] == "api",
        )
        api_key_input = ft.TextField(
            label="API Key",
            password=True,
            can_reveal_password=True,
            hint_text="留空则保留已保存的 Key",
            visible=agent_settings["provider"] == "api",
        )
        credential_status = ft.Text(size=12, color="#667085")
        api_controls = ft.Column(
            [base_url_input, model_input, api_key_input, credential_status],
            spacing=8,
            visible=agent_settings["provider"] == "api",
        )
        api_privacy_note = ft.Text(
            "API Key 仅保存到系统凭据库，不会写入应用设置文件。"
            "发送请求时会将当前页配置数据传给该 API 地址。",
            size=11,
            color="#667085",
            visible=agent_settings["provider"] == "api",
        )
        remove_key_button = ft.OutlinedButton(
            "删除已保存的 API Key",
            icon=ft.Icons.DELETE_OUTLINE,
            visible=agent_settings["provider"] == "api",
        )
        provider_help = ft.Text(
            "使用 Cursor CLI 自己的登录状态，并在临时目录中运行；"
            "当前表格数据作为提示内容提供给 CLI。",
            size=12,
            color="#667085",
            visible=agent_settings["provider"] == "cursor",
        )
        cursor_agent_warning = ft.Container(
            content=ft.Text(
                "Agent 模式点「应用到当前表」后会修改当前表并写入 TSV。"
                "它也可以调用 Cursor CLI 的本机工具，命令会自动执行。"
                "请仅在信任请求内容时使用。",
                size=12,
                color="#93370D",
            ),
            bgcolor="#FFFAEB",
            border_radius=8,
            padding=10,
            visible=(
                agent_settings["provider"] == "cursor"
                and agent_settings["cursor_mode"] == "agent"
            ),
        )

        def refresh_provider_help(_=None):
            is_api = provider_select.value == "api"
            api_controls.visible = is_api
            provider_help.visible = not is_api
            cursor_mode_select.visible = not is_api
            cursor_model_select.visible = not is_api
            cursor_model_status.visible = not is_api
            cursor_agent_warning.visible = (
                not is_api and cursor_mode_select.value == "agent"
            )
            provider_help.value = (
                "使用配置的模型服务商 API；当前页数据会发送到该服务。"
                if is_api
                else "使用 Cursor CLI 自己的登录状态，并在临时目录中运行；"
                "当前表格数据作为提示内容提供给 CLI。"
            )
            api_privacy_note.visible = is_api
            remove_key_button.visible = is_api
            editor.page.update()

        provider_select.on_select = refresh_provider_help
        cursor_mode_select.on_select = refresh_provider_help

        def refresh_credential_status():
            try:
                credential_status.value = (
                    "系统凭据库中已保存 API Key。"
                    if load_api_key()
                    else "尚未保存 API Key。"
                )
                credential_status.color = "#667085"
            except RuntimeError as exc:
                credential_status.value = str(exc)
                credential_status.color = "#D92D20"

        refresh_credential_status()

        def save_agent_connection(_):
            provider = provider_select.value or "cursor"
            if provider == "api":
                try:
                    base_url, model = validate_api_settings(
                        base_url_input.value or "",
                        model_input.value or "",
                    )
                except ValueError as exc:
                    editor.notify(str(exc), error=True)
                    return
                api_key = (api_key_input.value or "").strip()
                if not api_key:
                    try:
                        if not load_api_key():
                            editor.notify("请填写并保存 API Key。", error=True)
                            return
                    except RuntimeError as exc:
                        editor.notify(str(exc), error=True)
                        return
                if api_key:
                    try:
                        save_api_key(api_key)
                    except RuntimeError as exc:
                        editor.notify(str(exc), error=True)
                        return
                agent_settings.update(
                    {"provider": provider, "base_url": base_url, "model": model}
                )
            else:
                cursor_model = (cursor_model_select.value or "").strip()
                if cursor_model == "auto":
                    cursor_model = ""
                if any(character.isspace() for character in cursor_model):
                    editor.notify("Cursor 模型 ID 不能包含空白。例如 grok-4.7-high。", error=True)
                    return
                agent_settings.update(
                    {
                        "provider": "cursor",
                        "cursor_mode": cursor_mode_select.value or "ask",
                        "cursor_model": cursor_model,
                    }
                )
            editor.save_export_settings()
            editor.refresh_agent_provider_labels()
            editor.page.pop_dialog()
            editor.notify("Agent 连接设置已保存")

        def remove_api_key(_):
            try:
                if load_api_key():
                    save_api_key(None)
                api_key_input.value = ""
                refresh_credential_status()
                editor.page.update()
            except RuntimeError as exc:
                editor.notify(str(exc), error=True)

        remove_key_button.on_click = remove_api_key
        editor.show_alert_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("AI 服务与连接"),
                content=ft.Column(
                    [
                        provider_select,
                        cursor_mode_select,
                        cursor_model_select,
                        cursor_model_status,
                        provider_help,
                        cursor_agent_warning,
                        api_controls,
                        api_privacy_note,
                        remove_key_button,
                    ],
                    tight=True,
                    spacing=10,
                    width=editor.dialog_width(520),
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=[ft.TextButton("保存连接", on_click=save_agent_connection)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

        async def load_cursor_model_options():
            saved_model = agent_settings["cursor_model"].strip()
            try:
                models = await list_cursor_models()
            except RuntimeError as exc:
                cursor_model_status.value = str(exc)
                cursor_model_status.color = "#D92D20"
                cursor_model_select.disabled = False
                editor.page.update()
                return
            listed_ids = {model_id for model_id, _ in models}
            options = [
                ft.DropdownOption(
                    key=model_id,
                    text="Auto（CLI 默认）" if model_id == "auto" else f"{label}（{model_id}）",
                )
                for model_id, label in models
            ]
            if saved_model and saved_model not in listed_ids:
                options.insert(
                    0,
                    ft.DropdownOption(
                        key=saved_model,
                        text=f"{saved_model}（已保存，当前 CLI 未列出）",
                    ),
                )
            cursor_model_select.options = options
            cursor_model_select.value = saved_model or "auto"
            cursor_model_select.disabled = False
            cursor_model_status.value = f"共 {len(models)} 个模型，可输入名称筛选。"
            cursor_model_status.color = "#667085"
            editor.page.update()

        editor.page.run_task(load_cursor_model_options)

    def open_ai_agent(_):
        history: list[dict[str, str]] = []
        pending_apply: list = []
        page_height = editor.page.height if editor.page.height and editor.page.height > 0 else 700
        window_height = getattr(editor.page.window, "height", None)
        if isinstance(window_height, (int, float)) and window_height > 0:
            page_height = min(int(page_height), int(window_height) - 48)
        messages_height = max(100, min(200, int(page_height) - 580))
        messages_view = ft.Column(
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            height=messages_height,
            expand=False,
        )
        prompt_input = ft.TextField(
            hint_text="描述你想调整的配置，例如：给这些道具补充简短描述。Enter 发送，Shift+Enter 换行",
            multiline=True,
            shift_enter=True,
            min_lines=2,
            max_lines=5,
            expand=True,
        )
        send_button = ft.Button("发送", icon=ft.Icons.SEND)
        pending_preview = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        provider_text = ft.Text(agent_provider_label(editor.agent_settings), size=11, color="#667085")
        editor.agent_provider_labels.append(provider_text)

        def add_agent_message(label: str, message: str, color: str):
            messages_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(label, size=11, weight=ft.FontWeight.W_600),
                            ft.Text(message, size=13, selectable=True),
                        ],
                        spacing=4,
                    ),
                    bgcolor=color,
                    border_radius=10,
                    padding=12,
                )
            )

        async def send_agent_message(_):
            if send_button.disabled:
                return
            prompt = (prompt_input.value or "").strip()
            if not prompt:
                editor.notify("请先输入 Agent 请求。", error=True)
                return
            if not editor.columns:
                editor.notify("当前配置表没有可用字段。", error=True)
                return
            prompt_input.value = ""
            send_button.disabled = True
            add_agent_message("你", prompt, "#EEF0FF")
            working_message = ft.Text("Agent 正在分析当前页…", size=12, color="#667085")
            messages_view.controls.append(working_message)
            editor.page.update()

            start = editor.current_page() * editor.page_size()
            end = min(start + editor.page_size(), len(editor.rows))
            visible_rows = [
                (index + 1, copy.deepcopy(editor.rows[index]))
                for index in range(start, end)
            ]
            prior_history = copy.deepcopy(history)
            try:
                if editor.agent_settings["provider"] == "cursor":
                    response = await request_cursor_proposal(
                        prior_history,
                        editor.columns.copy(),
                        editor.data_types.copy(),
                        editor.source_name(),
                        visible_rows,
                        prompt,
                        editor.agent_settings["cursor_mode"],
                        editor.agent_settings["cursor_model"],
                        editor.targets.copy(),
                        editor.annotations.copy(),
                    )
                else:
                    base_url, model = validate_api_settings(
                        editor.agent_settings["base_url"],
                        editor.agent_settings["model"],
                    )
                    api_key = load_api_key()
                    if not api_key:
                        raise RuntimeError(
                            "系统凭据库中没有 API Key。请打开「AI 服务与连接」进行配置。"
                        )
                    response = await request_api_proposal(
                        base_url,
                        model,
                        api_key,
                        prior_history,
                        editor.columns.copy(),
                        editor.data_types.copy(),
                        editor.source_name(),
                        visible_rows,
                        prompt,
                        editor.targets.copy(),
                        editor.annotations.copy(),
                    )
                proposal = parse_agent_proposal(response)
            except (RuntimeError, ValueError, OSError) as exc:
                working_message.value = f"请求失败：{exc}"
                working_message.color = "#D92D20"
                send_button.disabled = False
                editor.page.update()
                return

            working_message.value = proposal["message"]
            history.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": response},
                ]
            )
            pending_preview.controls.clear()
            if not proposal["changes"] and not proposal["column_additions"] and not proposal["column_deletions"]:
                pending_apply.clear()
                pending_preview.controls.append(
                    ft.Text("没有建议的修改。", size=12, color="#667085")
                )
                show_idle_actions()
                send_button.disabled = False
                editor.page.update()
                return

            error, prepared = prepare_agent_edit(
                editor.columns,
                editor.data_types,
                editor.targets,
                editor.annotations,
                editor.key_columns,
                editor.rows,
                proposal,
                {number for number, _ in visible_rows},
                editor.parse_data_value,
                editor.display_value,
                editor.type_labels,
                editor.target_labels,
            )
            if error or prepared is None:
                pending_apply.clear()
                pending_preview.controls.append(
                    ft.Text(error or "没有建议的修改。", size=12, color="#D92D20")
                )
                show_idle_actions()
                send_button.disabled = False
                editor.page.update()
                return

            def apply_agent_proposal(_, save_file=False):
                if (
                    editor.source_name() != editor.source_text.value
                    or editor.columns != prepared.original_columns
                    or editor.data_types != prepared.original_types
                    or editor.targets != prepared.original_targets
                    or editor.annotations != prepared.original_annotations
                    or editor.key_columns != prepared.original_keys
                    or editor.rows != prepared.original_rows
                ):
                    pending_apply.clear()
                    pending_preview.controls.clear()
                    pending_preview.controls.append(
                        ft.Text(
                            "配置表已变化，旧预览已作废，请重新请求 Agent。",
                            size=12,
                            color="#D92D20",
                        )
                    )
                    show_idle_actions()
                    editor.page.update()
                    return
                editor.record_row_undo()
                editor.columns[:] = prepared.columns
                editor.data_types[:] = prepared.data_types
                editor.targets[:] = prepared.targets
                editor.annotations[:] = prepared.annotations
                editor.key_columns[:] = prepared.key_columns
                editor.rows[:] = prepared.rows
                editor.mark_active_table_modified()
                if (
                    prepared.columns != prepared.original_columns
                    or prepared.key_columns != prepared.original_keys
                ):
                    editor.save_export_settings()
                editor.refresh_table()
                refresh_columns = editor.column_manager_refresh()
                if refresh_columns is not None:
                    refresh_columns()
                pending_apply.clear()
                pending_preview.controls.clear()
                saved = editor.persist_active_table() if save_file else ""
                pending_preview.controls.append(
                    ft.Text(
                        (
                            f"已完成 {len(prepared.preview_lines)} 项修改，{saved} Ctrl+Z 可撤销。"
                            if save_file
                            else f"已应用 {len(prepared.preview_lines)} 项修改，可以继续描述下一步。Ctrl+Z 可撤销。"
                        ),
                        size=12,
                        color="#067647",
                    )
                )
                show_idle_actions()
                editor.page.update()

            agent_mode = (
                editor.agent_settings["provider"] == "cursor"
                and editor.agent_settings["cursor_mode"] == "agent"
            )
            ask_mode = (
                editor.agent_settings["provider"] == "cursor"
                and not agent_mode
            )
            pending_apply.clear()
            if not ask_mode:
                pending_apply[:] = [
                    lambda event, save_file=agent_mode: apply_agent_proposal(
                        event, save_file=save_file
                    )
                ]
            if ask_mode:
                preview_title = (
                    f"修改预览（{len(prepared.preview_lines)} 项）。"
                    "Ask 模式只给预览，不能应用到当前表。"
                )
            elif agent_mode:
                preview_title = (
                    f"修改预览（{len(prepared.preview_lines)} 项）。"
                    "点「应用到当前表」后写入当前表并保存。"
                )
            else:
                preview_title = (
                    f"修改预览（{len(prepared.preview_lines)} 项），"
                    "点「应用到当前表」后才改表格"
                )
            pending_preview.controls.extend(
                [
                    ft.Text(
                        preview_title,
                        size=13,
                        weight=ft.FontWeight.W_600,
                    ),
                    *[
                        ft.Text(line, size=12, selectable=True)
                        for line in prepared.preview_lines
                    ],
                ]
            )
            if ask_mode:
                show_idle_actions()
            else:
                show_pending_actions()
            send_button.disabled = False
            editor.page.update()

        def discard_agent_proposal(_):
            pending_apply.clear()
            pending_preview.controls.clear()
            show_idle_actions()
            editor.page.update()

        def sync_preview_height():
            pending_preview.height = 180 if len(pending_preview.controls) > 8 else None

        def show_idle_actions():
            sync_preview_height()
            agent_dialog.actions = [ft.TextButton("完成", on_click=request_close)]
            agent_dialog.actions_alignment = ft.MainAxisAlignment.END

        def show_pending_actions():
            sync_preview_height()
            agent_dialog.actions = [
                ft.TextButton("放弃修改", on_click=discard_agent_proposal),
                ft.Button(
                    "应用到当前表",
                    icon=ft.Icons.CHECK,
                    on_click=lambda event: pending_apply[-1](event),
                ),
                ft.TextButton("完成", on_click=request_close),
            ]
            agent_dialog.actions_alignment = ft.MainAxisAlignment.END
            editor.page.update()

        def request_close(_=None):
            pending_apply.clear()
            editor.page.pop_dialog()

        send_button.on_click = send_agent_message
        prompt_input.on_submit = send_agent_message
        settings_button = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            tooltip="AI 服务与连接",
            on_click=open_agent_settings,
        )
        page_start = editor.current_page() * editor.page_size() + 1 if editor.rows else 0
        page_end = min((editor.current_page() + 1) * editor.page_size(), len(editor.rows))
        agent_mode = (
            editor.agent_settings["provider"] == "cursor"
            and editor.agent_settings["cursor_mode"] == "agent"
        )
        if agent_mode:
            workflow_hint = (
                "当前是 Agent 模式，确认后点「应用到当前表」，"
                "修改会写进当前表并保存到 TSV。"
            )
        elif editor.agent_settings["provider"] == "cursor":
            workflow_hint = "当前是 Ask 模式，只给出预览，不能应用到当前表。"
        else:
            workflow_hint = "确认后点「应用到当前表」才会改当前表。"
        agent_dialog = ft.AlertDialog(
            modal=True,
            scrollable=False,
            inset_padding=ft.Padding.symmetric(vertical=8, horizontal=24),
            title_padding=ft.Padding(20, 8, 8, 0),
            content_padding=ft.Padding(20, 8, 20, 16),
            title=ft.Row(
                [
                    ft.Text("AI Agent"),
                    ft.Container(expand=True),
                    provider_text,
                    settings_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        f"只发送当前表的第 {page_start}–{page_end} 行。{workflow_hint}",
                        size=11,
                        color="#667085",
                    ),
                    messages_view,
                    pending_preview,
                    ft.Row([prompt_input, send_button], spacing=8),
                ],
                width=editor.dialog_width(760),
                spacing=10,
            ),
            actions=[ft.TextButton("完成", on_click=request_close)],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(left=16, right=16, bottom=12, top=0),
        )
        editor.show_alert_dialog(agent_dialog, on_close=request_close)

    return open_agent_settings, open_ai_agent
