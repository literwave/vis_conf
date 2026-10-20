"""编辑 proto 协议和字段，并导出 pb、C# 和 net_pb。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import flet as ft

from plugin_host import PluginAction, PluginContext

PLUGIN_TITLE = "协议"
PLUGIN_DESCRIPTION = "编辑 proto 协议和字段，并导出 pb、C# 和 net_pb。"

SCALAR_TYPES = (
    "int32",
    "int64",
    "uint32",
    "uint64",
    "sint32",
    "sint64",
    "fixed32",
    "fixed64",
    "sfixed32",
    "sfixed64",
    "float",
    "double",
    "bool",
    "string",
    "bytes",
)
FIELD_RE = re.compile(
    r"(repeated\s+)?([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\s*=\s*(\d+)\s*;\s*(?://\s*(.*))?$"
)
MAP_FIELD_RE = re.compile(
    r"map\s*<\s*([A-Za-z_][\w.]*)\s*,\s*([A-Za-z_][\w.]*)\s*>\s+"
    r"([A-Za-z_]\w*)\s*=\s*(\d+)\s*;\s*(?://\s*(.*))?$"
)
NAME_RE = re.compile(r"[A-Za-z_]\w*")
TYPE_RE = re.compile(r"[A-Za-z_][\w.]*")
MAP_KEY_TYPES = (
    "int32",
    "int64",
    "uint32",
    "uint64",
    "sint32",
    "sint64",
    "fixed32",
    "fixed64",
    "sfixed32",
    "sfixed64",
    "bool",
    "string",
)
FIELD_PADDING = ft.Padding(10, 8, 10, 8)
SUGGESTION_HINT = "点类型框后按输入模糊匹配。点候选填入，只剩一个时回车补全；保存或导出时，不存在的类型会报错。"


class ProtoParseError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"第 {line} 行：{message}")
        self.line = line


@dataclass
class ProtoField:
    repeated: bool
    type_name: str
    name: str
    number: int | None
    comment: str = ""
    map_key: str = ""
    map_value: str = ""
    map_value_repeated: bool = False


@dataclass
class ProtoMessage:
    name: str
    comment: str
    fields: list[ProtoField] = field(default_factory=list)


@dataclass
class ProtoDocument:
    package: str
    file_comment: str
    imports: list[str]
    messages: list[ProtoMessage]
    dirty: bool = False


def _is_protocol_tools(path: Path) -> bool:
    return (path / "script" / "extractlua.py").is_file() and (
        path / "script" / "extractluapb.py"
    ).is_file()


def find_protocol_tools(starts: list[Path | str | None]) -> Path | None:
    seen: set[str] = set()
    for start in starts:
        if not start:
            continue
        current = Path(start)
        try:
            current = current.resolve()
        except OSError:
            continue
        if current.is_file():
            current = current.parent
        for candidate in (current, *current.parents):
            key = os.path.normcase(str(candidate))
            if key in seen:
                break
            seen.add(key)
            if _is_protocol_tools(candidate):
                return candidate
            nested = candidate / "ptotools"
            if _is_protocol_tools(nested):
                return nested
    return None


def find_proto_directory(tools_dir: Path) -> Path | None:
    candidates = [
        tools_dir / "proto" / "proto_desc",
        tools_dir.parent / "proto",
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.proto")):
            return candidate
    return None


def protocol_desc_directory(tools_dir: Path) -> Path:
    return tools_dir / "proto" / "proto_desc"


def default_pb_directory(tools_dir: Path) -> Path:
    return tools_dir.parent / "pb"


def _saved_directory(saved: str | None) -> Path | None:
    if not isinstance(saved, str) or not saved.strip():
        return None
    return Path(saved.strip().strip('"'))


def resolve_import_directory(tools_dir: Path, saved: str | None) -> Path | None:
    candidate = _saved_directory(saved)
    if candidate is not None and candidate.is_dir():
        return candidate
    return find_proto_directory(tools_dir)


def resolve_pb_directory(tools_dir: Path, saved: str | None) -> Path:
    candidate = _saved_directory(saved)
    if candidate is not None and (candidate.is_dir() or not candidate.exists()):
        return candidate
    return default_pb_directory(tools_dir)


def normalize_proto_filename(name: str) -> str | None:
    text = name.strip().strip('"')
    if text.lower().endswith(".proto"):
        text = text[: -len(".proto")]
    if not NAME_RE.fullmatch(text):
        return None
    return f"{text}.proto"


def file_matches(name: str, document: ProtoDocument | None, query: str) -> bool:
    text = query.strip().casefold()
    if not text:
        return True
    if text in name.casefold():
        return True
    if document is None:
        return False
    if text in document.package.casefold():
        return True
    return any(text in (message.name or "").casefold() for message in document.messages)


def new_proto_text(filename: str) -> str:
    stem = Path(filename).stem
    package = stem[:1].upper() + stem[1:]
    return render_proto(ProtoDocument(package, "", [], []))


def _same_directory(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return os.path.normcase(str(left)) == os.path.normcase(str(right))


def parse_proto(text: str) -> ProtoDocument:
    lines = text.splitlines()
    package = ""
    file_comments: list[str] = []
    imports: list[str] = []
    messages: list[ProtoMessage] = []
    pending: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            if pending and not messages:
                file_comments.extend(pending)
                pending = []
            index += 1
            continue
        if stripped.startswith("//"):
            pending.append(stripped[2:].strip())
            index += 1
            continue
        syntax = re.fullmatch(r'syntax\s*=\s*"([^"]+)"\s*;', stripped)
        if syntax:
            if syntax.group(1) != "proto3":
                raise ProtoParseError(index + 1, "只支持 proto3")
            index += 1
            continue
        package_match = re.fullmatch(r"package\s+([\w.]+)\s*;", stripped)
        if package_match:
            package = package_match.group(1)
            index += 1
            continue
        import_match = re.fullmatch(r'import\s+"([^"]+)"\s*;', stripped)
        if import_match:
            imports.append(import_match.group(1))
            index += 1
            continue
        message_match = re.fullmatch(r"message\s+(\w+)\s*\{", stripped)
        if message_match:
            comment = "\n".join(part for part in pending if part)
            pending = []
            message, index = _parse_message(
                lines, index + 1, message_match.group(1), comment
            )
            messages.append(message)
            continue
        raise ProtoParseError(index + 1, f"无法识别：{stripped}")
    return ProtoDocument(
        package=package,
        file_comment="\n".join(file_comments),
        imports=imports,
        messages=_absorb_map_lists(messages),
    )


def _map_list_name(message_name: str, field_name: str) -> str:
    return f"p_map_{message_name}_{field_name}_list"


def _absorb_map_lists(messages: list[ProtoMessage]) -> list[ProtoMessage]:
    by_name = {message.name: message for message in messages}
    absorbed: set[str] = set()
    for message in messages:
        for item in message.fields:
            if not item.map_key:
                continue
            wrapper = by_name.get(item.map_value)
            expected = _map_list_name(message.name, item.name)
            if (
                wrapper is None
                or wrapper.name != expected
                or len(wrapper.fields) != 1
                or not wrapper.fields[0].repeated
                or wrapper.fields[0].name != "value"
                or wrapper.fields[0].map_key
            ):
                continue
            item.map_value = wrapper.fields[0].type_name
            item.map_value_repeated = True
            absorbed.add(wrapper.name)
    return [message for message in messages if message.name not in absorbed]


def _parse_message(
    lines: list[str], start: int, name: str, comment: str
) -> tuple[ProtoMessage, int]:
    fields: list[ProtoField] = []
    pending: list[str] = []
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped == "}":
            return ProtoMessage(name, comment, fields), index + 1
        if stripped.startswith("//"):
            pending.append(stripped[2:].strip())
            index += 1
            continue
        matched = MAP_FIELD_RE.fullmatch(stripped)
        plain = None if matched else FIELD_RE.fullmatch(stripped)
        if matched is None and plain is None:
            raise ProtoParseError(index + 1, f"无法识别字段：{stripped}")
        if matched:
            trailing = (matched.group(5) or "").strip()
            fields.append(
                ProtoField(
                    repeated=False,
                    type_name="",
                    name=matched.group(3),
                    number=int(matched.group(4)),
                    comment=trailing or " ".join(part for part in pending if part),
                    map_key=matched.group(1),
                    map_value=matched.group(2),
                )
            )
        else:
            trailing = (plain.group(5) or "").strip()
            fields.append(
                ProtoField(
                    repeated=bool(plain.group(1)),
                    type_name=plain.group(2),
                    name=plain.group(3),
                    number=int(plain.group(4)),
                    comment=trailing or " ".join(part for part in pending if part),
                )
            )
        pending = []
        index += 1
    raise ProtoParseError(start, f"协议 {name} 没有结束")


def render_proto(document: ProtoDocument) -> str:
    lines = ['syntax = "proto3";', "", f"package {document.package};"]
    for comment in document.file_comment.splitlines():
        if comment.strip():
            lines.append(f"// {comment.strip()}")
    if document.imports or document.messages:
        lines.append("")
    for imported in document.imports:
        lines.append(f'import "{imported}";')
    if document.imports and document.messages:
        lines.append("")
    wrappers: list[tuple[str, str]] = []
    for message in document.messages:
        for comment in message.comment.splitlines():
            if comment.strip():
                lines.append(f"// {comment.strip()}")
        lines.append(f"message {message.name} {{")
        declarations: list[tuple[str, str]] = []
        for item in message.fields:
            if item.map_key:
                value_type = item.map_value
                if item.map_value_repeated:
                    value_type = _map_list_name(message.name, item.name)
                    wrappers.append((value_type, item.map_value))
                head = f"map<{item.map_key}, {value_type}>"
            else:
                repeated = "repeated " if item.repeated else ""
                head = f"{repeated}{item.type_name}"
            declarations.append((f"{head} {item.name} = {item.number};", item.comment.strip()))
        width = max((len(text) for text, comment in declarations if comment), default=0)
        for text, comment in declarations:
            if comment:
                lines.append(f"\t{text.ljust(width)}  // {comment}")
            else:
                lines.append(f"\t{text}")
        lines.append("}")
        lines.append("")
    for wrapper_name, value_type in wrappers:
        lines.append(f"message {wrapper_name} {{")
        lines.append(f"\trepeated {value_type} value = 1;")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def type_matches(options: list[str], query: str, limit: int = 30) -> list[str]:
    needle = (query or "").strip().casefold()
    if not needle or needle in (option.casefold() for option in options):
        ordered = sorted(options, key=lambda option: option.casefold() != needle)
        return ordered[:limit]

    def rank(option: str) -> int | None:
        text = option.casefold()
        short = text.rsplit(".", 1)[-1]
        if text.startswith(needle) or short.startswith(needle):
            return 0
        if needle in text:
            return 1
        letters = iter(text)
        if all(char in letters for char in needle):
            return 2
        return None

    ranked = [(rank(option), index, option) for index, option in enumerate(options)]
    return [option for score, _, option in sorted(r for r in ranked if r[0] is not None)][:limit]


def map_key_options(current: str) -> list[str]:
    options = list(MAP_KEY_TYPES)
    if current and current not in options:
        options.insert(0, current)
    return options


def field_type_options(
    proto_dir: Path, document: ProtoDocument, current: str
) -> list[str]:
    options = list(SCALAR_TYPES)
    for message in document.messages:
        if message.name and message.name not in options:
            options.append(message.name)
    for imported in document.imports:
        imported_path = proto_dir / imported
        if not imported_path.is_file():
            continue
        try:
            imported_document = parse_proto(
                imported_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, UnicodeError, ProtoParseError):
            continue
        prefix = imported_document.package
        for message in imported_document.messages:
            qualified = f"{prefix}.{message.name}" if prefix else message.name
            if qualified not in options:
                options.append(qualified)
    if current and current not in options:
        options.insert(0, current)
    return options


def message_name_error(filename: str, name: str) -> str | None:
    if not NAME_RE.fullmatch(name or ""):
        return "协议名只能包含字母、数字和下划线，且不能以数字开头"
    if filename == "common.proto" and name[:3] in {"c2s", "s2c"}:
        return "common.proto 里的类型不能以 c2s 或 s2c 开头"
    return None


MESSAGE_KINDS = {
    "c2s": ("请求", "#175CD3", "#EFF8FF"),
    "s2c": ("返回", "#027A48", "#ECFDF3"),
    "notify": ("推送", "#B54708", "#FFFAEB"),
    "type": ("结构", "#667085", "#F2F4F7"),
}


def message_kind(name: str) -> str:
    lowered = (name or "").casefold()
    if lowered.startswith("c2s"):
        return "c2s"
    if lowered.startswith("s2c"):
        return "s2c"
    if lowered.startswith("notify"):
        return "notify"
    return "type"


def known_field_types(document: ProtoDocument, proto_dir: Path | None = None) -> set[str]:
    names = set(SCALAR_TYPES)
    names.update(message.name for message in document.messages if message.name)
    if proto_dir is None:
        return names
    for imported in document.imports:
        imported_path = proto_dir / imported
        if not imported_path.is_file():
            continue
        try:
            imported_document = parse_proto(imported_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ProtoParseError):
            continue
        for message in imported_document.messages:
            if not message.name:
                continue
            names.add(message.name)
            if imported_document.package:
                names.add(f"{imported_document.package}.{message.name}")
    return names


def validate_document(
    filename: str, document: ProtoDocument, proto_dir: Path | None = None
) -> list[str]:
    errors: list[str] = []
    if not NAME_RE.fullmatch(document.package or ""):
        errors.append("包名只能包含字母、数字、下划线和点")
    seen_messages: set[str] = set()
    known_types = known_field_types(document, proto_dir)
    for message in document.messages:
        name_error = message_name_error(filename, message.name)
        if name_error:
            errors.append(f"{message.name or '未命名协议'}：{name_error}")
        if message.name in seen_messages:
            errors.append(f"协议名重复：{message.name}")
        seen_messages.add(message.name)
        seen_fields: set[str] = set()
        seen_numbers: set[int] = set()
        for item in message.fields:
            if not NAME_RE.fullmatch(item.name or ""):
                errors.append(f"{message.name}：字段名无效")
            elif item.name in seen_fields:
                errors.append(f"{message.name}：字段名重复 {item.name}")
            seen_fields.add(item.name)
            if item.map_key or item.map_value:
                if item.repeated:
                    errors.append(f"{message.name}.{item.name or '字段'}：字典不能同时是数组")
                if item.map_key not in MAP_KEY_TYPES:
                    errors.append(
                        f"{message.name}.{item.name or '字段'}：字典的键只能是整数、bool 或 string"
                    )
                if not TYPE_RE.fullmatch(item.map_value or ""):
                    errors.append(f"{message.name}.{item.name or '字段'}：字典的值类型无效")
                elif item.map_value not in known_types:
                    errors.append(
                        f"{message.name}.{item.name or '字段'}：不支持的类型 {item.map_value}"
                    )
            elif not TYPE_RE.fullmatch(item.type_name or ""):
                errors.append(f"{message.name}.{item.name or '字段'}：类型无效")
            elif item.type_name not in known_types:
                errors.append(
                    f"{message.name}.{item.name or '字段'}：不支持的类型 {item.type_name}"
                )
            if item.number is None or item.number <= 0:
                errors.append(f"{message.name}.{item.name or '字段'}：序号需要是正整数")
            elif item.number in seen_numbers:
                errors.append(f"{message.name}：序号重复 {item.number}")
            else:
                seen_numbers.add(item.number)
    return errors


def run_protocol_export(
    tools_dir: Path, proto_dir: Path | None = None, pb_dir: Path | None = None
) -> tuple[bool, str]:
    desc = protocol_desc_directory(tools_dir)
    source = proto_dir or desc
    if not _same_directory(source, desc):
        desc.mkdir(parents=True, exist_ok=True)
        for path in source.glob("*.proto"):
            shutil.copyfile(path, desc / path.name)
    scripts = [
        tools_dir / "script" / "extractlua.py",
        tools_dir / "script" / "extractluapb.py",
    ]
    missing = [script.name for script in scripts if not script.is_file()]
    if missing or not desc.is_dir():
        missing_text = "、".join(missing or ["proto/proto_desc"])
        return False, f"协议目录不完整，缺少 {missing_text}。"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    chunks: list[str] = []
    for script in scripts:
        try:
            completed = subprocess.run(
                [sys.executable, str(script), str(desc)],
                cwd=tools_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            chunks.append(f"{script.name} 无法执行：{exc}")
            return False, _limit("\n\n".join(chunks))
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part
        )
        chunks.append(f"--- {script.name}（退出码 {completed.returncode}）---\n{output}")
        if completed.returncode != 0 or "Failed to generate" in output:
            return False, _limit("\n\n".join(chunks))

    generated_pb = default_pb_directory(tools_dir)
    destination = pb_dir or generated_pb
    copied = _copy_pb_files(generated_pb, destination)
    client_net_pb = tools_dir.parent / "client" / "net_pb.json"
    server_net_pb = tools_dir.parent / "server" / "net_pb.lua"
    summary = "\n".join(
        [
            "协议已导出。",
            f"pb：{destination}" + (f"（{copied} 个文件）" if copied else ""),
            f"C#：{tools_dir / 'proto' / 'outcs'}",
            f"客户端 net_pb：{client_net_pb}",
            f"后端 net_pb：{server_net_pb}",
            "",
        ]
    )
    return True, _limit(summary + "\n\n".join(chunks))


def _copy_pb_files(generated: Path, destination: Path) -> int:
    if not generated.is_dir() or _same_directory(generated, destination):
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in generated.glob("*.pb"):
        shutil.copyfile(path, destination / path.name)
        count += 1
    return count


def _limit(text: str) -> str:
    if len(text) <= 12000:
        return text
    return text[:2000] + "\n...\n" + text[-9000:]


def _export_status(ok: bool, message: str) -> str:
    lines = []
    for line in message.splitlines():
        if line.startswith("---"):
            break
        text = line.strip()
        if text:
            lines.append(text)
    if not lines:
        return "协议已导出。" if ok else "协议导出失败。"
    text = " ".join(lines)
    if len(text) > 180:
        return text[:177] + "..."
    return text


class ProtocolEditor:
    def __init__(
        self,
        ctx: PluginContext,
        tools_dir: Path,
        proto_dir: Path | None,
        pb_dir: Path | None = None,
    ):
        self.ctx = ctx
        self.tools_dir = tools_dir
        self.proto_dir = proto_dir
        self.pb_dir = pb_dir or default_pb_directory(tools_dir)
        self.files: list[Path] = []
        self.documents: dict[Path, ProtoDocument] = {}
        self.parse_errors: dict[Path, str] = {}
        self.current: Path | None = None
        self.message_index = 0
        self.file_query = ""
        self.file_cursor = 0
        self.search_focused = False
        self._suppress_search_blur = False
        self.source_mode = False
        self.source_text: dict[Path, str] = {}
        self.type_target = None
        self.suggestions = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self.file_search = ft.TextField(
            hint_text="搜索文件，回车打开",
            dense=True,
            text_size=12,
            ignore_up_down_keys=True,
            on_change=self._on_file_search,
            on_submit=self._open_search_target,
            on_focus=self._on_search_focus,
            on_blur=self._on_search_blur,
        )
        self.file_list = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self.message_query = ""
        self.message_search_focused = False
        self._suppress_message_blur = False
        self.message_search = ft.TextField(
            hint_text="搜索协议，回车打开",
            dense=True,
            text_size=12,
            ignore_up_down_keys=True,
            on_change=self._on_message_search,
            on_submit=self._open_message_target,
            on_focus=self._on_message_focus,
            on_blur=self._on_message_blur,
        )
        self.message_list = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self._reload_files(load=True)
        self.status = ft.Text(
            "",
            size=12,
            color="#667085",
            expand=True,
            max_lines=1,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.body = ft.Column(spacing=10, expand=True)
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Text("协议编辑"),
                    ft.IconButton(
                        icon=ft.Icons.SETTINGS_OUTLINED,
                        icon_size=18,
                        tooltip="目录配置",
                        on_click=self.open_directory_settings,
                    ),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Container(
                content=self.body,
                width=ctx.dialog_width(1080),
                height=ctx.dialog_height(640),
            ),
        )

    def open(self) -> None:
        self.rebuild()
        self.ctx.listen_keyboard(self._on_key)

        def close(_event=None) -> None:
            self.ctx.stop_keyboard()
            self.ctx.pop_dialog()

        self.ctx.show_dialog(self.dialog, on_close=close)

    def _reload_files(self, load: bool = False) -> None:
        self.documents.clear()
        self.parse_errors.clear()
        self.source_text.clear()
        self.message_index = 0
        if self.proto_dir is not None and self.proto_dir.is_dir():
            self.files = sorted(
                self.proto_dir.glob("*.proto"), key=lambda path: path.name.casefold()
            )
        else:
            self.files = []
        self.current = self.files[0] if self.files else None
        if load and self.current is not None:
            self._load(self.current)

    def _load(self, path: Path) -> None:
        if path in self.documents or path in self.parse_errors:
            return
        try:
            self.documents[path] = parse_proto(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ProtoParseError) as exc:
            self.parse_errors[path] = str(exc)

    def _path_bar(self) -> ft.Control:
        if self.proto_dir is None:
            proto_hint = "还没有 proto 导入目录"
        else:
            proto_hint = f"proto：{self.proto_dir}"
        return ft.Column(
            [
                ft.Text(proto_hint, size=11, color="#98A2B3"),
                ft.Text(f"pb：{self.pb_dir}", size=11, color="#98A2B3"),
            ],
            spacing=0,
        )

    def open_directory_settings(self, _event=None) -> None:
        import_field = ft.TextField(
            label="proto导入目录",
            value="" if self.proto_dir is None else str(self.proto_dir),
            dense=True,
            expand=True,
        )
        pb_field = ft.TextField(
            label="pb导出目录",
            value=str(self.pb_dir),
            dense=True,
            expand=True,
        )

        async def pick_import(_event) -> None:
            selected = await self.ctx.pick_directory("选择 proto 导入目录", import_field.value)
            if selected:
                import_field.value = selected
                self.ctx.update()

        async def pick_pb(_event) -> None:
            selected = await self.ctx.pick_directory("选择 pb 导出目录", pb_field.value)
            if selected:
                pb_field.value = selected
                self.ctx.update()

        def apply(_event) -> None:
            raw_import = (import_field.value or "").strip().strip('"')
            raw_pb = (pb_field.value or "").strip().strip('"')
            if not raw_import:
                self.ctx.notify("请填写 proto 导入目录。", error=True)
                return
            import_dir = Path(raw_import)
            if not import_dir.is_dir():
                self.ctx.notify("proto 导入目录不存在。", error=True)
                return
            pb_dir = Path(raw_pb) if raw_pb else default_pb_directory(self.tools_dir)
            if pb_dir.exists() and not pb_dir.is_dir():
                self.ctx.notify("pb 导出目录需要是文件夹。", error=True)
                return
            import_changed = self.proto_dir is None or not _same_directory(
                self.proto_dir, import_dir
            )
            if import_changed and (
                self.source_text or any(document.dirty for document in self.documents.values())
            ):
                self.ctx.notify("有未保存的修改，请先保存再更换 proto 导入目录。", error=True)
                return
            self.pb_dir = pb_dir
            self.ctx.set_setting("proto_directory", str(import_dir))
            self.ctx.set_setting("pb_directory", str(pb_dir))
            if import_changed:
                self.proto_dir = import_dir
                self._reload_files(load=True)
            self.ctx.pop_dialog()
            self.rebuild()
            self.ctx.notify("目录已保存")

        self.ctx.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("目录配置"),
                content=ft.Container(
                    width=self.ctx.dialog_width(640),
                    content=ft.Column(
                        [
                            ft.Text(
                                "proto导入目录是正在编辑的 .proto。pb导出目录是生成的 .pb 文件位置，默认是仓库的 pb。C# 仍写到脚本原来的位置。协议号写到 client/net_pb.json 和 server/net_pb.lua。",
                                size=12,
                                color="#667085",
                            ),
                            ft.Row(
                                [
                                    import_field,
                                    ft.OutlinedButton(
                                        "选择",
                                        icon=ft.Icons.FOLDER_OPEN,
                                        on_click=pick_import,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    pb_field,
                                    ft.OutlinedButton(
                                        "选择",
                                        icon=ft.Icons.FOLDER_OPEN,
                                        on_click=pick_pb,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [ft.Button("确定", on_click=apply)],
                                alignment=ft.MainAxisAlignment.END,
                            ),
                        ],
                        spacing=12,
                        tight=True,
                    ),
                ),
            )
        )

    def open_new_proto(self, _event=None) -> None:
        if self.proto_dir is None or not self.proto_dir.is_dir():
            self.ctx.notify("请先在齿轮里设置 proto 导入目录。", error=True)
            return
        name_field = ft.TextField(
            label="文件名",
            hint_text="例如 login",
            dense=True,
            autofocus=True,
        )

        def apply(_event) -> None:
            filename = normalize_proto_filename(name_field.value or "")
            if filename is None:
                self.ctx.notify("文件名只能包含字母、数字和下划线。", error=True)
                return
            path = self.proto_dir / filename
            if path.exists():
                self.ctx.notify(f"{filename} 已经存在。", error=True)
                return
            try:
                path.write_text(new_proto_text(filename), encoding="utf-8")
            except OSError as exc:
                self.ctx.notify(f"创建失败：{exc}", error=True)
                return
            if path not in self.files:
                self.files.append(path)
                self.files.sort(key=lambda item: item.name.casefold())
            self.documents[path] = parse_proto(path.read_text(encoding="utf-8"))
            self.current = path
            self.message_index = 0
            self.ctx.pop_dialog()
            self.rebuild()
            self.ctx.notify(f"已创建 {filename}")

        self.ctx.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("新增 proto"),
                content=ft.Container(
                    width=self.ctx.dialog_width(420),
                    content=ft.Column(
                        [
                            ft.Text(
                                "会在 proto 导入目录里新建一个 proto3 文件。",
                                size=12,
                                color="#667085",
                            ),
                            name_field,
                            ft.Row(
                                [ft.Button("创建", on_click=apply)],
                                alignment=ft.MainAxisAlignment.END,
                            ),
                        ],
                        spacing=12,
                        tight=True,
                    ),
                ),
            )
        )

    def _on_search_focus(self, _event) -> None:
        self.search_focused = True

    def _on_search_blur(self, _event) -> None:
        if self._suppress_search_blur:
            self._suppress_search_blur = False
            return
        self.search_focused = False

    def _on_file_search(self, event) -> None:
        self.file_query = event.control.value or ""
        self.file_cursor = 0
        self._fill_file_list()
        self.ctx.update()

    def _file_matches(self, path: Path) -> bool:
        if self.file_query.strip():
            self._load(path)
        return file_matches(path.name, self.documents.get(path), self.file_query)

    def _visible_files(self) -> list[Path]:
        return [path for path in self.files if self._file_matches(path)]

    def _message_index_for_query(self, path: Path) -> int:
        query = self.file_query.strip().casefold()
        self._load(path)
        document = self.documents.get(path)
        if document is None or not query:
            return 0
        for index, message in enumerate(document.messages):
            if query in (message.name or "").casefold():
                return index
        return 0

    def _on_key(self, event) -> bool:
        key = (event.key or "").casefold().replace(" ", "")
        if key == "s" and (event.ctrl or event.meta) and not event.alt and not event.shift:
            self.save()
            return True
        if event.ctrl or event.meta or event.alt or event.shift:
            return False
        if self.message_search_focused:
            if key in {"arrowup", "up"}:
                self._move_message(-1)
                return True
            if key in {"arrowdown", "down"}:
                self._move_message(1)
                return True
            return False
        if not self.search_focused:
            return False
        if key in {"arrowup", "up"}:
            self._move_file(-1)
            return True
        if key in {"arrowdown", "down"}:
            self._move_file(1)
            return True
        return False

    def _on_message_focus(self, _event) -> None:
        self.message_search_focused = True

    def _on_message_blur(self, _event) -> None:
        if self._suppress_message_blur:
            self._suppress_message_blur = False
            return
        self.message_search_focused = False

    def _on_message_search(self, event) -> None:
        self.message_query = event.control.value or ""
        self._fill_message_list()
        self.ctx.update()

    def _visible_messages(self) -> list[tuple[int, ProtoMessage]]:
        document = self._document()
        if document is None:
            return []
        query = self.message_query.strip().casefold()
        return [
            (index, message)
            for index, message in enumerate(document.messages)
            if not query or query in (message.name or "").casefold()
        ]

    def _move_message(self, delta: int) -> None:
        visible = self._visible_messages()
        if not visible:
            return
        indexes = [index for index, _message in visible]
        start = indexes.index(self.message_index) if self.message_index in indexes else 0
        target = min(len(indexes) - 1, max(0, start + delta))
        self._choose_message(indexes[target])
        self._refocus_message()

    def _open_message_target(self, _event=None) -> None:
        visible = self._visible_messages()
        if not visible:
            self.ctx.notify("没有匹配的协议。", error=True)
            return
        indexes = [index for index, _message in visible]
        query = self.message_query.strip().casefold()
        chosen = indexes[0]
        if query:
            for index, message in visible:
                if query in (message.name or "").casefold():
                    chosen = index
                    break
        elif self.message_index in indexes:
            chosen = self.message_index
        self._choose_message(chosen)
        self._refocus_message()

    def _refocus_message(self) -> None:
        self.message_search_focused = True
        self._suppress_message_blur = True
        focus = getattr(self.ctx, "focus", None)
        if focus is not None:
            focus(self.message_search)

    def _fill_message_list(self) -> None:
        visible = self._visible_messages()
        if not visible:
            self.message_list.controls = [
                ft.Text(
                    "没有匹配的协议" if self.message_query.strip() else "这个文件还没有协议",
                    size=12,
                    color="#667085",
                )
            ]
            return
        buttons = []
        for index, message in visible:
            selected = index == self.message_index
            label, color, background = MESSAGE_KINDS[message_kind(message.name)]
            buttons.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(label, size=10, color=color),
                                bgcolor=background,
                                border_radius=6,
                                padding=ft.Padding(5, 1, 5, 1),
                            ),
                            ft.Text(
                                message.name or "未命名",
                                size=12,
                                color="#3538CD" if selected else "#344054",
                                weight=ft.FontWeight.W_600 if selected else None,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=message.comment or None,
                                expand=True,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#EEF4FF" if selected else None,
                    border_radius=8,
                    padding=ft.Padding(8, 6, 8, 6),
                    on_click=lambda _, index=index: self._choose_message(index),
                    ink=True,
                )
            )
        self.message_list.controls = buttons

    def _choose_message(self, index: int) -> None:
        self.message_index = index
        self.rebuild()

    def _move_file(self, delta: int) -> None:
        visible = self._visible_files()
        if not visible:
            return
        if self.current in visible:
            start = visible.index(self.current)
        else:
            start = min(self.file_cursor, len(visible) - 1)
        target = min(len(visible) - 1, max(0, start + delta))
        self.file_cursor = target
        self.select_file(visible[target], self._message_index_for_query(visible[target]))
        self._refocus_search()

    def _open_search_target(self, _event=None) -> None:
        visible = self._visible_files()
        if not visible:
            self.ctx.notify("没有匹配的文件。", error=True)
            return
        query = self.file_query.strip().casefold()
        ordered = [self.current] if self.current in visible else []
        ordered.extend(path for path in visible if path != self.current)
        chosen = ordered[0]
        message_index = self.message_index if chosen == self.current and not query else 0
        if query:
            for path in ordered:
                index = self._message_index_for_query(path)
                document = self.documents.get(path)
                matched = (
                    document is not None
                    and document.messages
                    and query in (document.messages[index].name or "").casefold()
                )
                if matched:
                    chosen = path
                    message_index = index
                    break
        self.file_cursor = visible.index(chosen)
        self.select_file(chosen, message_index)
        self._refocus_search()

    def _refocus_search(self) -> None:
        self.search_focused = True
        self._suppress_search_blur = True
        focus = getattr(self.ctx, "focus", None)
        if focus is not None:
            focus(self.file_search)

    def _fill_file_list(self) -> None:
        visible = self._visible_files()
        if not visible:
            self.file_list.controls = [
                ft.Text("没有匹配的文件", size=12, color="#667085")
            ]
            return
        if self.current in visible:
            self.file_cursor = visible.index(self.current)
        else:
            self.file_cursor = min(self.file_cursor, len(visible) - 1)
        aimed = visible[self.file_cursor]
        buttons = []
        for path in visible:
            selected = path == self.current
            aimed_only = path == aimed and not selected
            dirty = self._is_dirty(path)
            buttons.append(
                ft.Container(
                    content=ft.Text(
                        f"{'● ' if dirty else ''}{path.name}",
                        size=12,
                        color="#3538CD" if selected else "#344054",
                        weight=ft.FontWeight.W_600 if selected else None,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                    bgcolor="#EEF4FF" if selected else "#F2F4F7" if aimed_only else None,
                    border_radius=8,
                    padding=ft.Padding(8, 6, 8, 6),
                    on_click=lambda _, path=path: self.select_file(path),
                    ink=True,
                )
            )
        self.file_list.controls = buttons

    def _icon_action(self, icon, tooltip: str, on_click, color: str | None = None):
        return ft.IconButton(
            icon=icon,
            icon_size=16,
            icon_color=color,
            tooltip=tooltip,
            width=28,
            height=28,
            style=ft.ButtonStyle(
                padding=0,
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=on_click,
        )

    def _browser(self, title: str, actions: list, search: ft.Control, body: ft.Control, width: int):
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(title, size=13, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        ft.Row(actions, spacing=0),
                    ],
                    width=width,
                    height=32,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=ft.Column([search, body], spacing=6, expand=True),
                    expand=True,
                    bgcolor="#F8FAFC",
                    border=ft.Border.all(1, "#EAECF0"),
                    border_radius=10,
                    padding=ft.Padding(8, 8, 8, 6),
                ),
            ],
            width=width,
            spacing=6,
        )

    def rebuild(self) -> None:
        self._fill_file_list()
        self._fill_message_list()
        self.body.controls = [
            self._path_bar(),
            self._file_meta(),
            ft.Row(
                [
                    self._browser(
                        "协议文件",
                        [
                            self._icon_action(ft.Icons.ADD, "新增 proto", self.open_new_proto),
                            self._icon_action(
                                ft.Icons.DELETE_OUTLINE,
                                "删除 proto",
                                self.delete_current_file,
                                "#D92D20",
                            ),
                        ],
                        self.file_search,
                        self.file_list,
                        168,
                    ),
                    self._browser(
                        "协议",
                        [
                            self._icon_action(
                                ft.Icons.ADD, "新增协议", lambda _: self.add_message()
                            ),
                            self._icon_action(
                                ft.Icons.DELETE_OUTLINE,
                                "删除协议",
                                lambda _: self.delete_message(),
                                "#D92D20",
                            ),
                        ],
                        self.message_search,
                        self.message_list,
                        188,
                    ),
                    self._detail(),
                ],
                spacing=16,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ]
        self.ctx.update()

    def _detail(self) -> ft.Control:
        path = self.current
        if path is None:
            return ft.Text("请选择协议文件")
        error = self.parse_errors.get(path)
        if error or self.source_mode:
            return self._with_footer(self._source_editor(path, error), path)
        document = self.documents[path]
        if not document.messages:
            self.message_index = 0
        elif self.message_index >= len(document.messages):
            self.message_index = len(document.messages) - 1
        message = document.messages[self.message_index] if document.messages else None
        self.type_target = None
        self._fill_suggestions()
        if message is None:
            editor = ft.Text("从左侧选择或新增一条协议。", size=12, color="#667085")
        else:
            rule = (
                "子类型不要以 c2s 或 s2c 开头。"
                if path.name == "common.proto"
                else "c2s 开头是请求，s2c 是返回，notify 是推送，其它名字当作结构。字段序号在本协议内不能重复。"
            )
            field_headers = self._field_line(
                ft.Text("结构", size=11, color="#98A2B3"),
                ft.Text("类型", size=11, color="#98A2B3"),
                ft.Text("字段名", size=11, color="#98A2B3"),
                ft.Text("序号", size=11, color="#98A2B3"),
                ft.Text("注释", size=11, color="#98A2B3"),
                ft.Container(),
            )
            fields = (
                ft.Text("这个协议还没有字段。", size=12, color="#667085")
                if not message.fields
                else ft.Column(
                    [self._field_row(document, message, item) for item in message.fields],
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                )
            )
            editor = ft.Column(
                [
                    ft.Row(
                        [
                            self._text(
                                "协议名",
                                message.name,
                                lambda value, message=message: self._rename_message(message, value),
                                expand=True,
                            ),
                            self._text(
                                "协议注释",
                                message.comment,
                                lambda value, message=message: self._set(message, "comment", value),
                                expand=True,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Text(rule, size=11, color="#98A2B3"),
                    *(
                        [ft.Container(content=self.suggestions, height=24), field_headers]
                        if message.fields
                        else []
                    ),
                    ft.Container(content=fields, expand=True),
                ],
                spacing=8,
                expand=True,
            )
        return self._with_footer(editor, path)

    def _source_editor(self, path: Path, error: str | None) -> ft.Control:
        text = self.source_text.get(path)
        document = self.documents.get(path)
        if text is None and document is not None and document.dirty:
            text = render_proto(document)
        if text is None:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                return ft.Text(f"读取 {path.name} 失败：{exc}", color="#B42318")

        def changed(event) -> None:
            fresh = path not in self.source_text
            self.source_text[path] = event.control.value or ""
            if fresh:
                self._fill_file_list()
                self.ctx.update()

        hint = (
            f"表格解析不了这个文件，可以直接改源码。{error}"
            if error
            else "直接编辑 proto 源码，Ctrl+S 保存；切回表格时会重新解析。"
        )
        return ft.Column(
            [
                ft.Text(hint, size=11, color="#B42318" if error else "#98A2B3"),
                ft.Column(
                    [
                        ft.TextField(
                            value=text,
                            multiline=True,
                            min_lines=20,
                            text_size=13,
                            text_style=ft.TextStyle(font_family="Consolas"),
                            content_padding=ft.Padding(12, 10, 12, 10),
                            on_change=changed,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            spacing=8,
            expand=True,
        )

    def _with_footer(self, editor: ft.Control, path: Path) -> ft.Control:
        table_ready = path not in self.parse_errors
        in_source = self.source_mode or not table_ready
        controls: list[ft.Control] = []
        if not in_source:
            controls.append(ft.OutlinedButton("新增字段", on_click=lambda _: self.add_field()))
        if table_ready or path in self.source_text:
            controls.append(
                ft.TextButton(
                    "表格" if in_source else "源码",
                    icon=ft.Icons.TABLE_ROWS_OUTLINED if in_source else ft.Icons.CODE,
                    tooltip="切回表格编辑" if in_source else "直接编辑 proto 源码",
                    on_click=lambda _: self.toggle_source(),
                )
            )
        return ft.Column(
            [
                editor,
                ft.Row(
                    [
                        *controls,
                        self.status,
                        ft.Button(
                            "保存",
                            icon=ft.Icons.SAVE_OUTLINED,
                            tooltip="Ctrl+S",
                            on_click=lambda _: self.save(),
                        ),
                        ft.OutlinedButton(
                            "导出协议",
                            icon=ft.Icons.ACCOUNT_TREE_OUTLINED,
                            on_click=self.export_protocols,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=8,
            expand=True,
        )

    def _file_meta(self) -> ft.Control:
        document = self._document()
        if document is None:
            return ft.Container()
        return ft.Row(
            [
                self._text(
                    "包名",
                    document.package,
                    lambda value, document=document: self._set(document, "package", value),
                    width=200,
                ),
                self._text(
                    "文件注释",
                    document.file_comment,
                    lambda value, document=document: self._set(document, "file_comment", value),
                    expand=True,
                ),
            ],
            spacing=8,
        )

    def _text(self, label: str, value: str, assign, width: int | None = None, expand: bool = False):
        return ft.TextField(
            label=label,
            value=value,
            dense=True,
            text_size=13,
            width=width,
            expand=expand,
            on_change=lambda event, assign=assign: assign(event.control.value),
        )

    def _rename_message(self, message: ProtoMessage, value: str) -> None:
        self._set(message, "name", value)
        self._fill_message_list()
        self.ctx.update()

    def _set(self, target, attr: str, value: str) -> None:
        setattr(target, attr, value)
        if self.current is not None and self.current in self.documents:
            self.documents[self.current].dirty = True

    def _field_row(self, document: ProtoDocument, message: ProtoMessage, item: ProtoField):
        type_options = field_type_options(
            self.proto_dir, document, item.map_value or item.type_name
        )
        key_options = map_key_options(item.map_key)

        def mark():
            document.dirty = True

        def set_number(event, item=item):
            text = event.control.value.strip()
            item.number = int(text) if text.isdigit() else None
            mark()

        def set_type(text, item=item):
            item.type_name = (text or "").strip()
            mark()

        def set_map_key(text, item=item):
            item.map_key = (text or "").strip()
            mark()

        def set_map_value(text, item=item):
            item.map_value = (text or "").strip()
            mark()

        def set_map_value_kind(value, item=item):
            item.map_value_repeated = value == "数组"
            mark()

        def set_kind(value, item=item):
            if value == "数组":
                item.repeated = True
                item.map_key = ""
                item.map_value = ""
                item.type_name = item.type_name or "int32"
            elif value == "字典":
                item.repeated = False
                item.map_key = item.map_key or "int32"
                item.map_value = item.map_value or item.type_name or "string"
            else:
                item.repeated = False
                item.type_name = item.type_name or item.map_value or "int32"
                item.map_key = ""
                item.map_value = ""
            mark()
            self.rebuild()

        kind = "字典" if item.map_key else "数组" if item.repeated else "单个"
        if item.map_key:
            type_box = ft.Row(
                [
                    self._type_input(item.map_key, key_options, set_map_key, "键"),
                    self._type_input(item.map_value, type_options, set_map_value, "值"),
                    self._cycle(
                        "数组" if item.map_value_repeated else "单个",
                        ("单个", "数组"),
                        set_map_value_kind,
                        "点击切换：值是单个，或值是数组。数组会额外生成一个 repeated 类型作为 map 的值",
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        else:
            type_box = self._type_input(item.type_name, type_options, set_type)
        return self._field_line(
            self._select(
                kind,
                ("单个", "数组", "字典"),
                set_kind,
                "单个；数组写成 repeated；字典写成 map",
                width=72,
            ),
            type_box,
            self._input(
                item.name,
                lambda event, item=item: (
                    setattr(item, "name", event.control.value),
                    mark(),
                ),
                expand=True,
            ),
            self._input(
                "" if item.number is None else str(item.number),
                set_number,
                width=56,
            ),
            self._input(
                item.comment,
                lambda event, item=item: (
                    setattr(item, "comment", event.control.value),
                    mark(),
                ),
                expand=True,
                hint="注释",
            ),
            self._icon_action(
                ft.Icons.DELETE_OUTLINE,
                "删除字段",
                lambda _, message=message, item=item: self.delete_field(message, item),
                "#D92D20",
            ),
        )

    def _input(
        self,
        value: str,
        on_change=None,
        width: int | None = None,
        expand: bool = False,
        hint: str | None = None,
        **extra,
    ) -> ft.TextField:
        return ft.TextField(
            value=value,
            hint_text=hint,
            dense=True,
            text_size=13,
            width=width,
            expand=expand,
            content_padding=FIELD_PADDING,
            on_change=on_change,
            **extra,
        )

    def _cycle(self, value: str, options, on_select, tooltip: str):
        box = self._input(
            value,
            width=64,
            read_only=True,
            tooltip=tooltip,
            text_align=ft.TextAlign.CENTER,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        def clicked(_event) -> None:
            current = box.value if box.value in options else options[0]
            box.value = options[(options.index(current) + 1) % len(options)]
            on_select(box.value)
            self._refresh(box)

        box.on_click = clicked
        return box

    def _select(self, value: str, options, on_select, tooltip: str, width: int | None = None):
        box = self._input(
            value,
            width=width,
            read_only=True,
            tooltip=f"{tooltip}。点一下后在上方选择",
            text_align=ft.TextAlign.CENTER,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        def pick(option: str) -> None:
            box.value = option
            on_select(option)

        def clicked(_event) -> None:
            self.type_target = None
            self.suggestions.controls = [
                ft.Container(
                    content=ft.Text(option, size=12, color="#3538CD"),
                    padding=ft.Padding(8, 3, 8, 3),
                    border_radius=10,
                    bgcolor="#EEF4FF" if option == box.value else "#F2F4F7",
                    tooltip=option,
                    on_click=lambda _event, option=option: pick(option),
                )
                for option in options
            ]
            self._refresh(self.suggestions)

        box.on_click = clicked
        return box

    def _type_input(self, value: str, options: list[str], assign, hint: str = "类型"):
        box = self._input(
            value or "",
            hint=hint,
            expand=True,
            tooltip="按输入模糊匹配；保存或导出时，标量、本文件和 import 里没有的类型会报错",
        )
        target = (box, options, assign)

        def focused(_event) -> None:
            self.type_target = target
            self._fill_suggestions()

        def changed(event) -> None:
            assign(event.control.value or "")
            self.type_target = target
            self._fill_suggestions()

        def submitted(event) -> None:
            text = (event.control.value or "").strip()
            matches = type_matches(options, text)
            if text and len(matches) == 1 and text not in options:
                self._pick_type(target, matches[0])

        box.on_focus = focused
        box.on_change = changed
        box.on_submit = submitted
        return box

    def _pick_type(self, target, option: str) -> None:
        box, _options, assign = target
        box.value = option
        assign(option)
        self.type_target = target
        self._fill_suggestions()
        self._refresh(box)

    def _fill_suggestions(self) -> None:
        target = self.type_target
        if target is None:
            self.suggestions.controls = [
                ft.Text(SUGGESTION_HINT, size=11, color="#98A2B3")
            ]
        else:
            box, options, _assign = target
            matches = type_matches(options, box.value or "")
            self.suggestions.controls = [
                ft.Container(
                    content=ft.Text(option, size=12, color="#3538CD"),
                    padding=ft.Padding(8, 3, 8, 3),
                    border_radius=10,
                    bgcolor="#EEF4FF",
                    tooltip=f"使用 {option}",
                    on_click=lambda _event, option=option: self._pick_type(target, option),
                )
                for option in matches
            ] or [ft.Text("没有匹配的类型，会按输入的名字使用", size=11, color="#98A2B3")]
        self._refresh(self.suggestions)

    def _refresh(self, control) -> None:
        try:
            control.update()
        except (AssertionError, RuntimeError):
            pass

    def _field_line(self, repeated, type_box, name_box, number_box, comment_box, trailing):
        if isinstance(type_box, ft.Row):
            type_box.expand = 6
            type_cell = type_box
        else:
            type_cell = ft.Container(expand=6, content=type_box)
        return ft.Row(
            [
                ft.Container(width=72, content=repeated),
                type_cell,
                ft.Container(expand=3, content=name_box),
                ft.Container(width=56, content=number_box),
                ft.Container(expand=3, content=comment_box),
                ft.Container(width=32, content=trailing, alignment=ft.Alignment.CENTER),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def delete_current_file(self, _event=None) -> None:
        path = self.current
        if path is None or self.proto_dir is None:
            self.ctx.notify("请先选择要删除的 proto 文件。", error=True)
            return
        try:
            path.resolve().relative_to(self.proto_dir.resolve())
        except ValueError:
            self.ctx.notify("只能删除 proto 导入目录里的文件。", error=True)
            return
        dirty = self._is_dirty(path)
        hint = f"确定删除 {path.name}？文件会从 proto 导入目录中移除。"
        if dirty:
            hint = f"{path.name} 还有未保存的修改。删除后这些修改也会丢掉。"

        def confirm(_event=None) -> None:
            try:
                if path.is_file():
                    path.unlink()
            except OSError as exc:
                self.ctx.notify(f"删除失败：{exc}", error=True)
                return
            self.files = [item for item in self.files if item != path]
            self.documents.pop(path, None)
            self.parse_errors.pop(path, None)
            self.source_text.pop(path, None)
            self.ctx.pop_dialog()
            if self.files:
                self.select_file(self.files[0])
            else:
                self.current = None
                self.message_index = 0
                self.rebuild()
            self.ctx.notify(f"已删除 {path.name}")

        self.ctx.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除 proto"),
                content=ft.Text(hint, size=13),
                actions=[
                    ft.Button("删除", on_click=confirm),
                ],
            )
        )

    def select_file(self, path: Path, message_index: int = 0) -> None:
        if path != self.current:
            self.message_query = ""
            self.message_search.value = ""
        self.current = path
        self._load(path)
        document = self.documents.get(path)
        if document is not None and document.messages:
            self.message_index = max(0, min(message_index, len(document.messages) - 1))
        else:
            self.message_index = 0
        self.rebuild()

    def _document(self) -> ProtoDocument | None:
        if self.current is None:
            return None
        return self.documents.get(self.current)

    def add_message(self) -> None:
        document = self._document()
        if document is None or self.current is None:
            return
        prefix = "p_" if self.current.name == "common.proto" else "c2s_"
        document.messages.append(ProtoMessage(f"{prefix}new", "", []))
        document.dirty = True
        self.message_index = len(document.messages) - 1
        self.rebuild()

    def delete_message(self) -> None:
        document = self._document()
        if document is None or not document.messages:
            return
        document.messages.pop(self.message_index)
        document.dirty = True
        self.message_index = max(0, self.message_index - 1)
        self.rebuild()

    def add_field(self) -> None:
        document = self._document()
        if document is None or not document.messages:
            return
        message = document.messages[self.message_index]
        numbers = [item.number for item in message.fields if item.number]
        message.fields.append(
            ProtoField(False, "int32", f"field{len(message.fields) + 1}", max(numbers or [0]) + 1)
        )
        document.dirty = True
        self.rebuild()

    def delete_field(self, message: ProtoMessage, item: ProtoField) -> None:
        document = self._document()
        if document is None:
            return
        message.fields = [field for field in message.fields if field is not item]
        document.dirty = True
        self.rebuild()

    def _set_status(self, text: str, color: str) -> None:
        self.status.value = text
        self.status.color = color
        self.status.tooltip = text or None

    def _is_dirty(self, path: Path) -> bool:
        if path in self.source_text:
            return True
        document = self.documents.get(path)
        return document is not None and document.dirty

    def _apply_source(self, path: Path) -> str | None:
        try:
            document = parse_proto(self.source_text[path])
        except ProtoParseError as exc:
            return str(exc)
        original = self.documents.get(path)
        document.dirty = original is None or render_proto(original) != render_proto(document)
        self.documents[path] = document
        self.parse_errors.pop(path, None)
        del self.source_text[path]
        return None

    def toggle_source(self) -> None:
        path = self.current
        if path is None:
            return
        if self.source_mode or path in self.parse_errors:
            if path in self.source_text:
                error = self._apply_source(path)
                if error:
                    self._set_status(f"源码还不能用表格编辑：{error}", "#B42318")
                    self.rebuild()
                    return
            self.source_mode = False
            document = self.documents.get(path)
            if document is not None and self.message_index >= len(document.messages):
                self.message_index = 0
        else:
            self.source_mode = True
        self._set_status("", "#667085")
        self.rebuild()

    def save(self) -> bool:
        if self.current is not None and self.current in self.source_text:
            return self.save_source(self.current)
        return self.save_current()

    def save_source(self, path: Path) -> bool:
        text = self.source_text[path]
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            self.ctx.notify(f"保存失败：{exc}", error=True)
            return False
        del self.source_text[path]
        try:
            document = parse_proto(text)
        except ProtoParseError as exc:
            self.documents.pop(path, None)
            self.parse_errors[path] = str(exc)
            self._set_status(f"已保存 {path.name}，但表格解析不了：{exc}", "#B54708")
        else:
            self.documents[path] = document
            self.parse_errors.pop(path, None)
            self._set_status(f"已保存 {path.name}", "#027A48")
        self._fill_file_list()
        self.ctx.update()
        return True

    def save_current(self) -> bool:
        document = self._document()
        if document is None or self.current is None:
            return False
        errors = validate_document(self.current.name, document, self.proto_dir)
        if errors:
            self._set_status(errors[0], "#B42318")
            self.ctx.update()
            return False
        try:
            self.current.write_text(render_proto(document), encoding="utf-8")
        except OSError as exc:
            self.ctx.notify(f"保存失败：{exc}", error=True)
            return False
        document.dirty = False
        self._set_status(f"已保存 {self.current.name}", "#027A48")
        self.rebuild()
        return True

    async def export_protocols(self, _) -> None:
        for path in list(self.source_text):
            if not self.save_source(path):
                return
        for path, document in self.documents.items():
            if not document.dirty:
                continue
            errors = validate_document(path.name, document, self.proto_dir)
            if errors:
                self.current = path
                self._set_status(f"{path.name}：{errors[0]}", "#B42318")
                self.rebuild()
                return
            try:
                path.write_text(render_proto(document), encoding="utf-8")
            except OSError as exc:
                self.ctx.notify(f"保存失败：{exc}", error=True)
                return
            document.dirty = False
        if self.proto_dir is None:
            self._set_status("请先在齿轮里设置 proto 导入目录。", "#B42318")
            self.ctx.update()
            self.ctx.notify(self.status.value, error=True)
            return
        self._set_status("正在导出协议…", "#667085")
        self.ctx.update()
        ok, message = await asyncio.to_thread(
            run_protocol_export, self.tools_dir, self.proto_dir, self.pb_dir
        )
        self._set_status(_export_status(ok, message), "#027A48" if ok else "#B42318")
        self.ctx.update()
        self.ctx.notify(self.status.value, error=not ok)
        self.ctx.show_text("协议导出完成" if ok else "协议导出失败", message)


def register(ctx: PluginContext) -> list[PluginAction]:
    async def open_editor(_event) -> None:
        saved = ctx.get_setting("tools_directory")
        tools_dir = find_protocol_tools(
            [
                saved if isinstance(saved, str) else None,
                ctx.configuration_directory(),
                ctx.app_directory,
                Path.cwd(),
            ]
        )
        if tools_dir is None:
            selected = await ctx.pick_directory(
                "选择协议工具目录（ptotools 或仓库根目录）",
                str(ctx.app_directory),
            )
            if not selected:
                return
            tools_dir = find_protocol_tools([selected, ctx.app_directory])
            if tools_dir is None:
                ctx.notify(
                    "没有找到协议导出脚本。请选择含有 ptotools/script 的目录，不是配置表目录。",
                    error=True,
                )
                return
        if str(tools_dir) != saved:
            ctx.set_setting("tools_directory", str(tools_dir))
        saved_import = ctx.get_setting("proto_directory")
        if not isinstance(saved_import, str):
            saved_import = ctx.get_setting("import_directory")
        saved_pb = ctx.get_setting("pb_directory")
        proto_dir = resolve_import_directory(
            tools_dir, saved_import if isinstance(saved_import, str) else None
        )
        pb_dir = resolve_pb_directory(
            tools_dir, saved_pb if isinstance(saved_pb, str) else None
        )
        ProtocolEditor(ctx, tools_dir, proto_dir, pb_dir).open()

    return [
        PluginAction(
            label=PLUGIN_TITLE,
            icon=ft.Icons.ACCOUNT_TREE_OUTLINED,
            tooltip=PLUGIN_DESCRIPTION,
            on_click=open_editor,
            desktop_only=True,
        )
    ]
