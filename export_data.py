from pathlib import Path
import io
import json
import math
import os
import re
import zipfile
from typing import Any
from schema import EXPORT_TARGETS
from table_file import _lua_value_pretty, parse_data_value


KEY_RULES_FILENAME = "key_rules.json"


def resolve_key_columns(
    columns: list[str], saved_keys: list[str] | None
) -> list[str]:
    """Pick export keys. A missing rule defaults to the id column, matching Id or id."""
    by_name = {}
    for column in columns:
        by_name.setdefault(column.casefold(), column)
    if saved_keys is None:
        id_column = by_name.get("id")
        return [id_column] if id_column else []
    resolved = []
    for key in saved_keys:
        if not isinstance(key, str):
            continue
        actual = by_name.get(key.casefold())
        if actual and actual not in resolved:
            resolved.append(actual)
    return resolved


def load_directory_key_rules(directory: str | None) -> dict[str, list[str]]:
    if not directory:
        return {}
    path = Path(directory) / KEY_RULES_FILENAME
    if not path.is_file():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(saved, dict):
        return {}
    rules = {}
    for name, keys in saved.items():
        if isinstance(name, str) and isinstance(keys, list):
            rules[name] = [key for key in keys if isinstance(key, str)]
    return rules


def store_directory_key_rules(directory: str | None, rules: dict[str, list[str]]) -> None:
    if not directory:
        return
    root = Path(directory)
    path = root / KEY_RULES_FILENAME
    if not path.is_file():
        return
    table_names = {item.name for item in root.glob("*.tsv")}
    stored = {
        name: list(rules.get(name, []))
        for name in sorted(table_names)
        if name in rules
    }
    path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _significant_lua(data: bytes) -> str:
    text = data.decode("utf-8")
    output: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        character = text[index]
        if in_string:
            output.append(character)
            if character == "\\":
                index += 1
                if index < len(text):
                    output.append(text[index])
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
            output.append(character)
        elif not character.isspace():
            output.append(character)
        index += 1
    return "".join(output)


def export_content_changed(path: Path, data: bytes) -> bool:
    """True when the new export changes values. Indent and a final newline do not count."""
    try:
        current = path.read_bytes()
    except OSError:
        return True
    if current == data:
        return False
    suffix = path.suffix.casefold()
    try:
        if suffix == ".json":
            return json.loads(current) != json.loads(data)
        if suffix == ".lua":
            return _significant_lua(current) != _significant_lua(data)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return True
    return True


_ENUM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _only_id_columns(columns: list[str]) -> bool:
    return len(columns) == 1 and columns[0].casefold() == "id"


def server_enum_directory(backend_directory: str) -> Path:
    """后端目录是 server/res 时，枚举写到旁边的 server/enum。"""
    return Path(backend_directory).parent / "enum"


def _archive_name(path: Path) -> str:
    parent = path.parent
    if parent.name == "enum":
        return f"enum/{path.name}"
    if parent.name not in {"backend", "frontend"}:
        raise ValueError(f"无效的导出端目录：{parent.name}")
    return f"{parent.name}/{path.name}"


def build_export_archive(outputs: list[tuple[Path, bytes]]) -> bytes:
    archive_buffer = io.BytesIO()
    seen_names: set[str] = set()
    with zipfile.ZipFile(
        archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path, data in outputs:
            archive_name = _archive_name(path)
            if archive_name in seen_names:
                raise ValueError(f"ZIP 中存在重复文件：{archive_name}")
            seen_names.add(archive_name)
            archive.writestr(archive_name, data)
    return archive_buffer.getvalue()


def _enum_entries(
    source_name: str,
    columns: list[str],
    data_types: list[str],
    rows: list[dict[str, Any]],
) -> tuple[str, list[tuple[str, int]]]:
    if "Enum" not in columns:
        raise ValueError("导出枚举需要 Enum 字段。")
    id_column = next((column for column in columns if column.casefold() == "id"), None)
    if id_column is None:
        raise ValueError("导出枚举需要 Id 字段。")
    enum_name = Path(source_name).stem
    if _ENUM_NAME.fullmatch(enum_name) is None:
        raise ValueError(f"配置表名「{enum_name}」不能作为枚举名。")
    enum_type = data_types[columns.index("Enum")]
    id_type = data_types[columns.index(id_column)]
    entries: list[tuple[str, int]] = []
    seen_names: dict[str, int] = {}
    for row_number, row in enumerate(rows, start=1):
        variable = parse_data_value(row.get("Enum", ""), enum_type)
        number = parse_data_value(row.get(id_column, ""), id_type)
        if not isinstance(variable, str) or not variable.strip():
            raise ValueError(f"第 {row_number} 行的 Enum 不能为空。")
        variable = variable.strip()
        if _ENUM_NAME.fullmatch(variable) is None:
            raise ValueError(f"第 {row_number} 行的 Enum「{variable}」不是合法的变量名。")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError(f"第 {row_number} 行的 {id_column} 必须是整数。")
        previous_row = seen_names.get(variable)
        if previous_row is not None:
            raise ValueError(
                f"第 {row_number} 行与第 {previous_row} 行的 Enum「{variable}」重复。"
            )
        seen_names[variable] = row_number
        entries.append((variable, number))
    return enum_name, entries


def export_server_enum(
    source_name: str,
    columns: list[str],
    data_types: list[str],
    rows: list[dict[str, Any]],
) -> bytes:
    _, entries = _enum_entries(source_name, columns, data_types, rows)
    body = "\n".join((f"    {variable} = {number}," for variable, number in entries))
    header = (
        "-- author: liter_wave\n"
        "-- Generated by: 星图 · 游戏配置导表工具\n"
        f"-- Source TSV: {source_name}\n\n"
    )
    return f"{header}return {{\n{body}\n}}\n".encode("utf-8")


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
    if any((key_column not in columns for key_column in key_columns or [])):
        raise ValueError("导出 key 字段必须来自当前配置表。")
    data = _index_export_records(records, key_columns, json_keys=True)
    data = _omit_null_values(data)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _omit_null_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _omit_null_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_omit_null_values(item) for item in value if item is not None]
    return value


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
    if any((key_column not in columns for key_column in key_columns or [])):
        raise ValueError("导出 key 字段必须来自当前配置表。")
    data = _index_export_records(records, key_columns)
    data = _omit_null_values(data)
    source_label = source_name or "未知配置表"
    header = f"-- author: liter_wave\n-- Generated by: 星图 · 游戏配置导表工具\n-- Source TSV: {source_label}\n\n"
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
            if isinstance(key_value, float) and (not math.isfinite(key_value)):
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
                (f"{column}={value}" for column, value in zip(key_columns, path))
            )
            raise ValueError(
                f"第 {row_number} 行与第 {conflicting_row_number} 行的 key 组合重复或层级冲突（{key_description}），请检查该表的 key 字段是否重复或存在层级冲突。"
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
    if any((target not in EXPORT_TARGETS for target in targets)):
        raise ValueError("存在无效的列导出端配置。")
    enum_columns = columns
    enum_types = data_types
    enum_rows = rows
    if "Enum" in columns:
        if not backend_directory:
            raise ValueError("请先选择后端导出目录。")
        kept = [index for index, column in enumerate(columns) if column != "Enum"]
        columns = [columns[index] for index in kept]
        data_types = [data_types[index] for index in kept]
        targets = [targets[index] for index in kept]
        key_columns = [key for key in key_columns or [] if key != "Enum"] or None
    backend_indexes = [
        index for index, target in enumerate(targets) if target in {"backend", "both"}
    ]
    frontend_indexes = [
        index for index, target in enumerate(targets) if target in {"frontend", "both"}
    ]
    if backend_indexes and (not backend_directory):
        raise ValueError("请先选择后端导出目录。")
    if frontend_indexes and (not frontend_directory):
        raise ValueError("请先选择前端导出目录。")
    if backend_indexes:
        missing_keys = [
            key
            for key in key_columns or []
            if key not in columns
            or targets[columns.index(key)] not in {"backend", "both"}
        ]
        if missing_keys:
            raise ValueError(
                "后端导出 key 字段未勾选后端导出：" + "、".join(missing_keys) + "。"
            )
    if frontend_indexes:
        missing_keys = [
            key
            for key in key_columns or []
            if key not in columns
            or targets[columns.index(key)] not in {"frontend", "both"}
        ]
        if missing_keys:
            raise ValueError(
                "前端导出 key 字段未勾选前端导出：" + "、".join(missing_keys) + "。"
            )
    stem = Path(source_name).stem
    outputs: list[tuple[Path, bytes]] = []
    if backend_indexes and not _only_id_columns(
        [columns[index] for index in backend_indexes]
    ):
        selected_columns = [columns[index] for index in backend_indexes]
        selected_types = [data_types[index] for index in backend_indexes]
        selected_rows = [
            {column: row.get(column, "") for column in selected_columns} for row in rows
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
    if frontend_indexes and not _only_id_columns(
        [columns[index] for index in frontend_indexes]
    ):
        selected_columns = [columns[index] for index in frontend_indexes]
        selected_types = [data_types[index] for index in frontend_indexes]
        selected_rows = [
            {column: row.get(column, "") for column in selected_columns} for row in rows
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
    if "Enum" in enum_columns:
        server_enum_path = server_enum_directory(backend_directory) / f"{stem}.lua"
        if validate_directories:
            server_enum_path.parent.mkdir(parents=True, exist_ok=True)
        outputs.append(
            (
                server_enum_path,
                export_server_enum(source_name, enum_columns, enum_types, enum_rows),
            )
        )
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


def checked_export_directory(label: str, raw: str | None) -> str | None:
    text = (raw or "").strip().strip('"')
    if text in {"", "尚未选择"}:
        return None
    path = Path(text)
    if not path.exists():
        raise ValueError(f"{label}不存在：{text}")
    if not path.is_dir():
        raise ValueError(f"{label}不是文件夹：{text}")
    return str(path)


def remove_stale_export_files(
    directory: str | None, extension: str, kept_paths: set[str]
) -> list[Path]:
    if not directory or extension not in {"lua", "json", "ts"}:
        return []
    root = Path(directory)
    if not root.is_dir():
        return []
    suffix = f".{extension}"
    removed: list[Path] = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() != suffix:
            continue
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError as exc:
            raise ValueError(f"无法检查导出文件 {path.name}：{exc}") from exc
        if key in kept_paths:
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise ValueError(f"无法删除已没有对应配置表的文件 {path.name}：{exc}") from exc
        removed.append(path)
    return removed


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
        if path.parent.name == "enum":
            path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and not export_content_changed(path, data):
            written_paths.append(path)
            continue
        path.write_bytes(data)
        written_paths.append(path)
    return written_paths
