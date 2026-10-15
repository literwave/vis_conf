import copy
from dataclasses import dataclass
from typing import Any, Callable

from column_fields import normalize_column_type, normalize_export_target


@dataclass
class PreparedAgentEdit:
    preview_lines: list[str]
    columns: list[str]
    data_types: list[str]
    targets: list[str]
    annotations: list[str]
    key_columns: list[str]
    rows: list[dict[str, Any]]
    original_columns: list[str]
    original_types: list[str]
    original_targets: list[str]
    original_annotations: list[str]
    original_keys: list[str]
    original_rows: list[dict[str, Any]]


def prepare_agent_edit(
    columns: list[str],
    data_types: list[str],
    targets: list[str],
    annotations: list[str],
    key_columns: list[str],
    rows: list[dict[str, Any]],
    proposal: dict[str, Any],
    visible_row_numbers: set[int],
    parse_value: Callable[[Any, str], Any],
    display_value: Callable[[Any], str],
    type_labels: dict[str, str],
    target_labels: dict[str, str],
) -> tuple[str | None, PreparedAgentEdit | None]:
    """Turn an agent proposal into a table snapshot, or an error message."""
    column_additions = proposal["column_additions"]
    column_deletions = proposal["column_deletions"]
    candidate_rows = copy.deepcopy(rows)
    candidate_columns = columns.copy()
    candidate_types = data_types.copy()
    candidate_targets = targets.copy()
    candidate_annotations = annotations.copy()
    candidate_keys = key_columns.copy()
    preview_lines: list[str] = []
    seen_cells: set[tuple[int, str]] = set()
    added_names: list[str] = []
    deleted_names: list[str] = []

    for raw_name in column_deletions:
        column_name = raw_name.strip()
        if column_name not in candidate_columns:
            return f"不存在字段「{column_name}」，已拒绝删除。", None
        if column_name in deleted_names:
            return f"字段「{column_name}」被重复删除，已拒绝。", None
        deleted_names.append(column_name)

    normalized_additions: list[tuple[str, str, str, str, Any]] = []
    for addition in column_additions:
        column_name = addition["name"].strip()
        column_type = normalize_column_type(addition["type"])
        column_target = normalize_export_target(addition.get("target") or "both")
        if not column_name:
            return "新增列缺少列名，已拒绝。", None
        if column_name in deleted_names or column_name in added_names:
            return f"字段「{column_name}」不能在同一次建议中重复新增或删除。", None
        if column_name in candidate_columns:
            return f"字段「{column_name}」已存在，已拒绝新增。", None
        if column_type is None:
            return f"字段「{column_name}」的数据类型无效，已拒绝新增。", None
        if column_target is None:
            return f"字段「{column_name}」的导出端无效，已拒绝新增。", None
        added_names.append(column_name)
        normalized_additions.append(
            (column_name, column_type, column_target, addition.get("annotation") or "", addition)
        )

    for column_name in deleted_names:
        index = candidate_columns.index(column_name)
        candidate_columns.pop(index)
        candidate_types.pop(index)
        candidate_targets.pop(index)
        candidate_annotations.pop(index)
        candidate_keys = [key for key in candidate_keys if key != column_name]
        for row in candidate_rows:
            row.pop(column_name, None)
        preview_lines.append(f"删除列 · {column_name}")

    for column_name, column_type, column_target, annotation, addition in normalized_additions:
        try:
            default_value = parse_value(addition.get("default", ""), column_type)
        except (ValueError, TypeError) as exc:
            return f"字段「{column_name}」的默认值无效：{exc}", None
        candidate_columns.append(column_name)
        candidate_types.append(column_type)
        candidate_targets.append(column_target)
        candidate_annotations.append(annotation)
        for row in candidate_rows:
            row[column_name] = default_value
        if column_name == "id" and not candidate_keys:
            candidate_keys.append(column_name)
        preview_lines.append(
            f"新增列 · {column_name}："
            f"{type_labels[column_type]} · {target_labels[column_target]}，"
            f"默认 {display_value(default_value) or '（空）'}"
        )

    for change in proposal["changes"]:
        row_number = change["row"]
        column = change["column"]
        cell = (row_number, column)
        if row_number not in visible_row_numbers:
            return f"第 {row_number} 行不在当前可见页，已拒绝应用建议。", None
        if column not in candidate_columns:
            return f"不存在字段「{column}」，已拒绝应用建议。", None
        if column in deleted_names:
            return f"字段「{column}」已在本次建议中删除，不能再修改单元格。", None
        if cell in seen_cells:
            return f"Agent 对第 {row_number} 行「{column}」给出重复修改，已拒绝。", None
        if change["value"] is None:
            return "Agent 提议了 null 值，已拒绝应用建议。", None
        try:
            new_value = parse_value(change["value"], candidate_types[candidate_columns.index(column)])
        except (ValueError, TypeError) as exc:
            return f"第 {row_number} 行字段「{column}」类型无效：{exc}", None
        if new_value is None:
            return f"第 {row_number} 行字段「{column}」为空，已拒绝应用建议。", None
        seen_cells.add(cell)
        previous_value = candidate_rows[row_number - 1].get(column)
        candidate_rows[row_number - 1][column] = new_value
        preview_lines.append(
            f"第 {row_number} 行 · {column}："
            f"{display_value(previous_value) or '（空）'} → {display_value(new_value)}"
        )

    return None, PreparedAgentEdit(
        preview_lines=preview_lines,
        columns=candidate_columns,
        data_types=candidate_types,
        targets=candidate_targets,
        annotations=candidate_annotations,
        key_columns=candidate_keys,
        rows=candidate_rows,
        original_columns=columns.copy(),
        original_types=data_types.copy(),
        original_targets=targets.copy(),
        original_annotations=annotations.copy(),
        original_keys=key_columns.copy(),
        original_rows=copy.deepcopy(rows),
    )
