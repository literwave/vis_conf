"""在配置目录里用 Cursor、OpenAI 或 DeepSeek 直接阅读和修改文件。"""

import uuid

import flet as ft

import ai_agent
from plugin_host import PluginAction, PluginContext

PLUGIN_TITLE = "AI Agent"
PLUGIN_DESCRIPTION = "用 Cursor、OpenAI 或 DeepSeek 在配置目录里直接阅读和修改文件。不安装时没有这项。"


def _saved_text(ctx: PluginContext, key: str) -> str:
    value = ctx.get_setting(key, "")
    return value if isinstance(value, str) else ""


def _blank_conversation() -> dict:
    return {"id": uuid.uuid4().hex, "title": "新对话", "messages": []}


def _conversation_title(messages: list[dict[str, str]], current: str) -> str:
    for item in messages:
        if item.get("role") == "user" and item.get("content", "").strip():
            text = item["content"].strip().replace("\n", " ")
            return text if len(text) <= 18 else text[:18] + "…"
    return current or "新对话"


def load_conversations(saved: object, active_id: object) -> tuple[list[dict], str]:
    conversations: list[dict] = []
    if isinstance(saved, list):
        for item in saved:
            if not isinstance(item, dict):
                continue
            messages = []
            for turn in item.get("messages") or []:
                if (
                    isinstance(turn, dict)
                    and turn.get("role") in {"user", "assistant"}
                    and isinstance(turn.get("content"), str)
                ):
                    messages.append({"role": turn["role"], "content": turn["content"]})
            title = item.get("title")
            conversations.append(
                {
                    "id": item["id"] if isinstance(item.get("id"), str) and item["id"] else uuid.uuid4().hex,
                    "title": title.strip() if isinstance(title, str) and title.strip() else "新对话",
                    "messages": messages,
                }
            )
    if not conversations:
        conversations = [_blank_conversation()]
    selected = active_id if isinstance(active_id, str) else ""
    if not any(item["id"] == selected for item in conversations):
        selected = conversations[-1]["id"]
    return conversations, selected


def register(ctx: PluginContext) -> list[PluginAction]:
    def open_agent(_event) -> None:
        _AgentPanel(ctx).open()

    return [
        PluginAction(
            label=PLUGIN_TITLE,
            icon=ft.Icons.SMART_TOY,
            tooltip=PLUGIN_DESCRIPTION,
            on_click=open_agent,
            desktop_only=True,
        )
    ]


class _AgentPanel:
    def __init__(self, ctx: PluginContext):
        self.ctx = ctx
        self.conversations, self.active_id = load_conversations(
            ctx.get_setting("conversations"),
            ctx.get_setting("active_conversation"),
        )
        self.history = [dict(item) for item in self._active()["messages"]]
        saved_provider = ctx.get_setting("provider", "cursor")
        self.provider = saved_provider if saved_provider in {"cursor", "openai", "deepseek"} else "cursor"
        saved_mode = ctx.get_setting("cursor_mode", "agent")
        self.mode = saved_mode if saved_mode in {"ask", "agent"} else "agent"
        self.models = {
            "cursor": _saved_text(ctx, "cursor_model"),
            "openai": _saved_text(ctx, "openai_model") or ai_agent.API_PROVIDERS["openai"]["default_model"],
            "deepseek": _saved_text(ctx, "deepseek_model") or ai_agent.API_PROVIDERS["deepseek"]["default_model"],
        }
        self.messages = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self.prompt = ft.TextField(
            hint_text="直接描述要做的事。Enter 发送，Shift+Enter 换行",
            multiline=True,
            shift_enter=True,
            min_lines=2,
            max_lines=6,
            expand=True,
        )
        self.send_button = ft.Button("发送", icon=ft.Icons.SEND, on_click=self.send)
        self.prompt.on_submit = self.send
        self.mode_text = ft.Text(self._mode_label(), size=11, color="#667085")
        self.conversation_select = ft.Dropdown(
            value=self.active_id,
            options=self._conversation_options(),
            width=190,
            text_size=12,
            on_select=self._switch_conversation,
        )

    def _mode_label(self) -> str:
        mode_name = "Agent" if self.mode == "agent" else "Ask"
        if self.provider == "cursor":
            model = self.models["cursor"].strip()
            return f"Cursor {mode_name}" + (f" · {model}" if model else "")
        profile = ai_agent.API_PROVIDERS[self.provider]
        return f"{profile['label']} {mode_name} · {self.models[self.provider]}"

    def open(self) -> None:
        directory = self.ctx.configuration_directory() or "尚未选择配置目录"
        dialog = ft.AlertDialog(
            modal=True,
            scrollable=False,
            title=ft.Row(
                [
                    ft.Text(PLUGIN_TITLE),
                    ft.Container(expand=True),
                    self.mode_text,
                    ft.IconButton(
                        icon=ft.Icons.SETTINGS_OUTLINED,
                        tooltip="模型连接",
                        on_click=self.open_settings,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Column(
                [
                    ft.Column(
                        [
                            ft.Text(
                                f"在配置目录里工作：{directory}。Cursor、OpenAI 和 DeepSeek 都可以自己读文件、改文件。",
                                size=11,
                                color="#667085",
                            ),
                            ft.Row(
                                [
                                    self.conversation_select,
                                    ft.OutlinedButton("新对话", on_click=self.new_conversation),
                                    ft.OutlinedButton("删除", on_click=self.delete_conversation),
                                ],
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                    ),
                    self.messages,
                    ft.Row([self.prompt, self.send_button], spacing=8),
                ],
                width=self.ctx.dialog_width(760),
                height=self.ctx.dialog_height(520),
                spacing=10,
            ),
            actions=[
                ft.TextButton("完成", on_click=lambda _: self.ctx.pop_dialog())
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_saved_messages()
        self.ctx.show_dialog(dialog)

    def _active(self) -> dict:
        for item in self.conversations:
            if item["id"] == self.active_id:
                return item
        self.conversations.append(_blank_conversation())
        self.active_id = self.conversations[-1]["id"]
        return self.conversations[-1]

    def _conversation_options(self) -> list[ft.DropdownOption]:
        return [
            ft.DropdownOption(key=item["id"], text=item["title"] or "新对话")
            for item in self.conversations
        ]

    def _remember_active(self) -> None:
        current = self._active()
        current["messages"] = [dict(item) for item in self.history]
        current["title"] = _conversation_title(self.history, current["title"])

    def _persist_conversations(self) -> None:
        self._remember_active()
        if len(self.conversations) > 30:
            del self.conversations[:-30]
            if not any(item["id"] == self.active_id for item in self.conversations):
                self.active_id = self.conversations[-1]["id"]
        self.ctx.set_setting("conversations", self.conversations)
        self.ctx.set_setting("active_conversation", self.active_id)
        self.conversation_select.options = self._conversation_options()
        self.conversation_select.value = self.active_id

    def _show_saved_messages(self) -> None:
        self.messages.controls.clear()
        for item in self.history:
            if item["role"] == "user":
                self._add_message("你", item["content"], "#EEF0FF")
            else:
                self._add_message("Agent", item["content"], "#F8F9FC")

    def new_conversation(self, _=None) -> None:
        if self.send_button.disabled:
            return
        self._persist_conversations()
        created = _blank_conversation()
        self.conversations.append(created)
        self.active_id = created["id"]
        self.history = []
        self.messages.controls.clear()
        self._persist_conversations()
        self.ctx.update()

    def delete_conversation(self, _=None) -> None:
        if self.send_button.disabled:
            return
        if len(self.conversations) == 1:
            self.history = []
            self.messages.controls.clear()
            current = self._active()
            current["messages"] = []
            current["title"] = "新对话"
            self._persist_conversations()
            self.ctx.update()
            return
        index = next(
            position
            for position, item in enumerate(self.conversations)
            if item["id"] == self.active_id
        )
        del self.conversations[index]
        self.active_id = self.conversations[min(index, len(self.conversations) - 1)]["id"]
        self.history = [dict(item) for item in self._active()["messages"]]
        self._show_saved_messages()
        self._persist_conversations()
        self.ctx.update()

    def _switch_conversation(self, event) -> None:
        if self.send_button.disabled:
            self.conversation_select.value = self.active_id
            return
        selected = getattr(event, "control", None)
        conversation_id = getattr(selected, "value", None) or self.conversation_select.value
        if not isinstance(conversation_id, str) or conversation_id == self.active_id:
            return
        if not any(item["id"] == conversation_id for item in self.conversations):
            return
        self._remember_active()
        self.active_id = conversation_id
        self.history = [dict(item) for item in self._active()["messages"]]
        self._show_saved_messages()
        self._persist_conversations()
        self.ctx.update()

    def open_settings(self, _) -> None:
        provider_select = ft.Dropdown(
            label="模型服务",
            value=self.provider,
            options=[
                ft.DropdownOption(key="cursor", text="Cursor"),
                ft.DropdownOption(key="openai", text="OpenAI"),
                ft.DropdownOption(key="deepseek", text="DeepSeek"),
            ],
            width=self.ctx.dialog_width(420),
        )
        mode_select = ft.Dropdown(
            label="模式",
            value=self.mode,
            options=[
                ft.DropdownOption(key="agent", text="Agent（可改文件）"),
                ft.DropdownOption(key="ask", text="Ask（只读）"),
            ],
            width=self.ctx.dialog_width(420),
        )
        model_input = ft.TextField(
            label="模型",
            value=self.models[self.provider],
            hint_text="Cursor 可留空。OpenAI 如 gpt-4o-mini，DeepSeek 如 deepseek-chat",
        )
        api_key_input = ft.TextField(
            label="API Key",
            password=True,
            can_reveal_password=True,
            hint_text="留空则保留已保存的 Key，只写入系统凭据库",
            visible=self.provider != "cursor",
        )

        def show_provider(_event=None) -> None:
            selected = provider_select.value if provider_select.value in self.models else "cursor"
            model_input.value = self.models[selected]
            api_key_input.visible = selected != "cursor"
            api_key_input.value = ""
            self.ctx.update()

        provider_select.on_select = show_provider

        def save(_event) -> None:
            selected = provider_select.value if provider_select.value in self.models else "cursor"
            self.provider = selected
            self.mode = mode_select.value if mode_select.value in {"ask", "agent"} else "agent"
            self.models[selected] = (model_input.value or "").strip()
            api_key = (api_key_input.value or "").strip()
            try:
                if selected != "cursor" and api_key:
                    ai_agent.save_provider_api_key(selected, api_key)
            except RuntimeError as exc:
                self.ctx.notify(str(exc), error=True)
                return
            self.ctx.set_setting("provider", self.provider)
            self.ctx.set_setting("cursor_mode", self.mode)
            self.ctx.set_setting("cursor_model", self.models["cursor"])
            self.ctx.set_setting("openai_model", self.models["openai"])
            self.ctx.set_setting("deepseek_model", self.models["deepseek"])
            self.mode_text.value = self._mode_label()
            self.ctx.pop_dialog()
            self.ctx.update()
            self.ctx.notify("模型连接已保存")

        self.ctx.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("模型连接"),
                content=ft.Column(
                    [provider_select, mode_select, model_input, api_key_input],
                    width=self.ctx.dialog_width(460),
                    tight=True,
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _event: self.ctx.pop_dialog()),
                    ft.Button("保存", on_click=save),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def _add_message(self, label: str, message: str, color: str) -> None:
        self.messages.controls.append(
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

    async def send(self, _) -> None:
        if self.send_button.disabled:
            return
        prompt = (self.prompt.value or "").strip()
        if not prompt:
            self.ctx.notify("请先输入请求。", error=True)
            return
        directory = self.ctx.configuration_directory()
        if not directory:
            self.ctx.notify("请先在导出设置里选择配置文件目录。", error=True)
            return
        self.prompt.value = ""
        self.send_button.disabled = True
        self._add_message("你", prompt, "#EEF0FF")
        service = "Cursor" if self.provider == "cursor" else ai_agent.API_PROVIDERS[self.provider]["label"]
        working = ft.Text(f"{service} 正在配置目录里工作…", size=12, color="#667085")
        self.messages.controls.append(working)
        self.ctx.update()
        try:
            if self.provider == "cursor":
                reply = await ai_agent.run_cursor_workspace(
                    directory,
                    prompt,
                    mode=self.mode,
                    model=self.models["cursor"],
                    history=list(self.history),
                    active_table=self.ctx.active_table_path(),
                )
            else:
                reply = await ai_agent.run_api_workspace(
                    self.provider,
                    directory,
                    prompt,
                    mode=self.mode,
                    model=self.models[self.provider],
                    api_key=ai_agent.load_provider_api_key(self.provider) or "",
                    history=list(self.history),
                    active_table=self.ctx.active_table_path(),
                )
        except (RuntimeError, ValueError, OSError) as exc:
            working.value = f"请求失败：{exc}"
            working.color = "#D92D20"
            self.send_button.disabled = False
            self.ctx.update()
            return
        working.value = reply
        self.history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": reply},
            ]
        )
        self._persist_conversations()
        if self.mode == "agent" and self.ctx.reload_active_table():
            self.messages.controls.append(
                ft.Text("已重新读取当前配置表。", size=12, color="#067647")
            )
        self.send_button.disabled = False
        self.ctx.update()
