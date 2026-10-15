from pathlib import Path
import ast
import copy
import csv
import io
import json
import re
from typing import Any
from schema import DATA_TYPES, EXPORT_TARGETS


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
        records = list(
            csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter="\t")
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"TSV 文件无法读取：{exc}") from exc
    records = [record for record in records if record]
    if len(records) < 4:
        raise ValueError("TSV 文件至少需要字段名、数据类型、导出端和注释四行。")
    columns = [name.strip() for name in records[0]]
    if not columns or any((not name for name in columns)):
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
            raise ValueError(
                f"第 {line_number} 行有 {len(record)} 列，应为 {len(columns)} 列。"
            )
        row = {}
        for column, value, data_type in zip(columns, record, data_types):
            try:
                row[column] = parse_data_value(value, data_type)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"第 {line_number} 行字段「{column}」不符合{DATA_TYPES[data_type]}类型：{exc}"
                ) from exc
        rows.append(row)
    return (columns, data_types, targets, annotations, rows)


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
        (
            [
                _display_value_for_type(row.get(column), data_types[index])
                for index, column in enumerate(columns)
            ]
            for row in rows
        )
    )
    return output.getvalue().encode("utf-8")


def new_configuration_table_bytes() -> bytes:
    return export_tsv(["id"], ["integer"], ["both"], ["唯一标识"], [])


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
    rows: list[dict[str, Any]], row: dict[str, Any], insert_index: int
) -> int:
    if not 0 <= insert_index <= len(rows):
        raise IndexError("粘贴位置超出范围。")
    rows.insert(insert_index, copy.deepcopy(row))
    return insert_index


def _display_value_for_type(value: Any, data_type: str) -> str:
    if data_type in {"lua_array", "lua_object"} and value is not None:
        return _lua_value(value)
    return _display_value(value)


class _LuaTableParser:

    def __init__(self, source: str):
        source = source.strip()
        if re.match("^return\\b", source):
            source = source[6:].lstrip()
        self.source = source
        self.position = 0

    def parse(self) -> Any:
        value = self._parse_value()
        self._skip_whitespace()
        if self.position != len(self.source):
            raise ValueError(f"Lua 表后有无法识别的内容：{self.source[self.position:]}")
        if not isinstance(value, (list, dict)):
            raise ValueError('请输入 Lua 表，例如 {1, 2} 或 {name = "value"}')
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
                    value = ast.literal_eval(self.source[start : self.position])
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
            "-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?",
            self.source[self.position :],
        )
        if number:
            token = number.group()
            self.position += len(token)
            return (
                float(token) if any((mark in token for mark in ".eE")) else int(token)
            )
        identifier = re.match("[A-Za-z_][A-Za-z0-9_]*", self.source[self.position :])
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
                    "[A-Za-z_][A-Za-z0-9_]*\\s*=", self.source[self.position :]
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
            if not all((type(key) is int for key in parsed)):
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
    if (
        data_type == "integer"
        and isinstance(value, int)
        and (not isinstance(value, bool))
    ):
        return value
    if (
        data_type == "number"
        and isinstance(value, (int, float))
        and (not isinstance(value, bool))
    ):
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
        return f'''"{''.join(escaped)}"'''
    if isinstance(value, list):
        return "{ " + ", ".join((_lua_value(item) for item in value)) + " }"
    if isinstance(value, dict):
        entries = (
            f"[{_lua_value(key)}] = {_lua_value(item)}" for key, item in value.items()
        )
        return "{ " + ", ".join(entries) + " }"
    raise TypeError(f"Lua 导出不支持 {type(value).__name__} 类型。")


def _lua_value_pretty(value: Any, indent: int = 0) -> str:
    if isinstance(value, list):
        if not value:
            return "{}"
        child_indent = indent + 4
        entries = ",\n".join(
            (
                " " * child_indent + _lua_value_pretty(item, child_indent)
                for item in value
            )
        )
    elif isinstance(value, dict):
        if not value:
            return "{}"
        child_indent = indent + 4
        entries = ",\n".join(
            (
                " " * child_indent
                + f"[{_lua_value(key)}] = {_lua_value_pretty(item, child_indent)}"
                for key, item in value.items()
            )
        )
    else:
        return _lua_value(value)
    return "{\n" + entries + "\n" + " " * indent + "}"
