import ast
import csv
import copy
import io
import json
import math
import os
import re
import zipfile
from pathlib import Path
from typing import Any

import flet as ft


PAGE_SIZES = (10, 20, 50, 100)
MAX_ROW_UNDO = 50
SAMPLE_COLUMNS = ["id", "name", "type", "rarity", "price"]
DATA_TYPES = {
    "string": "字符串",
    "integer": "整数",
    "number": "小数",
    "boolean": "布尔值",
    "json": "JSON（对象/数组）",
    "lua_array": "Lua 表（数组）",
    "lua_object": "Lua 表（字典）",
}
EXPORT_TARGETS = {
    "both": "前后端",
    "backend": "仅后端",
    "frontend": "仅前端",
}
SAMPLE_TYPES = ["integer", "string", "string", "string", "integer"]
SAMPLE_TARGETS = ["both", "both", "both", "both", "both"]
SAMPLE_ANNOTATIONS = ["唯一标识", "道具名称", "道具分类", "品质等级", "商店价格"]
SAMPLE_ROWS = [
    {"id": 1001, "name": "新手长剑", "type": "武器", "rarity": "普通", "price": 100},
    {"id": 1002, "name": "旅人法杖", "type": "武器", "rarity": "精良", "price": 420},
    {"id": 1003, "name": "生命药水", "type": "消耗品", "rarity": "普通", "price": 35},
    {"id": 1004, "name": "秘银护甲", "type": "防具", "rarity": "稀有", "price": 1250},
    {"id": 1005, "name": "疾风靴", "type": "防具", "rarity": "精良", "price": 680},
    {"id": 1006, "name": "火焰卷轴", "type": "消耗品", "rarity": "稀有", "price": 900},
    {"id": 1007, "name": "守护指环", "type": "饰品", "rarity": "精良", "price": 760},
    {"id": 1008, "name": "星辰碎片", "type": "材料", "rarity": "史诗", "price": 3200},
    {"id": 1009, "name": "铁矿石", "type": "材料", "rarity": "普通", "price": 12},
    {"id": 1010, "name": "远古护符", "type": "饰品", "rarity": "传说", "price": 8600},
    {"id": 1011, "name": "冰霜短刃", "type": "武器", "rarity": "稀有", "price": 1750},
    {"id": 1012, "name": "强效回复药", "type": "消耗品", "rarity": "精良", "price": 160},
    {"id": 1013, "name": "秘银矿石", "type": "材料", "rarity": "稀有", "price": 340},
    {"id": 1014, "name": "游侠斗篷", "type": "防具", "rarity": "史诗", "price": 4100},
    {"id": 1015, "name": "月光宝石", "type": "材料", "rarity": "史诗", "price": 5200},
    {"id": 1016, "name": "勇者徽章", "type": "饰品", "rarity": "传说", "price": 9800},
    {"id": 1017, "name": "橡木弓", "type": "武器", "rarity": "普通", "price": 150},
    {"id": 1018, "name": "净化药剂", "type": "消耗品", "rarity": "精良", "price": 230},
]


def _app_settings_path() -> Path:
    app_data = os.environ.get("APPDATA")
    settings_root = Path(app_data) if app_data else Path.home() / ".config"
    return settings_root / "GameConfigAssistant" / "settings.json"


def _load_app_settings() -> tuple[dict[str, Any], str | None]:
    settings_path = _app_settings_path()
    try:
        if not settings_path.exists():
            return {}, None
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"无法读取已保存的导出设置：{exc}"
    if not isinstance(settings, dict):
        return {}, "已保存的导出设置格式无效，将使用默认设置。"
    return settings, None


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def resolve_image_path(value: Any, table_path: Path | None) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value.strip())
    if candidate.suffix.casefold() not in {
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }:
        return None
    if not candidate.is_absolute():
        base_directory = table_path.parent if table_path is not None else Path.cwd()
        candidate = base_directory / candidate
    try:
        if candidate.is_file():
            return candidate.resolve()
    except (OSError, RuntimeError):
        return None
    return None


def load_table(
    path: Path, file_bytes: bytes | None = None
) -> tuple[list[str], list[str], list[str], list[str], list[dict[str, Any]]]:
    if path.suffix.lower() != ".tsv":
        raise ValueError("目前仅支持 TSV 配置文件。")
    content = file_bytes if file_bytes is not None else path.read_bytes()
    try:
        records = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter="\t"))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"TSV 文件无法读取：{exc}") from exc
    records = [record for record in records if record]
    if len(records) < 4:
        raise ValueError("TSV 文件至少需要字段名、数据类型、导出端和注释四行。")
    columns = [name.strip() for name in records[0]]
    if not columns or any(not name for name in columns):
        raise ValueError("字段行中不能有空字段名。")
    if len(set(columns)) != len(columns):
        raise ValueError("字段名不能重复。")
    data_types = records[1]
    targets = records[2]
    annotations = records[3]
    for label, values in (
        ("数据类型", data_types),
        ("导出端", targets),
        ("注释", annotations),
    ):
        if len(values) != len(columns):
            raise ValueError(f"{label}行的列数必须与字段名行一致。")
    invalid_types = [value for value in data_types if value not in DATA_TYPES]
    if invalid_types:
        raise ValueError(f"不支持的数据类型：{', '.join(invalid_types)}。")
    invalid_targets = [value for value in targets if value not in EXPORT_TARGETS]
    if invalid_targets:
        raise ValueError(f"不支持的导出端：{', '.join(invalid_targets)}。")
    rows = []
    for line_number, record in enumerate(records[4:], start=5):
        if len(record) != len(columns):
            raise ValueError(f"第 {line_number} 行有 {len(record)} 列，应为 {len(columns)} 列。")
        row = {}
        for column, value, data_type in zip(columns, record, data_types):
            try:
                row[column] = parse_data_value(value, data_type)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"第 {line_number} 行字段「{column}」不符合{DATA_TYPES[data_type]}类型：{exc}"
                ) from exc
        rows.append(row)
    return columns, data_types, targets, annotations, rows


def export_tsv(
    columns: list[str],
    data_types: list[str],
    targets: list[str],
    annotations: list[str],
    rows: list[dict[str, Any]],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    writer.writerow(data_types)
    writer.writerow(targets)
    writer.writerow(annotations)
    writer.writerows(
        [
            _display_value_for_type(row.get(column), data_types[index])
            for index, column in enumerate(columns)
        ]
        for row in rows
    )
    return output.getvalue().encode("utf-8")


def new_configuration_table_bytes() -> bytes:
    return export_tsv(
        ["id"],
        ["integer"],
        ["both"],
        ["唯一标识"],
        [],
    )


def move_row(rows: list[dict[str, Any]], source_index: int, target_index: int):
    if not 0 <= source_index < len(rows):
        raise IndexError("源行索引超出范围。")
    if not 0 <= target_index < len(rows):
        raise IndexError("目标行索引超出范围。")
    if source_index == target_index:
        return
    row = rows.pop(source_index)
    rows.insert(target_index, row)


def insert_row_copy(
    rows: list[dict[str, Any]],
    row: dict[str, Any],
    insert_index: int,
) -> int:
    if not 0 <= insert_index <= len(rows):
        raise IndexError("粘贴位置超出范围。")
    rows.insert(insert_index, copy.deepcopy(row))
    return insert_index


def build_export_archive(outputs: list[tuple[Path, bytes]]) -> bytes:
    archive_buffer = io.BytesIO()
    seen_names: set[str] = set()
    with zipfile.ZipFile(
        archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path, data in outputs:
            target = path.parent.name
            if target not in {"backend", "frontend"}:
                raise ValueError(f"无效的导出端目录：{target}")
            archive_name = f"{target}/{path.name}"
            if archive_name in seen_names:
                raise ValueError(f"ZIP 中存在重复文件：{archive_name}")
            seen_names.add(archive_name)
            archive.writestr(archive_name, data)
    return archive_buffer.getvalue()


def _display_value_for_type(value: Any, data_type: str) -> str:
    if data_type in {"lua_array", "lua_object"} and value is not None:
        return _lua_value(value)
    return _display_value(value)


class _LuaTableParser:
    def __init__(self, source: str):
        source = source.strip()
        if re.match(r"^return\b", source):
            source = source[6:].lstrip()
        self.source = source
        self.position = 0

    def parse(self) -> Any:
        value = self._parse_value()
        self._skip_whitespace()
        if self.position != len(self.source):
            raise ValueError(f"Lua 表后有无法识别的内容：{self.source[self.position:]}")
        if not isinstance(value, (list, dict)):
            raise ValueError("请输入 Lua 表，例如 {1, 2} 或 {name = \"value\"}")
        return value

    def _skip_whitespace(self):
        while self.position < len(self.source) and self.source[self.position].isspace():
            self.position += 1

    def _consume(self, token: str):
        self._skip_whitespace()
        if not self.source.startswith(token, self.position):
            raise ValueError(f"Lua 表语法错误：此处应为 {token}")
        self.position += len(token)

    def _parse_string(self) -> str:
        quote = self.source[self.position]
        start = self.position
        self.position += 1
        while self.position < len(self.source):
            character = self.source[self.position]
            self.position += 1
            if character == "\\":
                self.position += 1
            elif character == quote:
                try:
                    value = ast.literal_eval(self.source[start:self.position])
                except (SyntaxError, ValueError) as exc:
                    raise ValueError(f"Lua 字符串无效：{exc}") from exc
                if not isinstance(value, str):
                    raise ValueError("Lua 表的字典键必须是字符串或数字。")
                return value
        raise ValueError("Lua 字符串缺少结束引号。")

    def _parse_value(self) -> Any:
        self._skip_whitespace()
        if self.position >= len(self.source):
            raise ValueError("Lua 表内容不完整。")
        character = self.source[self.position]
        if character == "{":
            return self._parse_table()
        if character in {'"', "'"}:
            return self._parse_string()
        number = re.match(
            r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
            self.source[self.position:],
        )
        if number:
            token = number.group()
            self.position += len(token)
            return float(token) if any(mark in token for mark in ".eE") else int(token)
        identifier = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.source[self.position:])
        if identifier:
            token = identifier.group()
            self.position += len(token)
            literals = {"true": True, "false": False, "nil": None}
            if token in literals:
                return literals[token]
        raise ValueError(f"不支持的 Lua 表值：{self.source[self.position:]}")

    def _parse_table(self) -> Any:
        self._consume("{")
        array_values = []
        keyed_values = {}
        has_keyed_values = False
        self._skip_whitespace()
        while self.position < len(self.source) and self.source[self.position] != "}":
            if self.source[self.position] == "[":
                self._consume("[")
                key = self._parse_value()
                if key is None or not isinstance(key, (str, int, float, bool)):
                    raise ValueError("Lua 表的字典键必须是字符串、数字或布尔值。")
                self._consume("]")
                self._consume("=")
                keyed_values[key] = self._parse_value()
                has_keyed_values = True
            else:
                identifier = re.match(
                    r"[A-Za-z_][A-Za-z0-9_]*\s*=",
                    self.source[self.position:],
                )
                if identifier:
                    key = identifier.group().split("=", 1)[0].strip()
                    self.position += identifier.end()
                    keyed_values[key] = self._parse_value()
                    has_keyed_values = True
                else:
                    array_values.append(self._parse_value())

            self._skip_whitespace()
            if self.position < len(self.source) and self.source[self.position] == "}":
                break
            if self.position < len(self.source) and self.source[self.position] in ",;":
                self.position += 1
                self._skip_whitespace()
            else:
                raise ValueError("Lua 表中的字段之间需要使用逗号或分号分隔。")
        self._consume("}")
        if not has_keyed_values:
            return array_values
        keyed_values.update(
            {index: value for index, value in enumerate(array_values, start=1)}
        )
        return keyed_values


def _parse_lua_table(value: str, data_type: str) -> list[Any] | dict[Any, Any]:
    parsed = _LuaTableParser(value).parse()
    if data_type == "lua_array":
        if isinstance(parsed, dict):
            if not all(type(key) is int for key in parsed):
                raise ValueError("Lua 表数组只能包含顺序数组项。")
            if set(parsed) != set(range(1, len(parsed) + 1)):
                raise ValueError("Lua 表数组的索引必须从 1 开始连续排列。")
            return [parsed[index] for index in range(1, len(parsed) + 1)]
        return parsed
    if isinstance(parsed, list):
        if parsed:
            raise ValueError("Lua 表字典请使用 name = value 或 [key] = value 格式。")
        return {}
    return parsed


def parse_data_value(value: Any, data_type: str) -> Any:
    if data_type not in DATA_TYPES:
        raise ValueError(f"不支持的数据类型：{data_type}。")
    if value is None:
        return None
    if data_type == "string":
        return value if isinstance(value, str) else _display_value(value)
    if data_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if data_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if data_type == "boolean" and isinstance(value, bool):
        return value
    if data_type == "json" and isinstance(value, (dict, list)):
        return value
    if data_type == "lua_array" and isinstance(value, list):
        return value
    if data_type == "lua_object" and isinstance(value, dict):
        return value
    if not isinstance(value, str):
        value = _display_value(value)
    if value == "":
        return None
    if data_type == "integer":
        return int(value)
    if data_type == "number":
        return float(value)
    if data_type == "boolean":
        normalized = value.strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError("布尔值请输入 true 或 false")
        return normalized == "true"
    if data_type in {"lua_array", "lua_object"}:
        return _parse_lua_table(value, data_type)
    return json.loads(value)


def export_json_data(
    columns: list[str],
    data_types: list[str],
    rows: list[dict[str, Any]],
    key_columns: list[str] | None = None,
) -> bytes:
    records = [
        {
            column: parse_data_value(row.get(column, ""), data_types[index])
            for index, column in enumerate(columns)
        }
        for row in rows
    ]
    if any(key_column not in columns for key_column in (key_columns or [])):
        raise ValueError("导出 key 字段必须来自当前配置表。")
    data = _index_export_records(records, key_columns, json_keys=True)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _lua_value(value: Any) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = []
        for character in value:
            codepoint = ord(character)
            if character == "\\":
                escaped.append("\\\\")
            elif character == '"':
                escaped.append('\\"')
            elif character == "\n":
                escaped.append("\\n")
            elif character == "\r":
                escaped.append("\\r")
            elif character == "\t":
                escaped.append("\\t")
            elif codepoint < 32 or codepoint == 127:
                escaped.append(f"\\{codepoint:03d}")
            else:
                escaped.append(character)
        return f'"{"".join(escaped)}"'
    if isinstance(value, list):
        return "{ " + ", ".join(_lua_value(item) for item in value) + " }"
    if isinstance(value, dict):
        entries = (
            f"[{_lua_value(key)}] = {_lua_value(item)}"
            for key, item in value.items()
        )
        return "{ " + ", ".join(entries) + " }"
    raise TypeError(f"Lua 导出不支持 {type(value).__name__} 类型。")


def _lua_value_pretty(value: Any, indent: int = 0) -> str:
    if isinstance(value, list):
        if not value:
            return "{}"
        child_indent = indent + 4
        entries = ",\n".join(
            " " * child_indent + _lua_value_pretty(item, child_indent)
            for item in value
        )
    elif isinstance(value, dict):
        if not value:
            return "{}"
        child_indent = indent + 4
        entries = ",\n".join(
            " " * child_indent
            + f"[{_lua_value(key)}] = {_lua_value_pretty(item, child_indent)}"
            for key, item in value.items()
        )
    else:
        return _lua_value(value)
    return "{\n" + entries + "\n" + " " * indent + "}"


def export_lua(
    columns: list[str],
    data_types: list[str],
    rows: list[dict[str, Any]],
    key_columns: list[str] | None = None,
    source_name: str | None = None,
) -> bytes:
    records = [
        {
            column: parse_data_value(row.get(column, ""), data_types[index])
            for index, column in enumerate(columns)
        }
        for row in rows
    ]
    if any(key_column not in columns for key_column in (key_columns or [])):
        raise ValueError("导出 key 字段必须来自当前配置表。")
    data = _index_export_records(records, key_columns)
    source_label = source_name or "未知配置表"
    header = (
        "-- author: liter_wave\n"
        "-- Generated by: 星图 · 游戏配置导表工具\n"
        f"-- Source TSV: {source_label}\n"
        "\n"
    )
    return (header + "return " + _lua_value_pretty(data) + "\n").encode("utf-8")


def _index_export_records(
    records: list[dict[str, Any]],
    key_columns: list[str] | None,
    json_keys: bool = False,
) -> list[dict[str, Any]] | dict[Any, Any]:
    if not key_columns:
        return records
    if len(set(key_columns)) != len(key_columns):
        raise ValueError("导出 key 字段不能重复。")
    result: dict[Any, Any] = {}
    seen_paths: dict[tuple[Any, ...], int] = {}
    for row_number, record in enumerate(records, start=1):
        key_path = []
        for key_column in key_columns:
            key_value = record[key_column]
            if key_value is None:
                raise ValueError(
                    f"第 {row_number} 条记录的 key 字段「{key_column}」不能为空。"
                )
            if isinstance(key_value, (dict, list)) or not isinstance(
                key_value, (str, int, float, bool)
            ):
                raise ValueError(
                    f"key 字段「{key_column}」必须是字符串、整数、小数或布尔值。"
                )
            if isinstance(key_value, float) and not math.isfinite(key_value):
                raise ValueError(f"key 字段「{key_column}」不能是无穷值或 NaN。")
            key_path.append(str(key_value) if json_keys else key_value)

        path = tuple(key_path)
        conflicting_row_number = next(
            (
                existing_row_number
                for existing_path, existing_row_number in seen_paths.items()
                if existing_path[: min(len(path), len(existing_path))]
                == path[: min(len(path), len(existing_path))]
            ),
            None,
        )
        if conflicting_row_number is not None:
            key_description = " / ".join(
                f"{column}={value}"
                for column, value in zip(key_columns, path)
            )
            raise ValueError(
                f"第 {row_number} 行与第 {conflicting_row_number} 行的 "
                f"key 组合重复或层级冲突（{key_description}），"
                "请检查该表的 key 字段是否重复或存在层级冲突。"
            )
        seen_paths[path] = row_number

        current = result
        for key_value in key_path[:-1]:
            current = current.setdefault(key_value, {})
        current[key_path[-1]] = record
    return result


def prepare_export_files(
    columns: list[str],
    data_types: list[str],
    targets: list[str],
    rows: list[dict[str, Any]],
    source_name: str,
    backend_format: str,
    frontend_format: str,
    backend_directory: str | None,
    frontend_directory: str | None,
    key_columns: list[str] | None = None,
    validate_directories: bool = True,
) -> list[Path]:
    if backend_format not in {"lua", "json"}:
        raise ValueError("后端格式只能选择 Lua 或 JSON。")
    if frontend_format not in {"lua", "json"}:
        raise ValueError("前端格式只能选择 Lua 或 JSON。")
    if len(columns) != len(data_types) or len(columns) != len(targets):
        raise ValueError("字段、数据类型和导出端配置数量不一致。")
    if any(target not in EXPORT_TARGETS for target in targets):
        raise ValueError("存在无效的列导出端配置。")
    backend_indexes = [
        index for index, target in enumerate(targets) if target in {"backend", "both"}
    ]
    frontend_indexes = [
        index for index, target in enumerate(targets) if target in {"frontend", "both"}
    ]
    if backend_indexes and not backend_directory:
        raise ValueError("请先选择后端导出目录。")
    if frontend_indexes and not frontend_directory:
        raise ValueError("请先选择前端导出目录。")
    if backend_indexes:
        missing_keys = [
            key for key in (key_columns or [])
            if key not in columns or targets[columns.index(key)] not in {"backend", "both"}
        ]
        if missing_keys:
            raise ValueError(
                "后端导出 key 字段未勾选后端导出："
                + "、".join(missing_keys)
                + "。"
            )
    if frontend_indexes:
        missing_keys = [
            key for key in (key_columns or [])
            if key not in columns or targets[columns.index(key)] not in {"frontend", "both"}
        ]
        if missing_keys:
            raise ValueError(
                "前端导出 key 字段未勾选前端导出："
                + "、".join(missing_keys)
                + "。"
            )

    stem = Path(source_name).stem
    outputs: list[tuple[Path, bytes]] = []
    if backend_indexes:
        selected_columns = [columns[index] for index in backend_indexes]
        selected_types = [data_types[index] for index in backend_indexes]
        selected_rows = [
            {column: row.get(column, "") for column in selected_columns}
            for row in rows
        ]
        backend_path = Path(backend_directory) / f"{stem}.{backend_format}"
        backend_data = (
            export_lua(
                selected_columns,
                selected_types,
                selected_rows,
                key_columns,
                source_name,
            )
            if backend_format == "lua"
            else export_json_data(
                selected_columns, selected_types, selected_rows, key_columns
            )
        )
        outputs.append((backend_path, backend_data))
    if frontend_indexes:
        selected_columns = [columns[index] for index in frontend_indexes]
        selected_types = [data_types[index] for index in frontend_indexes]
        selected_rows = [
            {column: row.get(column, "") for column in selected_columns}
            for row in rows
        ]
        frontend_path = Path(frontend_directory) / f"{stem}.{frontend_format}"
        frontend_data = (
            export_lua(
                selected_columns,
                selected_types,
                selected_rows,
                key_columns,
                source_name,
            )
            if frontend_format == "lua"
            else export_json_data(
                selected_columns, selected_types, selected_rows, key_columns
            )
        )
        outputs.append((frontend_path, frontend_data))

    if validate_directories:
        for path, _ in outputs:
            if not path.parent.is_dir():
                raise ValueError(f"导出目录不存在：{path.parent}")
    normalized_paths = [os.path.normcase(str(path.resolve())) for path, _ in outputs]
    if len(normalized_paths) != len(set(normalized_paths)):
        raise ValueError(
            "前后端导出目录和格式相同，文件名会冲突；请为两端选择不同目录或不同格式。"
        )
    return outputs


def write_export_files(
    columns: list[str],
    data_types: list[str],
    targets: list[str],
    rows: list[dict[str, Any]],
    source_name: str,
    backend_format: str,
    frontend_format: str,
    backend_directory: str | None,
    frontend_directory: str | None,
    key_columns: list[str] | None = None,
) -> list[Path]:
    outputs = prepare_export_files(
        columns,
        data_types,
        targets,
        rows,
        source_name,
        backend_format,
        frontend_format,
        backend_directory,
        frontend_directory,
        key_columns,
    )
    written_paths = []
    for path, data in outputs:
        path.write_bytes(data)
        written_paths.append(path)
    return written_paths


def main(page: ft.Page):
    page.title = "星图 · 游戏配置导表工具"
    page.bgcolor = "#F5F7FB"
    page.padding = 0
    page.theme = ft.Theme(
        color_scheme_seed="#5B6CFF",
        popup_menu_theme=ft.PopupMenuTheme(
            color="#FFFFFF",
            shadow_color="#1018281A",
            label_text_style=ft.TextStyle(size=12, color="#344054"),
            elevation=3,
            shape=ft.RoundedRectangleBorder(
                side=ft.BorderSide(1, "#EAECF0"),
                radius=10,
            ),
            menu_padding=4,
        ),
    )
    mobile_platform = page.platform.is_mobile()
    if not mobile_platform:
        page.window.min_width = 960
        page.window.min_height = 680

    def dialog_width(preferred: int) -> int:
        available_width = page.width
        if available_width is None or available_width <= 0:
            return preferred
        return max(220, min(preferred, int(available_width) - 96))

    def dialog_height(preferred: int, margin: int = 80) -> int:
        available_height = page.height
        if available_height is None or available_height <= 0:
            return preferred
        return max(240, min(preferred, int(available_height) - margin))

    def available_initial_directory(directory: str | None) -> str | None:
        if not directory:
            return None
        return directory if Path(directory).is_dir() else None

    columns = SAMPLE_COLUMNS.copy()
    data_types = SAMPLE_TYPES.copy()
    targets = SAMPLE_TARGETS.copy()
    annotations = SAMPLE_ANNOTATIONS.copy()
    rows = [row.copy() for row in SAMPLE_ROWS]
    saved_settings, settings_load_error = _load_app_settings()
    saved_export_paths = saved_settings.get("export_paths", {})
    if not isinstance(saved_export_paths, dict):
        saved_export_paths = {}
    export_paths: dict[str, str | None] = {
        target: (
            directory
            if isinstance(directory, str) and directory
            else None
        )
        for target, directory in saved_export_paths.items()
        if target in {"backend", "frontend"}
    }
    export_paths.setdefault("backend", None)
    export_paths.setdefault("frontend", None)
    configuration_directory = saved_settings.get("configuration_directory")
    if not isinstance(configuration_directory, str) or not configuration_directory:
        configuration_directory = None
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
    key_columns = [
        column
        for column in columns
        if column in saved_table_keys
    ] if "item_config.tsv" in saved_key_rules else (
        ["id"] if "id" in columns else []
    )
    current_page = 0
    page_size = 10
    source_name = "item_config.tsv"
    active_table_path: Path | None = None
    selected_row_index: int | None = None
    copied_row: dict[str, Any] | None = None
    copied_row_table_key: str | None = None
    row_undo_history: dict[str, list[dict[str, Any]]] = {}
    row_copy_button: ft.OutlinedButton | None = None
    row_paste_button: ft.OutlinedButton | None = None
    row_undo_button: ft.OutlinedButton | None = None
    mobile_configuration_paths: list[Path] = []
    mobile_file_bytes: dict[str, bytes] = {}
    modified_table_paths: set[str] = set()
    table_states: dict[str, dict[str, Any]] = {}
    configuration_delete_button: ft.IconButton | None = None
    key_rules_by_table = {
        name: [
            key for key in keys
            if isinstance(key, str)
        ]
        for name, keys in saved_key_rules.items()
        if isinstance(name, str) and isinstance(keys, list)
    }
    picker = ft.FilePicker()
    page.services.append(picker)
    configuration_directory_field = ft.TextField(
        label="配置文件目录",
        value=configuration_directory or "尚未选择",
        read_only=True,
        width=410,
    )
    configuration_table_count = ft.Text(
        "请先选择 TSV 配置文件" if mobile_platform else "尚未选择配置目录"
    )
    configuration_count_metric = ft.Text("—")
    configuration_section_title = ft.Text(
        "TSV 配置表",
        size=11,
        color="#98A2B3",
        weight=ft.FontWeight.W_600,
        expand=True,
    )
    mobile_configuration_section_title = ft.Text(
        "配置表",
        size=11,
        color="#98A2B3",
        weight=ft.FontWeight.W_600,
        expand=True,
    )
    new_configuration_name = ft.TextField(
        label="配置表名称",
        hint_text="例如：item_config",
        autofocus=True,
    )
    configuration_search_field = ft.TextField(
        hint_text="搜索配置表…",
        prefix_icon=ft.Icons.SEARCH,
        text_size=12,
        dense=True,
        height=40,
        content_padding=ft.Padding(10, 8, 10, 8),
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#EAECF0"),
            ),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#7A83FF"),
            ),
        },
    )
    configuration_file_list = ft.Column(
        [ft.Text("请先在导出设置中选择 TSV 目录。", size=11, color="#98A2B3")],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )
    mobile_configuration_search_field = ft.TextField(
        hint_text="搜索配置表…",
        prefix_icon=ft.Icons.SEARCH,
        text_size=12,
        dense=True,
        height=40,
        content_padding=ft.Padding(10, 8, 10, 8),
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#EAECF0"),
            ),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#7A83FF"),
            ),
        },
    )
    mobile_configuration_file_list = ft.Column(
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    backend_directory_field = ft.TextField(
        label="后端导出目录",
        value=export_paths["backend"] or "尚未选择",
        read_only=True,
        width=410,
    )
    frontend_directory_field = ft.TextField(
        label="前端导出目录",
        value=export_paths["frontend"] or "尚未选择",
        read_only=True,
        width=410,
    )
    backend_format_select = ft.Dropdown(
        label="后端文件格式",
        value=backend_format,
        options=[
            ft.DropdownOption(key="lua", text="Lua"),
            ft.DropdownOption(key="json", text="JSON"),
        ],
        width=220,
    )
    frontend_format_select = ft.Dropdown(
        label="前端文件格式",
        value=frontend_format,
        options=[
            ft.DropdownOption(key="lua", text="Lua"),
            ft.DropdownOption(key="json", text="JSON"),
        ],
        width=220,
    )

    table_area = ft.Column(expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)
    table_status = ft.Text(
        color="#667085",
        size=12,
        expand=True,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    selected_row_status = ft.Text(
        "先点行号选择一行",
        color="#667085",
        size=12,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    page_status = ft.Text(color="#667085", size=12)
    column_manager_refresh = None
    page_size_select = ft.Dropdown(
        value=str(page_size),
        options=[
            ft.DropdownOption(key=str(size), text=f"{size}条")
            for size in PAGE_SIZES
        ],
        width=104,
        height=34,
        dense=True,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0),
        text_size=12,
        text_style=ft.TextStyle(size=12, color="#344054"),
        menu_height=176,
        menu_width=112,
        enable_search=False,
        enable_filter=False,
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#D0D5DD"),
            ),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color="#7A83FF"),
            ),
        },
        on_select=None,
        tooltip="选择每页显示条数",
    )
    page_number_text = ft.Text(color="#344054", size=13, weight=ft.FontWeight.W_600)
    source_text = ft.Text(source_name, color="#344054", size=13)
    row_count_text = ft.Text()
    column_count_text = ft.Text()

    def notify(message: str, error: bool = False):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor="#D92D20" if error else "#344054",
                duration=3000,
            )
        )

    def save_export_settings():
        key_rules_by_table[source_name] = key_columns.copy()
        settings = {
            "export_paths": export_paths,
            "configuration_directory": configuration_directory,
            "backend_format": backend_format_select.value or "lua",
            "frontend_format": frontend_format_select.value or "json",
            "key_rules": key_rules_by_table,
        }
        settings_path = _app_settings_path()
        temporary_path = settings_path.with_suffix(".tmp")
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(settings_path)
        except OSError as exc:
            notify(f"保存导出设置失败：{exc}", error=True)

    def count_configuration_tables(directory: str) -> int:
        return sum(
            path.is_file() and path.suffix.lower() == ".tsv"
            for path in Path(directory).iterdir()
        )

    def table_path_key(path: Path) -> str:
        return os.path.normcase(str(path.resolve()))

    def configuration_paths() -> list[Path]:
        if mobile_platform:
            return sorted(mobile_configuration_paths, key=lambda path: path.name.casefold())
        if not configuration_directory:
            return []
        return sorted(
            (
                path
                for path in Path(configuration_directory).iterdir()
                if path.is_file() and path.suffix.lower() == ".tsv"
            ),
            key=lambda path: path.name.casefold(),
        )

    def make_configuration_file_controls(
        tables: list[Path],
        query: str,
        close_dialog_on_select: bool = False,
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
                    if mobile_platform
                    else "此目录下没有 TSV 文件。"
                )
            )
            return [
                ft.Text(
                    empty_message,
                    size=11,
                    color="#98A2B3",
                )
            ]

        def select_table(path: Path):
            load_configuration_file(path)
            if close_dialog_on_select:
                page.pop_dialog()

        return [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.DESCRIPTION_OUTLINED,
                            size=15,
                            color=(
                                "#5B6CFF"
                                if active_table_path is not None
                                and table_path_key(path) == table_path_key(active_table_path)
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
                            visible=table_path_key(path) in modified_table_paths,
                            tooltip="本次会话中已修改",
                        ),
                    ],
                    spacing=8,
                ),
                bgcolor=(
                    "#EEF0FF"
                    if active_table_path is not None
                    and table_path_key(path) == table_path_key(active_table_path)
                    else None
                ),
                border_radius=7,
                padding=ft.Padding(9, 7, 9, 7),
                ink=True,
                ink_color="#EEF0FF",
                on_click=lambda _, selected_path=path: select_table(selected_path),
                tooltip=path.name if mobile_platform else str(path),
            )
            for path in tables
        ]

    def refresh_configuration_files():
        tables = configuration_paths()
        configuration_file_list.controls = make_configuration_file_controls(
            tables,
            configuration_search_field.value or "",
        )
        mobile_configuration_file_list.controls = make_configuration_file_controls(
            tables,
            mobile_configuration_search_field.value or "",
            close_dialog_on_select=True,
        )
        if configuration_delete_button is not None:
            configuration_delete_button.disabled = active_table_path is None

    configuration_search_field.on_change = lambda _: refresh_configuration_files()
    mobile_configuration_search_field.on_change = lambda _: refresh_configuration_files()

    def snapshot_active_table() -> dict[str, Any]:
        return {
            "columns": columns.copy(),
            "data_types": data_types.copy(),
            "targets": targets.copy(),
            "annotations": annotations.copy(),
            "rows": copy.deepcopy(rows),
            "key_columns": key_columns.copy(),
        }

    def cache_active_table():
        if active_table_path is None:
            return
        path_key = table_path_key(active_table_path)
        table_states[path_key] = snapshot_active_table()

    def mark_active_table_modified():
        if active_table_path is None:
            return
        path_key = table_path_key(active_table_path)
        modified_table_paths.add(path_key)
        table_states[path_key] = snapshot_active_table()
        refresh_configuration_files()

    def row_history_key() -> str:
        if active_table_path is not None:
            return table_path_key(active_table_path)
        return f"sample:{source_name}"

    def update_row_action_buttons():
        selected_exists = (
            selected_row_index is not None
            and 0 <= selected_row_index < len(rows)
        )
        selected_row_status.value = (
            f"目标：第 {selected_row_index + 1} 行"
            if selected_exists
            else "点行号选择目标；Ctrl+C 复制，Ctrl+V 插入到目标行前；Ctrl+Z 撤销"
        )
        if row_copy_button is not None:
            row_copy_button.disabled = not selected_exists
        if row_paste_button is not None:
            row_paste_button.disabled = not (
                selected_exists
                and copied_row is not None
                and copied_row_table_key == row_history_key()
            )
        if row_undo_button is not None:
            row_undo_button.disabled = not row_undo_history.get(row_history_key())

    def record_row_undo():
        history = row_undo_history.setdefault(row_history_key(), [])
        history.append(
            {
                "rows": copy.deepcopy(rows),
                "current_page": current_page,
                "selected_row_index": selected_row_index,
            }
        )
        del history[:-MAX_ROW_UNDO]
        update_row_action_buttons()

    def select_row(row_index: int):
        nonlocal selected_row_index
        if not 0 <= row_index < len(rows):
            return
        selected_row_index = row_index
        update_row_action_buttons()
        refresh_table()

    def copy_selected_row(_):
        nonlocal copied_row, copied_row_table_key
        if selected_row_index is None or not 0 <= selected_row_index < len(rows):
            notify("请先点击行号选择要复制的行。", error=True)
            return
        copied_row = copy.deepcopy(rows[selected_row_index])
        copied_row_table_key = row_history_key()
        update_row_action_buttons()
        refresh_table()
        notify(f"已复制第 {selected_row_index + 1} 行")

    def paste_copied_row(_):
        nonlocal current_page, selected_row_index
        if (
            selected_row_index is None
            or not 0 <= selected_row_index < len(rows)
            or copied_row is None
            or copied_row_table_key != row_history_key()
        ):
            notify("请先在当前配置表中选择行并复制。", error=True)
            return
        record_row_undo()
        selected_row_index = insert_row_copy(
            rows,
            copied_row,
            selected_row_index,
        )
        current_page = selected_row_index // page_size
        mark_active_table_modified()
        refresh_table()
        notify(f"已插入到第 {selected_row_index + 1} 行，原行下移")

    def handle_row_shortcuts(event: ft.KeyboardEvent):
        key = event.key.casefold()
        if not (event.ctrl or event.meta) or event.alt or event.shift:
            return
        if key == "c":
            copy_selected_row(event)
        elif key == "v":
            paste_copied_row(event)
        elif key == "z":
            undo_row_action(event)

    def undo_row_action(_):
        nonlocal current_page, selected_row_index
        history = row_undo_history.get(row_history_key())
        if not history:
            notify("当前配置表没有可撤销的操作。")
            return
        previous_state = history.pop()
        rows[:] = copy.deepcopy(previous_state["rows"])
        current_page = previous_state["current_page"]
        selected_row_index = previous_state["selected_row_index"]
        mark_active_table_modified()
        update_row_action_buttons()
        refresh_table()
        notify("已撤销上一步操作")

    def reorder_row(event: ft.DragTargetEvent, target_index: int):
        nonlocal current_page, selected_row_index
        try:
            source_index = int(event.src.data)
        except (AttributeError, TypeError, ValueError) as exc:
            notify(f"无法识别拖动的配置行：{exc}", error=True)
            return
        if not 0 <= source_index < len(rows) or not 0 <= target_index < len(rows):
            notify("拖动位置已失效，请重试。", error=True)
            return
        if source_index == target_index:
            return
        record_row_undo()
        move_row(rows, source_index, target_index)
        selected_row_index = target_index
        current_page = target_index // page_size
        mark_active_table_modified()
        refresh_table()
        notify(f"已将配置行移动到第 {target_index + 1} 行")

    def metric_card(label: str, value: ft.Control, icon: str, tint: str):
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(label, size=12, color="#667085"),
                            value,
                        ],
                        spacing=8,
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

    def edit_cell(row: dict[str, Any], column: str):
        column_index = columns.index(column)
        original = row.get(column)
        data_type = data_types[column_index]
        value_input = ft.TextField(
            label=column,
            value=_display_value_for_type(original, data_type),
            autofocus=True,
            multiline=data_type in {"json", "lua_array", "lua_object"},
            min_lines=1,
            max_lines=6 if data_type in {"json", "lua_array", "lua_object"} else 1,
            width=dialog_width(400),
        )

        def save_value(_):
            try:
                updated_value = parse_data_value(
                    value_input.value or "",
                    data_type,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                value_input.error_text = f"无法保存：{exc}"
                page.update()
                return
            if row.get(column) != updated_value:
                record_row_undo()
                row[column] = updated_value
                mark_active_table_modified()
            page.pop_dialog()
            refresh_table()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"编辑「{column}」"),
                content=value_input,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                    ft.Button("保存", on_click=save_value),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def edit_annotation(index: int):
        annotation_input = ft.TextField(
            label=f"{columns[index]} 的注释",
            value=annotations[index],
            autofocus=True,
            multiline=True,
            min_lines=2,
            max_lines=5,
            width=dialog_width(400),
        )

        def save_annotation(_):
            annotation = annotation_input.value or ""
            if annotations[index] != annotation:
                annotations[index] = annotation
                mark_active_table_modified()
            page.pop_dialog()
            refresh_table()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("编辑字段注释"),
                content=annotation_input,
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                    ft.Button("保存", on_click=save_annotation),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def set_column_type(index: int, data_type: str):
        if data_type not in DATA_TYPES:
            raise ValueError(f"不支持的数据类型：{data_type}")
        if data_types[index] != data_type:
            data_types[index] = data_type
            mark_active_table_modified()

    def set_column_target(index: int, target: str):
        if target not in EXPORT_TARGETS:
            raise ValueError(f"不支持的导出端：{target}")
        if targets[index] != target:
            targets[index] = target
            mark_active_table_modified()

    def toggle_key_column(index: int):
        column = columns[index]
        previous_key_columns = key_columns.copy()
        if column in key_columns:
            key_columns.remove(column)
        else:
            key_columns.append(column)
        key_columns[:] = [name for name in columns if name in key_columns]
        if key_columns != previous_key_columns:
            mark_active_table_modified()
        save_export_settings()
        refresh_table()

    backend_format_select.on_select = lambda _: save_export_settings()
    frontend_format_select.on_select = lambda _: save_export_settings()

    def open_export_rule(_):
        rule_summary = ft.Text(size=12, color="#667085")
        key_checkboxes = {
            column: ft.Checkbox(
                label=column,
                value=column in key_columns,
            )
            for column in columns
        }

        def update_rule(_):
            previous_key_columns = key_columns.copy()
            key_columns[:] = [
                column
                for column in columns
                if key_checkboxes[column].value
            ]
            if key_columns != previous_key_columns:
                mark_active_table_modified()
            rule_summary.value = (
                "当前规则："
                + " → ".join(key_columns)
                + "（末级输出完整记录）"
                if key_columns
                else "当前规则：记录数组（未按字段建立索引）"
            )
            save_export_settings()
            page.update()

        for checkbox in key_checkboxes.values():
            checkbox.on_change = update_rule
        update_rule(None)

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("导表规则"),
                content=ft.Column(
                    [
                        ft.Text(
                            "勾选字段作为导出 key；多个字段按当前表格列顺序逐层嵌套。"
                            "默认使用 id，末级保留完整记录。",
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
                            width=dialog_width(420),
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
                    ft.TextButton(
                        "完成",
                        on_click=lambda _: page.pop_dialog(),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def add_row(_):
        nonlocal current_page, selected_row_index
        record_row_undo()
        rows.append(
            {
                column: "" if data_types[index] == "string" else None
                for index, column in enumerate(columns)
            },
        )
        selected_row_index = len(rows) - 1
        mark_active_table_modified()
        current_page = (len(rows) - 1) // page_size
        refresh_table()

    def confirm_delete_row(row: dict[str, Any]):
        row_number = next(
            (index + 1 for index, current_row in enumerate(rows) if current_row is row),
            None,
        )
        if row_number is None:
            return

        def delete_row(_):
            nonlocal selected_row_index
            row_index = next(
                (
                    index
                    for index, current_row in enumerate(rows)
                    if current_row is row
                ),
                None,
            )
            if row_index is None:
                page.pop_dialog()
                return
            record_row_undo()
            rows.pop(row_index)
            if selected_row_index == row_index:
                selected_row_index = None
            elif selected_row_index is not None and selected_row_index > row_index:
                selected_row_index -= 1
            mark_active_table_modified()
            page.pop_dialog()
            refresh_table()
            notify(f"已删除第 {row_number} 行")

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除数据行"),
                content=ft.Text(
                    f"确定删除第 {row_number} 行吗？此操作仅影响当前会话中的数据。"
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                    ft.Button(
                        "删除",
                        icon=ft.Icons.DELETE_OUTLINE,
                        style=ft.ButtonStyle(
                            bgcolor="#D92D20",
                            color="#FFFFFF",
                        ),
                        on_click=delete_row,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def open_column_manager(_):
        nonlocal column_manager_refresh
        pending_column: str | None = None
        column_list = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO)
        manager_status = ft.Text(
            "删除字段会同时移除该列的全部数据。",
            size=12,
            color="#667085",
        )

        def remove_column(column: str):
            index = columns.index(column)
            columns.pop(index)
            data_types.pop(index)
            targets.pop(index)
            annotations.pop(index)
            key_columns[:] = [key for key in key_columns if key != column]
            for row in rows:
                row.pop(column, None)
            mark_active_table_modified()
            save_export_settings()
            refresh_table()
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
                f"共 {len(columns)} 列。删除字段会同时移除该列的全部数据。"
            )
            if not columns:
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
                page.update()
                return

            for index, column in enumerate(columns):
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
                                    bgcolor="#D92D20",
                                    color="#FFFFFF",
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
                                        f"{DATA_TYPES[data_types[index]]} · "
                                        f"{EXPORT_TARGETS[targets[index]]}",
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
                        border=ft.Border.only(
                            bottom=ft.BorderSide(1, "#EAECF0")
                        ),
                    )
                )
            page.update()

        def close_manager(_):
            nonlocal column_manager_refresh
            column_manager_refresh = None
            page.pop_dialog()

        render_columns()
        column_manager_refresh = render_columns
        page.show_dialog(
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
                                    on_click=add_column,
                                    style=ft.ButtonStyle(
                                        bgcolor="#EEF0FF",
                                        color="#4F5FE8",
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color="#EAECF0"),
                        ft.Container(
                            content=column_list,
                            width=dialog_width(460),
                            height=380,
                        ),
                    ],
                    tight=True,
                    spacing=8,
                ),
                actions=[
                    ft.TextButton("完成", on_click=close_manager),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def refresh_table():
        nonlocal current_page
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        current_page = min(current_page, total_pages - 1)
        start = current_page * page_size
        visible_rows = rows[start : start + page_size]

        viewport_width = (
            getattr(page, "width", None)
            or getattr(page.window, "width", None)
            or 1280
        )
        available_width = max(600, viewport_width - 320)
        row_number_width = 82
        column_width = max(
            120,
            (available_width - row_number_width) / max(1, len(columns)),
        )
        grid_width = row_number_width + column_width * len(columns)
        grid_border = "#E4E7EC"

        def metadata_selector(
            value: str,
            options: dict[str, str],
            on_change,
            kind: str,
        ):
            if kind == "type":
                background, foreground = "#EEF2FF", "#4F46E5"
            else:
                background, foreground = {
                    "both": ("#ECFDF3", "#027A48"),
                    "backend": ("#EFF8FF", "#175CD3"),
                    "frontend": ("#FFF7ED", "#C2410C"),
                }[value]

            def select_option(selected: str):
                on_change(selected)
                refresh_table()

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
                            "#C7D2FE" if kind == "type" else {
                                "both": "#ABEFC6",
                                "backend": "#B2DDFF",
                                "frontend": "#FED7AA",
                            }[value],
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
                    min_width=column_width,
                    max_width=column_width,
                ),
                shape=ft.RoundedRectangleBorder(
                    side=ft.BorderSide(1, "#EAECF0"),
                    radius=10,
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
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for name in columns
        ]
        data_type_cells = [
            ft.Container(
                content=metadata_selector(
                    data_type,
                    DATA_TYPES,
                    lambda selected, index=index: set_column_type(
                        index, selected
                    ),
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
            for index, data_type in enumerate(data_types)
        ]
        target_cells = [
            ft.Container(
                content=metadata_selector(
                    target,
                    EXPORT_TARGETS,
                    lambda selected, index=index: set_column_target(
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
            for index, target in enumerate(targets)
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
                on_click=lambda _, index=index: edit_annotation(index),
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )
            for index, annotation in enumerate(annotations)
        ]

        def create_data_cell(
            row: dict[str, Any],
            column: str,
            column_index: int,
            row_index: int,
            is_selected: bool,
        ) -> ft.Container:
            value = row.get(column)
            image_path = resolve_image_path(value, active_table_path)
            cell_content: ft.Control
            if image_path is not None:
                cell_content = ft.Image(
                    src=str(image_path),
                    width=28,
                    height=28,
                    fit=ft.BoxFit.CONTAIN,
                    tooltip=str(value),
                    error_content=ft.Icon(
                        ft.Icons.BROKEN_IMAGE_OUTLINED,
                        size=18,
                        color="#98A2B3",
                    ),
                )
            else:
                cell_content = ft.Text(
                    _display_value_for_type(value, data_types[column_index]),
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
                on_click=lambda _, selected_row=row, selected_column=column: (
                    edit_cell(selected_row, selected_column)
                ),
                border=ft.Border.only(
                    right=ft.BorderSide(1, grid_border),
                    bottom=ft.BorderSide(1, grid_border),
                ),
            )

        grid_rows = []
        for index, row in enumerate(visible_rows):
            row_index = start + index
            is_selected = selected_row_index == row_index
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
                                        on_click=lambda _, selected_row=row: (
                                            confirm_delete_row(selected_row)
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
                            on_click=lambda _, selected_index=row_index: select_row(
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
                                f"第 {row_index + 1} 行",
                                color="#344054",
                                size=12,
                            ),
                            bgcolor="#FFFFFF",
                            border=ft.Border.all(1, "#D0D5DD"),
                            border_radius=6,
                            padding=8,
                        ),
                    ),
                    *[
                        create_data_cell(
                            row,
                            column,
                            column_index,
                            row_index,
                            is_selected,
                        )
                        for column_index, column in enumerate(columns)
                    ],
                ],
                spacing=0,
            )
            grid_rows.append(
                ft.DragTarget(
                    content=row_control,
                    group="configuration-row",
                    on_accept=lambda event, target_index=row_index: reorder_row(
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
                    on_click=add_row,
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
                    width=column_width * max(1, len(columns)),
                    height=42,
                    alignment=ft.Alignment(0, 0),
                    bgcolor="#FFFFFF",
                    on_click=add_row,
                    border=ft.Border.only(
                        bottom=ft.BorderSide(1, grid_border),
                    ),
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
                                content=                                ft.Row(
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
        table_area.controls = [
            ft.Row(
                [grid],
                expand=True,
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
            )
        ]
        row_count_text.value = f"{len(rows):,}"
        column_count_text.value = str(len(columns))
        table_status.value = (
            f"显示第 {start + 1 if rows else 0}–{start + len(visible_rows)} 行，"
            f"共 {len(rows)} 行 · 点击单元格编辑"
        )
        page_status.value = f"共 {len(rows)} 条记录"
        page_number_text.value = f"{current_page + 1} / {total_pages}"
        update_row_action_buttons()
        page.update()

    def load_configuration_file(path: Path):
        nonlocal current_page, selected_row_index, source_name, active_table_path
        path_key = table_path_key(path)
        if (
            active_table_path is not None
            and table_path_key(active_table_path) == path_key
        ):
            return
        cache_active_table()
        try:
            if path_key in table_states:
                state = table_states[path_key]
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
                ) = load_table(path, mobile_file_bytes.get(path_key))
                saved_keys = key_rules_by_table.get(path.name)
                loaded_keys = (
                    [
                        column
                        for column in loaded_columns
                        if column in saved_keys
                    ]
                    if saved_keys is not None
                    else (["id"] if "id" in loaded_columns else [])
                )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            notify(f"打开配置表失败：{exc}", error=True)
            return
        columns[:] = loaded_columns
        data_types[:] = loaded_types
        targets[:] = loaded_targets
        annotations[:] = loaded_annotations
        rows[:] = loaded_rows
        key_columns[:] = loaded_keys
        current_page = 0
        selected_row_index = None
        source_name = path.name
        active_table_path = path
        key_rules_by_table[source_name] = key_columns.copy()
        source_text.value = source_name
        save_export_settings()
        refresh_configuration_files()
        update_row_action_buttons()
        refresh_table()
        notify(f"已打开 {source_name}（{len(rows)} 条记录）")

    async def choose_export_directory(target: str):
        field = (
            backend_directory_field
            if target == "backend"
            else frontend_directory_field
        )
        label = "后端" if target == "backend" else "前端"
        try:
            directory = await picker.get_directory_path(
                dialog_title=f"选择{label}导出目录",
                initial_directory=available_initial_directory(
                    export_paths[target]
                ),
            )
        except (OSError, RuntimeError) as exc:
            notify(f"选择{label}导出目录失败：{exc}", error=True)
            return
        if directory is None:
            return
        export_paths[target] = directory
        field.value = directory
        save_export_settings()
        page.update()

    async def choose_backend_export_directory(_):
        await choose_export_directory("backend")

    async def choose_frontend_export_directory(_):
        await choose_export_directory("frontend")

    async def choose_configuration_directory(_):
        nonlocal configuration_directory
        try:
            directory = await picker.get_directory_path(
                dialog_title="选择 TSV 配置文件目录",
                initial_directory=available_initial_directory(
                    configuration_directory
                ),
            )
        except (OSError, RuntimeError) as exc:
            notify(f"选择配置文件目录失败：{exc}", error=True)
            return
        if directory is None:
            return
        try:
            table_count = count_configuration_tables(directory)
        except OSError as exc:
            notify(f"读取配置文件目录失败：{exc}", error=True)
            return
        configuration_directory = directory
        configuration_directory_field.value = directory
        configuration_table_count.value = f"目录中有 {table_count} 张 TSV 配置表"
        configuration_count_metric.value = str(table_count)
        save_export_settings()
        try:
            refresh_configuration_files()
        except OSError as exc:
            notify(f"读取配置文件目录失败：{exc}", error=True)
            return
        page.update()

    async def choose_mobile_configuration_files(_):
        try:
            selected_files = await picker.pick_files(
                dialog_title="选择 TSV 配置文件",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["tsv"],
                allow_multiple=True,
                with_data=True,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            notify(f"选择 TSV 配置文件失败：{exc}", error=True)
            return
        if not selected_files:
            return

        existing_names = {
            path.name.casefold() for path in mobile_configuration_paths
        }
        added_paths = []
        for selected_file in selected_files:
            if Path(selected_file.name).suffix.casefold() != ".tsv":
                continue
            if selected_file.name.casefold() in existing_names:
                notify(
                    f"已跳过重复文件名「{selected_file.name}」，请先移除同名配置表。",
                    error=True,
                )
                continue
            if not isinstance(selected_file.bytes, bytes):
                notify(
                    f"无法读取「{selected_file.name}」的文件内容，请重新选择。",
                    error=True,
                )
                continue
            path = Path("mobile-files") / selected_file.name
            path_key = table_path_key(path)
            mobile_file_bytes[path_key] = selected_file.bytes
            mobile_configuration_paths.append(path)
            existing_names.add(selected_file.name.casefold())
            added_paths.append(path)

        if added_paths:
            mobile_configuration_paths.sort(key=lambda path: path.name.casefold())
            configuration_table_count.value = (
                f"手机中已选择 {len(mobile_configuration_paths)} 张 TSV 配置表"
            )
            configuration_count_metric.value = str(len(mobile_configuration_paths))
            refresh_configuration_files()
            page.update()
            notify(f"已添加 {len(added_paths)} 张 TSV 配置表。")
        elif not any(
            Path(selected_file.name).suffix.casefold() == ".tsv"
            for selected_file in selected_files
        ):
            notify("请选择 .tsv 配置文件。", error=True)

    def update_configuration_count():
        count = len(configuration_paths())
        configuration_count_metric.value = str(count)
        if mobile_platform:
            configuration_table_count.value = f"手机中有 {count} 张 TSV 配置表"
        elif configuration_directory:
            configuration_table_count.value = f"目录中有 {count} 张 TSV 配置表"
        else:
            configuration_table_count.value = "尚未选择配置目录"

    def create_configuration_file(_):
        name = (new_configuration_name.value or "").strip()
        if name.lower().endswith(".tsv"):
            name = name[:-4]
        invalid_characters = '<>:"/\\|?*'
        if (
            not name
            or name in {".", ".."}
            or name.endswith((".", " "))
            or any(character in invalid_characters for character in name)
            or any(ord(character) < 32 for character in name)
        ):
            new_configuration_name.error_text = "请输入有效的配置表文件名。"
            page.update()
            return

        filename = f"{name}.tsv"
        try:
            existing_names = {
                path.name.casefold() for path in configuration_paths()
            }
        except OSError as exc:
            notify(f"读取配置文件列表失败：{exc}", error=True)
            return
        if filename.casefold() in existing_names:
            new_configuration_name.error_text = "该配置表已存在，请使用其他文件名。"
            page.update()
            return

        path = (
            Path("mobile-files") / filename
            if mobile_platform
            else Path(configuration_directory or "") / filename
        )
        if not mobile_platform and not configuration_directory:
            notify("请先在导出设置中选择 TSV 配置目录。", error=True)
            return

        try:
            initial_content = new_configuration_table_bytes()
            if mobile_platform:
                mobile_configuration_paths.append(path)
                mobile_file_bytes[table_path_key(path)] = initial_content
            else:
                with path.open("xb") as new_file:
                    new_file.write(initial_content)
        except OSError as exc:
            notify(f"新建配置表失败：{exc}", error=True)
            return

        page.pop_dialog()
        load_configuration_file(path)
        if (
            active_table_path is not None
            and table_path_key(active_table_path) == table_path_key(path)
        ):
            mark_active_table_modified()
        update_configuration_count()
        refresh_configuration_files()
        page.update()
        notify(f"已新建配置表「{filename}」")

    def open_new_configuration_dialog(_):
        if not mobile_platform and not configuration_directory:
            notify("请先在导出设置中选择 TSV 配置目录。", error=True)
            return
        new_configuration_name.value = ""
        new_configuration_name.error_text = None
        page.show_dialog(
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
                        new_configuration_name,
                    ],
                    tight=True,
                    width=dialog_width(380),
                    spacing=12,
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                    ft.Button("新建", icon=ft.Icons.ADD, on_click=create_configuration_file),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def delete_active_configuration_file(_):
        path = active_table_path
        if path is None or all(
            table_path_key(item) != table_path_key(path)
            for item in configuration_paths()
        ):
            notify("请先从左侧选择要删除的配置表。", error=True)
            return

        if mobile_platform:
            description = (
                f"从本次会话中移除「{path.name}」？"
                "手机原始文件不会被删除。"
            )
        else:
            description = (
                f"确定从配置目录中永久删除「{path.name}」吗？"
                "此操作无法撤销。"
            )

        def confirm_delete(_):
            nonlocal active_table_path, current_page, source_name
            path_key = table_path_key(path)
            try:
                if mobile_platform:
                    mobile_configuration_paths[:] = [
                        item
                        for item in mobile_configuration_paths
                        if table_path_key(item) != path_key
                    ]
                    mobile_file_bytes.pop(path_key, None)
                else:
                    configuration_root = Path(configuration_directory or "").resolve()
                    resolved_path = path.resolve()
                    if (
                        path.suffix.lower() != ".tsv"
                        or resolved_path.parent != configuration_root
                    ):
                        raise ValueError("只能删除所选配置目录中的 TSV 文件。")
                    path.unlink()
            except (OSError, ValueError) as exc:
                page.pop_dialog()
                notify(f"删除配置表失败：{exc}", error=True)
                return

            table_states.pop(path_key, None)
            modified_table_paths.discard(path_key)
            if active_table_path is not None and table_path_key(active_table_path) == path_key:
                active_table_path = None
                source_name = "未选择配置表"
                columns.clear()
                data_types.clear()
                targets.clear()
                annotations.clear()
                rows.clear()
                key_columns.clear()
                source_text.value = source_name

            page.pop_dialog()
            update_configuration_count()
            refresh_configuration_files()
            remaining_paths = configuration_paths()
            if remaining_paths:
                load_configuration_file(remaining_paths[0])
            else:
                current_page = 0
                refresh_table()
            page.update()
            notify(f"已删除配置表「{path.name}」")

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除配置表"),
                content=ft.Text(description),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
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

    async def export_tables(
        incremental: bool,
        selected_table_paths: list[Path] | None = None,
    ):
        if not configuration_paths():
            notify(
                "请先在导出设置中选择 TSV 配置文件。"
                if mobile_platform
                else "请先在导出设置中选择 TSV 配置目录。",
                error=True,
            )
            return
        selected_backend_format = backend_format_select.value or "lua"
        selected_frontend_format = frontend_format_select.value or "json"
        archive_saved_path: str | None = None
        try:
            if incremental:
                paths = selected_table_paths or sorted(
                    (Path(path) for path in modified_table_paths),
                    key=lambda path: path.name.casefold(),
                )
                if not paths:
                    notify("本次会话没有修改过的配置表。")
                    return
            else:
                paths = configuration_paths()
                if not paths:
                    notify(
                        "没有已选择的 TSV 文件。"
                        if mobile_platform
                        else "配置目录中没有 TSV 文件。",
                        error=True,
                    )
                    return

            prepared_outputs: list[tuple[Path, bytes]] = []
            table_output_paths: list[tuple[Path, list[Path]]] = []
            exported_path_keys: set[str] = set()
            output_backend_directory = (
                "backend" if mobile_platform else export_paths["backend"]
            )
            output_frontend_directory = (
                "frontend" if mobile_platform else export_paths["frontend"]
            )
            for path in paths:
                path_key = table_path_key(path)
                state = table_states.get(path_key)
                if state is None:
                    (
                        table_columns,
                        table_types,
                        table_targets,
                        _,
                        table_rows,
                    ) = load_table(path, mobile_file_bytes.get(path_key))
                    saved_keys = key_rules_by_table.get(path.name)
                    table_keys = (
                        [
                            column
                            for column in table_columns
                            if column in saved_keys
                        ]
                        if saved_keys is not None
                        else (["id"] if "id" in table_columns else [])
                    )
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
                        validate_directories=not mobile_platform,
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"配置表「{path.name}」：{exc}"
                    ) from exc
                prepared_outputs.extend(table_outputs)
                table_output_paths.append(
                    (path, [output_path for output_path, _ in table_outputs])
                )
                exported_path_keys.add(path_key)

            output_keys = [
                os.path.normcase(str(path.resolve()))
                for path, _ in prepared_outputs
            ]
            if len(output_keys) != len(set(output_keys)):
                raise ValueError(
                    "多个配置表生成了相同的导出路径，请检查配置表名称、导出目录和格式。"
                )
            if mobile_platform and prepared_outputs:
                archive_data = build_export_archive(prepared_outputs)
                archive_saved_path = await picker.save_file(
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
                    if not path.parent.is_dir():
                        raise ValueError(f"导出目录不存在：{path.parent}")
                for path, data in prepared_outputs:
                    path.write_bytes(data)
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            notify(f"导出失败：{exc}", error=True)
            return

        modified_table_paths.difference_update(exported_path_keys)
        refresh_configuration_files()
        page.update()
        label = "增量导出" if incremental else "全量导出"
        table_items = []
        for table_path, output_paths in table_output_paths:
            output_description = (
                "、".join(
                    f"{output_path.parent.name}/{output_path.name}"
                    if mobile_platform
                    else str(output_path)
                    for output_path in output_paths
                )
                if output_paths
                else "未生成文件（该表没有启用导出字段）"
            )
            table_items.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                table_path.name,
                                size=12,
                                color="#344054",
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                output_description,
                                size=10,
                                color="#667085",
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=output_description,
                            ),
                        ],
                        spacing=3,
                    ),
                    padding=ft.Padding(10, 8, 10, 8),
                    border=ft.Border.only(
                        bottom=ft.BorderSide(1, "#EAECF0")
                    ),
                )
            )
        summary_text = (
            f"共处理 {len(paths)} 张配置表，生成 {len(prepared_outputs)} 个文件。"
        )
        if archive_saved_path is not None:
            summary_text += f"\nZIP 已保存至：{archive_saved_path}"
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"{label}完成"),
                content=ft.Column(
                    [
                        ft.Text(
                            summary_text,
                            size=12,
                            color="#475467",
                        ),
                        ft.Container(
                            content=ft.Column(
                                table_items,
                                spacing=0,
                                scroll=ft.ScrollMode.AUTO,
                            ),
                            width=dialog_width(540),
                            height=min(420, max(100, len(table_items) * 66)),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                        ),
                    ],
                    tight=True,
                    spacing=12,
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: page.pop_dialog()),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def export_all_files(_):
        await export_tables(incremental=False)

    def export_incremental_files(_):
        dirty_paths = sorted(
            (Path(path) for path in modified_table_paths),
            key=lambda path: (path.name.casefold(), str(path).casefold()),
        )
        if not dirty_paths:
            notify("本次会话没有修改过的配置表。")
            return

        error_text = ft.Text("", size=12, color="#D92D20")
        table_checkboxes: dict[str, ft.Checkbox] = {}
        for path in dirty_paths:
            path_key = table_path_key(path)
            table_checkboxes[path_key] = ft.Checkbox(
                label=path.name,
                value=True,
            )

        async def export_selected_tables(_):
            selected_paths = [
                path
                for path in dirty_paths
                if table_checkboxes[table_path_key(path)].value
            ]
            if not selected_paths:
                error_text.value = "请至少勾选一张配置表。"
                page.update()
                return
            page.pop_dialog()
            await export_tables(
                incremental=True,
                selected_table_paths=selected_paths,
            )

        page.show_dialog(
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
                            width=dialog_width(420),
                            height=min(360, max(100, len(dirty_paths) * 52)),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                            padding=ft.Padding(10, 4, 10, 4),
                        ),
                    ],
                    tight=True,
                    spacing=10,
                    width=dialog_width(440),
                ),
                actions=[
                    ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                    ft.Button(
                        "导出所选",
                        icon=ft.Icons.DOWNLOAD,
                        on_click=export_selected_tables,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def open_mobile_configuration_list(_):
        refresh_configuration_files()
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("选择配置表"),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                mobile_configuration_section_title,
                                ft.IconButton(
                                    icon=ft.Icons.ADD,
                                    tooltip="新建配置表",
                                    on_click=open_new_configuration_dialog,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.FILE_OPEN,
                                    tooltip="从手机导入 TSV",
                                    on_click=choose_mobile_configuration_files,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    tooltip="删除当前配置表",
                                    on_click=delete_active_configuration_file,
                                    disabled=active_table_path is None,
                                ),
                            ],
                            spacing=2,
                        ),
                        mobile_configuration_search_field,
                        ft.Container(
                            content=mobile_configuration_file_list,
                            width=dialog_width(440),
                            height=dialog_height(440, margin=240),
                            border=ft.Border.all(1, "#EAECF0"),
                            border_radius=8,
                            padding=6,
                        ),
                    ],
                    tight=True,
                    spacing=10,
                    width=dialog_width(440),
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: page.pop_dialog()),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def open_export_settings(_):
        if mobile_platform:
            settings_controls = [
                ft.Text(
                    "从手机文件中选择一个或多个 TSV。导出时会保存为 ZIP，内部保留前后端目录结构；"
                    "修改仅保留在当前会话中。",
                    size=12,
                    color="#667085",
                ),
                ft.OutlinedButton(
                    "选择 TSV 文件",
                    icon=ft.Icons.FILE_OPEN,
                    on_click=choose_mobile_configuration_files,
                ),
                configuration_table_count,
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "每列的“导出端”下拉项控制字段输出到前端、后端或两端。",
                    size=12,
                    color="#667085",
                ),
                ft.Text(
                    "后端",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color="#344054",
                ),
                backend_format_select,
                ft.Text(
                    "前端",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color="#344054",
                ),
                frontend_format_select,
            ]
        else:
            settings_controls = [
                ft.Text(
                    "全量导出处理目录中的全部 TSV；增量导出仅处理本次在工具中修改过的表。"
                    "修改只保留在当前会话中，不会写回 TSV。",
                    size=12,
                    color="#667085",
                ),
                ft.Row(
                    [
                        configuration_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=choose_configuration_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                configuration_table_count,
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "每列的“导出端”下拉项控制字段输出到前端、后端或两端。",
                    size=12,
                    color="#667085",
                ),
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "后端",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color="#344054",
                ),
                backend_format_select,
                ft.Row(
                    [
                        backend_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=choose_backend_export_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Divider(height=1, color="#EAECF0"),
                ft.Text(
                    "前端",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color="#344054",
                ),
                frontend_format_select,
                ft.Row(
                    [
                        frontend_directory_field,
                        ft.OutlinedButton(
                            "选择目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=choose_frontend_export_directory,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
            ]
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("导出设置"),
                content=ft.Column(
                    settings_controls,
                    height=dialog_height(540, margin=112),
                    width=dialog_width(640),
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=[
                    ft.TextButton("完成", on_click=lambda _: page.pop_dialog()),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def add_column(_):
        form_error = ft.Text(
            "",
            size=12,
            color="#D92D20",
            visible=False,
        )
        name_input = ft.TextField(
            label="列名",
            hint_text="例如：description",
            autofocus=True,
            on_change=lambda _: clear_column_form_error(form_error, name_input),
        )
        type_input = ft.Dropdown(
            label="数据类型",
            value="string",
            options=[
                ft.DropdownOption(key=key, text=label)
                for key, label in DATA_TYPES.items()
            ],
            width=dialog_width(360),
        )
        target_input = ft.Dropdown(
            label="导出端",
            value="both",
            options=[
                ft.DropdownOption(key=key, text=label)
                for key, label in EXPORT_TARGETS.items()
            ],
            width=dialog_width(360),
        )
        annotation_input = ft.TextField(
            label="注释",
            hint_text="说明该字段的用途",
        )
        default_input = ft.TextField(
            label="默认值",
            hint_text="留空表示空值",
            on_change=lambda _: clear_column_form_error(
                form_error, default_input
            ),
        )
        type_input.on_select = lambda _: clear_column_form_error(
            form_error, type_input
        )
        target_input.on_select = lambda _: clear_column_form_error(
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
                width=dialog_width(400),
                spacing=14,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _: page.pop_dialog()),
                ft.Button(
                    "添加列",
                    icon=ft.Icons.ADD,
                    on_click=lambda _: commit_column(
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
        page.show_dialog(dialog)

    def clear_column_form_error(
        error_text: ft.Text,
        field: ft.TextField | ft.Dropdown | None = None,
    ):
        if field is not None:
            field.error_text = None
        error_text.value = ""
        error_text.visible = False

    def commit_column(
        name_input: ft.TextField,
        type_input: ft.Dropdown,
        target_input: ft.Dropdown,
        annotation_input: ft.TextField,
        default_input: ft.TextField,
        form_error: ft.Text,
    ):
        for field in (name_input, type_input, target_input, default_input):
            field.error_text = None
        clear_column_form_error(form_error)

        def show_error(
            message: str,
            field: ft.TextField | ft.Dropdown | None = None,
        ):
            if field is not None:
                field.error_text = message
            form_error.value = message
            form_error.visible = True
            page.update()

        name = (name_input.value or "").strip()
        if not name:
            show_error("请输入列名。", name_input)
            return
        if name in columns:
            show_error(f"列「{name}」已存在，请使用其他列名。", name_input)
            return
        if type_input.value not in DATA_TYPES:
            show_error("请选择有效的数据类型。", type_input)
            return
        if target_input.value not in EXPORT_TARGETS:
            show_error("请选择有效的导出端。", target_input)
            return
        columns.append(name)
        data_types.append(type_input.value)
        targets.append(target_input.value)
        annotations.append(annotation_input.value or "")
        try:
            default_value = parse_data_value(
                default_input.value or "",
                type_input.value,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            columns.pop()
            data_types.pop()
            targets.pop()
            annotations.pop()
            show_error(f"默认值与数据类型不匹配：{exc}", default_input)
            return
        for row in rows:
            row[name] = default_value
        if name == "id" and not key_columns:
            key_columns.append(name)
        mark_active_table_modified()
        save_export_settings()
        page.pop_dialog()
        refresh_table()
        if column_manager_refresh is not None:
            column_manager_refresh()
        notify(f"已添加列「{name}」")

    def change_page(delta: int):
        nonlocal current_page
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        current_page = min(max(0, current_page + delta), total_pages - 1)
        refresh_table()

    def change_page_size(event):
        nonlocal page_size, current_page
        try:
            selected_size = int(event.control.value)
        except (AttributeError, TypeError, ValueError):
            notify("无法识别每页显示条数。", error=True)
            return
        if selected_size not in PAGE_SIZES:
            notify("每页显示条数无效。", error=True)
            return
        page_size = selected_size
        current_page = 0
        refresh_table()

    page_size_select.on_select = change_page_size

    configuration_delete_button = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE,
        icon_size=18,
        tooltip="删除当前配置表",
        on_click=delete_active_configuration_file,
        disabled=active_table_path is None,
    )
    sidebar = ft.Container(
        width=226,
        bgcolor="#FFFFFF",
        padding=ft.Padding(18, 24, 18, 20),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(ft.Icons.AUTO_AWESOME, color="#FFFFFF", size=19),
                            bgcolor="#5B6CFF",
                            border_radius=10,
                            padding=9,
                        ),
                        ft.Column(
                            [
                                ft.Text("星图", size=16, weight=ft.FontWeight.BOLD, color="#101828"),
                                ft.Text("GAME DATA STUDIO", size=9, color="#98A2B3"),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=10,
                ),
                ft.Container(height=26),
                ft.Text("工作空间", size=11, color="#98A2B3", weight=ft.FontWeight.W_600),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.TABLE_VIEW, color="#5B6CFF", size=18),
                            ft.Text("配置表管理", size=13, color="#344054", weight=ft.FontWeight.W_600),
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
                            icon=ft.Icons.ADD,
                            icon_size=18,
                            tooltip="新建配置表",
                            on_click=open_new_configuration_dialog,
                        ),
                        configuration_delete_button,
                    ],
                    spacing=2,
                ),
                configuration_search_field,
                configuration_file_list_container := ft.Container(
                    content=configuration_file_list,
                    height=240,
                    border=ft.Border.all(1, "#EAECF0"),
                    border_radius=9,
                    padding=6,
                ),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.TIPS_AND_UPDATES_OUTLINED, color="#5B6CFF", size=20),
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
                                ft.Icons.SMART_TOY,
                                size=17,
                                color="#FFFFFF",
                            ),
                            bgcolor="#98A2B3",
                            radius=17,
                        ),
                        ft.Column(
                            [
                                ft.Text("游戏配置助手", size=12, weight=ft.FontWeight.W_600),
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

    mobile_configuration_button = ft.OutlinedButton(
        "配置表",
        icon=ft.Icons.TABLE_VIEW,
        on_click=open_mobile_configuration_list,
        visible=False,
    )
    header_actions = ft.Row(
        [
            mobile_configuration_button,
            ft.OutlinedButton(
                "导出设置",
                icon=ft.Icons.SETTINGS_OUTLINED,
                on_click=open_export_settings,
            ),
            ft.Button(
                "全量导出",
                icon=ft.Icons.DOWNLOAD,
                on_click=export_all_files,
            ),
            ft.OutlinedButton(
                "增量导出",
                icon=ft.Icons.CHANGE_CIRCLE_OUTLINED,
                on_click=export_incremental_files,
            ),
        ],
        spacing=8,
        wrap=True,
        run_spacing=8,
    )
    header_title = ft.Column(
        [
            ft.Text("配置表管理", size=23, weight=ft.FontWeight.BOLD, color="#101828"),
            ft.Text("查看、扩展并导出游戏配置数据", size=12, color="#667085"),
        ],
        spacing=5,
    )
    header_spacer = ft.Container(expand=True)
    header_content = ft.Row(
        [header_title, header_spacer, header_actions],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=False,
        run_spacing=10,
    )
    header = ft.Container(
        content=header_content,
        padding=ft.Padding(28, 22, 28, 18),
    )

    table_header_title = ft.Column(
        [
            ft.Text("配置表编辑", size=16, weight=ft.FontWeight.W_600, color="#101828"),
            ft.Row(
                [
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14, color="#667085"),
                    source_text,
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
                on_click=open_export_rule,
            ),
            ft.OutlinedButton(
                "管理列",
                icon=ft.Icons.VIEW_COLUMN_OUTLINED,
                on_click=open_column_manager,
            ),
        ],
        spacing=8,
        wrap=True,
        alignment=ft.MainAxisAlignment.END,
    )
    row_copy_button = ft.OutlinedButton(
        "复制行",
        icon=ft.Icons.CONTENT_COPY,
        on_click=copy_selected_row,
        disabled=True,
        tooltip="复制选中行（Ctrl+C）",
    )
    row_paste_button = ft.OutlinedButton(
        "插入行",
        icon=ft.Icons.CONTENT_PASTE,
        on_click=paste_copied_row,
        disabled=True,
        tooltip="在选中行之前插入副本，原行下移（Ctrl+V）",
    )
    row_undo_button = ft.OutlinedButton(
        "撤销",
        icon=ft.Icons.UNDO,
        on_click=undo_row_action,
        disabled=True,
        tooltip="撤销最近一次行或单元格数据操作（Ctrl+Z）",
    )
    update_row_action_buttons()
    table_header_spacer = ft.Container(expand=True)
    table_header_row = ft.Row(
        [table_header_title, table_header_spacer, table_header_actions],
        spacing=8,
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=False,
        run_spacing=8,
    )
    row_action_toolbar = ft.Row(
        [
            selected_row_status,
            row_copy_button,
            row_paste_button,
            row_undo_button,
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
    table_footer_status = ft.Row(
        [
            table_status,
            page_size_select,
        ],
        expand=True,
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    table_footer_pagination = ft.Row(
        [
            ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT,
                tooltip="上一页",
                on_click=lambda _: change_page(-1),
            ),
            page_number_text,
            ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT,
                tooltip="下一页",
                on_click=lambda _: change_page(1),
            ),
        ],
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    table_footer_row = ft.Row(
        [table_footer_status, table_footer_pagination],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=False,
        run_spacing=4,
    )
    table_card = ft.Container(
        content=ft.Column(
            [
                table_header_row,
                row_action_section,
                ft.Divider(height=1, color="#EAECF0"),
                table_area,
                ft.Divider(height=1, color="#EAECF0"),
                table_footer_row,
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

    metric_cards = [
        metric_card(
            "配置行数",
            row_count_text,
            ft.Icons.FORMAT_LIST_NUMBERED,
            "#5B6CFF",
        ),
        metric_card(
            "配置列数",
            column_count_text,
            ft.Icons.VIEW_COLUMN_OUTLINED,
            "#12B76A",
        ),
        metric_card(
            "当前分页",
            page_status,
            ft.Icons.AUTO_STORIES_OUTLINED,
            "#F79009",
        ),
        metric_card(
            "配置表数量",
            configuration_count_metric,
            ft.Icons.TABLE_VIEW,
            "#7F56D9",
        ),
    ]
    metrics_row = ft.Row(
        metric_cards,
        spacing=14,
        wrap=False,
        run_spacing=8,
    )
    content_body = ft.Container(
        content=ft.Column(
            [
                metrics_row,
                table_card,
            ],
            spacing=18,
            expand=True,
        ),
        padding=ft.Padding(28, 0, 28, 24),
        expand=True,
    )
    content = ft.Column(
        [
            header,
            content_body,
        ],
        spacing=0,
        expand=True,
    )

    workspace = ft.Row(
        [
            sidebar,
            ft.Container(content=content, expand=True),
        ],
        spacing=0,
        expand=True,
    )
    page.add(workspace)

    def apply_responsive_layout():
        width = page.width if page.width and page.width > 0 else 1024
        height = page.height if page.height and page.height > 0 else 768
        compact = width < 820
        configuration_file_list_container.height = max(
            96,
            min(240, int(height - 500)),
        )
        sidebar.visible = not compact
        mobile_configuration_button.visible = compact
        header.padding = (
            ft.Padding(14, 16, 14, 12)
            if compact
            else ft.Padding(28, 22, 28, 18)
        )
        header_title.controls[0].size = 20 if compact else 23
        header_content.run_spacing = 8 if compact else 10
        header_content.wrap = compact
        header_spacer.visible = not compact
        header_actions.spacing = 6 if compact else 8
        content_body.padding = (
            ft.Padding(12, 0, 12, 12)
            if compact
            else ft.Padding(28, 0, 28, 24)
        )
        for card in metric_cards:
            card.expand = not compact
            card.width = max(132, int((width - 44) / 2)) if compact else None
            card.padding = 12 if compact else 18
        table_card.padding = 12 if compact else 18
        metrics_row.wrap = compact
        table_header_row.run_spacing = 6 if compact else 8
        table_header_row.wrap = compact
        table_header_spacer.visible = not compact
        table_footer_row.wrap = compact
        table_status.visible = not compact
        table_footer_status.expand = not compact

    def handle_resize(_):
        apply_responsive_layout()
        refresh_table()

    page.on_resize = handle_resize
    page.on_keyboard_event = handle_row_shortcuts
    apply_responsive_layout()
    refresh_table()
    startup_errors = []
    unavailable_configuration_directory = None
    if configuration_directory and not mobile_platform:
        if not Path(configuration_directory).is_dir():
            unavailable_configuration_directory = configuration_directory
            configuration_table_count.value = "已保存的配置目录当前无法访问"
            configuration_file_list.controls = [
                ft.Column(
                    [
                        ft.Icon(
                            ft.Icons.FOLDER_OFF_OUTLINED,
                            size=22,
                            color="#98A2B3",
                        ),
                        ft.Text(
                            "配置目录暂不可用",
                            size=11,
                            weight=ft.FontWeight.W_600,
                            color="#344054",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "检查磁盘或网络，或重新选择目录。",
                            size=10,
                            color="#667085",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.TextButton(
                            "更换目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=choose_configuration_directory,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=6,
                    expand=True,
                )
            ]
        else:
            try:
                table_count = count_configuration_tables(configuration_directory)
                configuration_table_count.value = (
                    f"目录中有 {table_count} 张 TSV 配置表"
                )
                configuration_count_metric.value = str(table_count)
                refresh_configuration_files()
            except OSError as exc:
                configuration_file_list.controls = [
                    ft.Text("无法读取配置目录。", size=11, color="#B42318")
                ]
                startup_errors.append(f"读取已保存的配置目录失败：{exc}")
    elif mobile_platform:
        refresh_configuration_files()
    if settings_load_error:
        startup_errors.append(settings_load_error)
    if startup_errors:
        notify("；".join(startup_errors), error=True)
    elif unavailable_configuration_directory is not None:
        notify(
            "保存的配置目录暂时无法访问，原路径已保留。"
            "请检查磁盘或网络连接，或点击配置表列表中的“更换目录”。"
        )


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.FLET_APP)
