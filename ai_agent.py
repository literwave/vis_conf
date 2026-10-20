import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CREDENTIAL_SERVICE = "GameConfigAssistant"
CREDENTIAL_USERNAME = "openai-compatible-api-key"
API_PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "credential": "openai-api-key",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "credential": "deepseek-api-key",
    },
}
_WORKSPACE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出配置目录中的文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取配置目录中的文本文件。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "把文本写入配置目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]
MAX_AGENT_OUTPUT_BYTES = 2_000_000
MAX_AGENT_INPUT_BYTES = 1_000_000
MAX_CURSOR_PROMPT_CHARS = 24_000
_CURSOR_VERSION_DIR = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-\d{2}-\d{2}-\d{2})?-[0-9a-f]+$"
)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def validate_api_settings(base_url: str, model: str) -> tuple[str, str]:
    normalized_url = base_url.strip().rstrip("/")
    parsed_url = urllib.parse.urlsplit(normalized_url)
    normalized_model = model.strip()
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("API 地址必须是有效的 HTTPS 基础 URL，不能包含凭据或查询参数。")
    if not normalized_model:
        raise ValueError("请填写模型名称。")
    return normalized_url, normalized_model


def load_api_key() -> str | None:
    try:
        import keyring

        return keyring.get_password(CREDENTIAL_SERVICE, CREDENTIAL_USERNAME)
    except Exception as exc:
        raise RuntimeError(f"无法访问系统凭据库：{exc}") from exc


def save_api_key(api_key: str | None) -> None:
    save_provider_api_key("openai-compatible", api_key)


def load_provider_api_key(provider: str) -> str | None:
    username = API_PROVIDERS[provider]["credential"]
    try:
        import keyring

        return keyring.get_password(CREDENTIAL_SERVICE, username)
    except Exception as exc:
        raise RuntimeError(f"无法访问系统凭据库：{exc}") from exc


def save_provider_api_key(provider: str, api_key: str | None) -> None:
    username = (
        API_PROVIDERS[provider]["credential"]
        if provider in API_PROVIDERS
        else CREDENTIAL_USERNAME
    )
    try:
        import keyring

        if api_key:
            keyring.set_password(CREDENTIAL_SERVICE, username, api_key)
        else:
            keyring.delete_password(CREDENTIAL_SERVICE, username)
    except Exception as exc:
        raise RuntimeError(f"无法安全保存 API Key：{exc}") from exc


def _workspace_file(root: Path, raw: str) -> Path:
    text = (raw or ".").strip() or "."
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("路径超出配置目录。")
    return resolved


def _run_workspace_tool(root: Path, name: str, arguments: dict[str, Any], allow_write: bool) -> str:
    try:
        if name == "list_files":
            path = _workspace_file(root, str(arguments.get("path") or "."))
            if not path.is_dir():
                return "不是目录。"
            return "\n".join(sorted(item.name for item in path.iterdir())) or "目录是空的。"
        if name == "read_file":
            path = _workspace_file(root, str(arguments.get("path") or ""))
            return path.read_text(encoding="utf-8")
        if name == "write_file":
            if not allow_write:
                return "当前是只读模式，不能写文件。"
            path = _workspace_file(root, str(arguments.get("path") or ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(arguments.get("content") or ""), encoding="utf-8", newline="\n")
            return f"已写入 {path.relative_to(root.resolve())}"
        return f"未知工具 {name}"
    except (OSError, UnicodeError, ValueError) as exc:
        return str(exc)


def _chat_completion(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
    if tools:
        body["tools"] = tools
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_AGENT_INPUT_BYTES:
        raise RuntimeError("请求过大，请缩小文件或缩短对话后重试。")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_RejectRedirects)
        with opener.open(request, timeout=120) as response:
            response_body = response.read(MAX_AGENT_OUTPUT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        details = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"模型服务返回 HTTP {exc.code}：{details}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接模型服务：{exc}") from exc
    if len(response_body) > MAX_AGENT_OUTPUT_BYTES:
        raise RuntimeError("模型服务响应过大，已停止读取。")
    try:
        result = json.loads(response_body)
        message = result["choices"][0]["message"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型服务响应格式无效，预期 OpenAI 兼容的 chat completion。") from exc
    if not isinstance(message, dict):
        raise RuntimeError("模型服务响应格式无效，预期 OpenAI 兼容的 chat completion。")
    return message


async def run_api_workspace(
    provider: str,
    workspace: str,
    prompt: str,
    *,
    mode: str = "agent",
    model: str = "",
    api_key: str,
    history: list[dict[str, str]] | None = None,
    active_table: str | None = None,
) -> str:
    if provider not in API_PROVIDERS:
        raise ValueError("模型服务只能是 OpenAI 或 DeepSeek。")
    if mode not in {"ask", "agent"}:
        raise ValueError("模式只能选择 ask 或 agent。")
    root = Path(workspace)
    if not root.is_dir():
        raise RuntimeError("配置目录不存在。请先在导出设置里选择配置文件目录。")
    if not api_key.strip():
        raise RuntimeError("请先在连接设置里保存 API Key。")
    profile = API_PROVIDERS[provider]
    selected_model = model.strip() or profile["default_model"]
    base_url, selected_model = validate_api_settings(profile["base_url"], selected_model)
    allow_write = mode == "agent"
    tools = [
        tool
        for tool in _WORKSPACE_TOOLS
        if allow_write or tool["function"]["name"] != "write_file"
    ]
    context = [f"配置目录：{root}"]
    if active_table:
        context.append(f"当前打开的配置表：{active_table}")
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你在游戏配置目录里工作。用工具列出、读取"
                + ("和写入" if allow_write else "")
                + "这个目录中的文件，然后用自然语言回复。"
            ),
        },
        *(
            {"role": turn["role"], "content": turn["content"]}
            for turn in (history or [])
            if turn.get("role") in {"user", "assistant"} and isinstance(turn.get("content"), str)
        ),
        {"role": "user", "content": "\n".join([*context, "", prompt])},
    ]
    for _ in range(16):
        message = await asyncio.to_thread(
            _chat_completion, base_url, selected_model, api_key, messages, tools
        )
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("模型服务返回了空回复。")
            return content.strip()
        messages.append(message)
        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            result = _run_workspace_tool(root, name, arguments, allow_write)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": result,
                }
            )
    raise RuntimeError("模型连续调用工具次数过多，已停止。")


def parse_agent_proposal(response: str) -> dict[str, Any]:
    candidate = response.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        if candidate.startswith("json\n"):
            candidate = candidate[5:]
        if candidate.endswith("```"):
            candidate = candidate[:-3].strip()
    proposal = json.loads(candidate)
    if not isinstance(proposal, dict):
        raise ValueError("Agent 返回内容必须是 JSON 对象。")
    message = proposal.get("message")
    changes = proposal.get("changes")
    if not isinstance(message, str) or not isinstance(changes, list):
        raise ValueError("Agent 返回内容需要包含 message 和 changes 字段。")
    for change in changes:
        if (
            not isinstance(change, dict)
            or type(change.get("row")) is not int
            or not isinstance(change.get("column"), str)
            or "value" not in change
        ):
            raise ValueError("修改项需要包含整数 row、字符串 column 和 value。")
    additions = proposal.get("column_additions", [])
    deletions = proposal.get("column_deletions", [])
    if not isinstance(additions, list) or not isinstance(deletions, list):
        raise ValueError("column_additions 和 column_deletions 必须是数组。")
    for addition in additions:
        if (
            not isinstance(addition, dict)
            or not isinstance(addition.get("name"), str)
            or ("type" in addition and addition["type"] is not None and not isinstance(addition["type"], str))
            or (
                "target" in addition
                and addition["target"] is not None
                and not isinstance(addition["target"], str)
            )
            or (
                "annotation" in addition
                and addition["annotation"] is not None
                and not isinstance(addition["annotation"], str)
            )
        ):
            raise ValueError(
                "新增列需要包含字符串 name，以及可选的 type、target、annotation 和 default。"
            )
        if not isinstance(addition.get("type"), str) or not addition["type"].strip():
            addition["type"] = "string"
    for name in deletions:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("删除列必须是非空列名。")
    return {
        "message": message,
        "changes": changes,
        "column_additions": additions,
        "column_deletions": deletions,
    }


def _proposal_instructions(
    columns: list[str],
    data_types: list[str],
    source_name: str,
    visible_rows: list[tuple[int, dict[str, Any]]],
    prompt: str,
    targets: list[str] | None = None,
    annotations: list[str] | None = None,
) -> str:
    column_info = []
    for index, name in enumerate(columns):
        item: dict[str, Any] = {"name": name, "type": data_types[index]}
        if targets is not None and index < len(targets):
            item["target"] = targets[index]
        if annotations is not None and index < len(annotations):
            item["annotation"] = annotations[index]
        column_info.append(item)
    table = {
        "source": source_name,
        "columns": column_info,
        "visible_rows": [
            {"row": row_number, "values": row}
            for row_number, row in visible_rows
        ],
    }
    return (
        "你是游戏配置表助手。可以建议修改当前页已有单元格，以及新增或删除列；"
        "不要声称已修改文件。只返回一个 JSON 对象，形状为 "
        '{"message":"简要说明","changes":[{"row":1,"column":"name","value":"新值"}],'
        '"column_additions":[{"name":"desc","type":"string","target":"both",'
        '"annotation":"说明","default":""}],"column_deletions":["old_column"]}。'
        "changes 的行号是 TSV 数据区从 1 开始的行号（不包括四行表头），只能修改 "
        "visible_rows 中出现的已有行。column_deletions 只能填写现有列名，删除会移除该列全部数据。"
        "column_additions 的 name 不能与现有列或本次其他新增列重复，也不能与 column_deletions 重复。"
        "type 只能是 string、integer、number、boolean、json、lua_array、lua_object；"
        "target 只能是 both、backend、frontend，省略时视为 both；annotation 和 default 可省略，省略表示空。"
        "新增列的 default 会写入所有行；若当前页某行需要不同的值，再用 changes 修改该新列。"
        "value 和 default 必须符合列类型，且不能是 null。没有需要修改的内容时，changes、"
        "column_additions、column_deletions 都返回空数组。不要返回 Markdown 或 JSON 代码围栏。"
        f"\n\n当前配置表：\n{json.dumps(table, ensure_ascii=False, separators=(',', ':'))}"
        f"\n\n用户请求：\n{prompt}"
    )


def _openai_compatible_request(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2},
        ensure_ascii=False,
    ).encode("utf-8")
    if len(payload) > MAX_AGENT_INPUT_BYTES:
        raise RuntimeError("当前页上下文过大，请减少单元格内容后重试。")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_RejectRedirects)
        with opener.open(request, timeout=120) as response:
            response_body = response.read(MAX_AGENT_OUTPUT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        details = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"模型服务返回 HTTP {exc.code}：{details}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接模型服务：{exc}") from exc
    if len(response_body) > MAX_AGENT_OUTPUT_BYTES:
        raise RuntimeError("模型服务响应过大，已停止读取。")
    try:
        result = json.loads(response_body)
        content = result["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型服务响应格式无效，预期 OpenAI 兼容的 chat completion。") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("模型服务返回了空回复。")
    return content


async def request_api_proposal(
    base_url: str,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
    columns: list[str],
    data_types: list[str],
    source_name: str,
    visible_rows: list[tuple[int, dict[str, Any]]],
    prompt: str,
    targets: list[str] | None = None,
    annotations: list[str] | None = None,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个只提供修改预览的游戏配置表 Agent。绝不修改文件或执行工具。"
                "每次回复必须严格遵循用户消息指定的 JSON 格式。"
            ),
        },
        *history,
        {
            "role": "user",
            "content": _proposal_instructions(
                columns,
                data_types,
                source_name,
                visible_rows,
                prompt,
                targets,
                annotations,
            ),
        },
    ]
    return await asyncio.to_thread(
        _openai_compatible_request,
        base_url,
        model,
        api_key,
        messages,
    )


def _cursor_version_key(name: str) -> tuple[int, str]:
    match = _CURSOR_VERSION_DIR.match(name)
    if match is None:
        return (0, name)
    year, month, day = (int(part) for part in match.groups())
    return (year * 10000 + month * 100 + day, name)


def _cursor_mode_args(mode: str) -> list[str]:
    """Flags for one CLI run.

    Ask is read-only. Agent is the CLI default (there is no ``--mode=agent``).
    ``--print`` has no approval prompt, so Agent also passes ``--force``.
    """
    if mode == "ask":
        return ["--mode=ask", "--print", "--trust", "--output-format=text"]
    return ["--print", "--trust", "--force", "--output-format=text"]


def _remove_workdir(path: str) -> None:
    """Delete the CLI workspace. A just-exited process can keep the directory locked."""
    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 9:
                return
            time.sleep(0.15)


def parse_cursor_model_list(output: str) -> list[tuple[str, str]]:
    models: list[tuple[str, str]] = []
    for line in output.splitlines():
        model_id, separator, label = line.strip().partition(" - ")
        if not separator or not model_id or any(character.isspace() for character in model_id):
            continue
        models.append((model_id, label.strip() or model_id))
    return models


async def list_cursor_models() -> list[tuple[str, str]]:
    executable = shutil.which("agent") or shutil.which("cursor-agent")
    if executable is None:
        raise RuntimeError("未找到 Cursor Agent CLI，无法读取可用模型。")
    process = await asyncio.create_subprocess_exec(
        *_cursor_cli_argv(executable),
        "--list-models",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("读取 Cursor 模型列表超时。") from exc
    if process.returncode != 0:
        details = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "读取 Cursor 模型列表失败"
            + (f"：{details[:500]}" if details else "。")
        )
    models = parse_cursor_model_list(stdout.decode("utf-8", errors="replace"))
    if not models:
        raise RuntimeError("Cursor CLI 没有返回可用模型。")
    return models


def _cursor_model_args(model: str) -> list[str]:
    normalized = model.strip()
    if not normalized:
        return []
    if any(character.isspace() for character in normalized):
        raise ValueError("Cursor 模型 ID 不能包含空白。例如 grok-4.7-high。")
    return ["--model", normalized]


def _cursor_cli_argv(executable: str) -> list[str]:
    """Return the real CLI argv, skipping the Windows cmd wrapper.

    ``agent.cmd`` forwards arguments with ``%*``. cmd.exe ends that command at
    the first newline, so the table and the user request never reach the model.
    """
    path = Path(executable)
    if os.name != "nt" or path.suffix.lower() not in {".cmd", ".bat", ".ps1"}:
        return [executable]
    versions_dir = path.parent / "versions"
    if not versions_dir.is_dir():
        return [executable]
    candidates = [
        item
        for item in versions_dir.iterdir()
        if item.is_dir()
        and (item / "node.exe").is_file()
        and (item / "index.js").is_file()
    ]
    if not candidates:
        return [executable]
    latest = max(candidates, key=lambda item: _cursor_version_key(item.name))
    return [str(latest / "node.exe"), str(latest / "index.js")]


async def run_cursor_workspace(
    workspace: str,
    prompt: str,
    *,
    mode: str = "agent",
    model: str = "",
    history: list[dict[str, str]] | None = None,
    active_table: str | None = None,
) -> str:
    """Run Cursor in the real configuration directory.

    The CLI keeps its own tools. The prompt is the user's request plus the
    open table path, not a fixed JSON schema or a single page of cells.
    """
    if mode not in {"ask", "agent"}:
        raise ValueError("Cursor Agent 模式只能选择 ask 或 agent。")
    root = Path(workspace)
    if not root.is_dir():
        raise RuntimeError("配置目录不存在。请先在导出设置里选择配置文件目录。")
    executable = shutil.which("agent") or shutil.which("cursor-agent")
    if executable is None:
        raise RuntimeError(
            "未找到 Cursor Agent CLI。请安装 Cursor CLI 并完成登录。"
        )
    parts: list[str] = []
    if history:
        parts.append(
            "此前对话：\n"
            + "\n".join(
                f"{'用户' if turn['role'] == 'user' else 'Agent'}：{turn['content']}"
                for turn in history
            )
        )
    if active_table:
        parts.append(f"当前打开的配置表：{active_table}")
    parts.append(prompt)
    full_prompt = "\n\n".join(parts)
    env = os.environ.copy()
    env.setdefault("CURSOR_INVOKED_AS", Path(executable).name)
    process = await asyncio.create_subprocess_exec(
        *_cursor_cli_argv(executable),
        *_cursor_mode_args(mode),
        *_cursor_model_args(model),
        full_prompt,
        cwd=str(root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("Cursor Agent CLI 请求超时（10 分钟）。") from exc
    if process.returncode != 0:
        details = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Cursor Agent CLI 退出码 {process.returncode}"
            + (f"：{details[:2000]}" if details else "。")
        )
    if len(stdout) > MAX_AGENT_OUTPUT_BYTES:
        raise RuntimeError("Cursor Agent CLI 响应过大，已停止读取。")
    response = stdout.decode("utf-8", errors="replace").strip()
    if not response:
        raise RuntimeError("Cursor Agent CLI 返回了空回复。")
    return response


async def request_cursor_proposal(
    history: list[dict[str, str]],
    columns: list[str],
    data_types: list[str],
    source_name: str,
    visible_rows: list[tuple[int, dict[str, Any]]],
    prompt: str,
    mode: str = "ask",
    model: str = "",
    targets: list[str] | None = None,
    annotations: list[str] | None = None,
) -> str:
    if mode not in {"ask", "agent"}:
        raise ValueError("Cursor Agent 模式只能选择 ask 或 agent。")
    executable = shutil.which("agent") or shutil.which("cursor-agent")
    if executable is None:
        raise RuntimeError(
            "未找到 Cursor Agent CLI。请安装 Cursor CLI 并完成登录，"
            "或切换到 OpenAI 兼容 API。"
        )
    transcript = "\n".join(
        f"{'用户' if turn['role'] == 'user' else 'Agent'}：{turn['content']}"
        for turn in history
    )
    full_prompt = _proposal_instructions(
        columns,
        data_types,
        source_name,
        visible_rows,
        prompt,
        targets,
        annotations,
    )
    if transcript:
        full_prompt = f"此前对话：\n{transcript}\n\n{full_prompt}"
    if len(full_prompt) > MAX_CURSOR_PROMPT_CHARS:
        raise RuntimeError("当前页上下文或对话过长，请减少内容或重新打开 Agent。")

    env = os.environ.copy()
    env.setdefault("CURSOR_INVOKED_AS", Path(executable).name)
    working_directory = tempfile.mkdtemp(prefix="game-config-agent-")
    try:
        process = await asyncio.create_subprocess_exec(
            *_cursor_cli_argv(executable),
            *_cursor_mode_args(mode),
            *_cursor_model_args(model),
            full_prompt,
            cwd=working_directory,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("Cursor Agent CLI 请求超时（180 秒）。") from exc
    finally:
        await asyncio.to_thread(_remove_workdir, working_directory)
    if process.returncode != 0:
        details = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Cursor Agent CLI 退出码 {process.returncode}"
            + (f"：{details[:2000]}" if details else "。")
        )
    if len(stdout) > MAX_AGENT_OUTPUT_BYTES:
        raise RuntimeError("Cursor Agent CLI 响应过大，已停止读取。")
    response = stdout.decode("utf-8", errors="replace").strip()
    if not response:
        raise RuntimeError("Cursor Agent CLI 返回了空回复。")
    return response
