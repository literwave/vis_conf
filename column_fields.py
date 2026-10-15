_TYPE_ALIASES = {
    "string": "string",
    "str": "string",
    "字符串": "string",
    "integer": "integer",
    "int": "integer",
    "整数": "integer",
    "number": "number",
    "float": "number",
    "小数": "number",
    "数字": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "布尔": "boolean",
    "布尔值": "boolean",
    "json": "json",
    "lua_array": "lua_array",
    "lua数组": "lua_array",
    "lua_object": "lua_object",
    "lua字典": "lua_object",
    "lua表": "lua_object",
}
_TARGET_ALIASES = {
    "both": "both",
    "前后端": "both",
    "两端": "both",
    "backend": "backend",
    "后端": "backend",
    "仅后端": "backend",
    "frontend": "frontend",
    "前端": "frontend",
    "仅前端": "frontend",
}


def normalize_column_type(value: str) -> str | None:
    return _TYPE_ALIASES.get(value.strip().casefold()) or _TYPE_ALIASES.get(value.strip())


def normalize_export_target(value: str) -> str | None:
    return _TARGET_ALIASES.get(value.strip().casefold()) or _TARGET_ALIASES.get(value.strip())
