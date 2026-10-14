import asyncio
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


CREDENTIAL_SERVICE = "GameConfigAssistant"
CREDENTIAL_USERNAME = "openai-compatible-api-key"
MAX_AGENT_OUTPUT_BYTES = 2_000_000
MAX_AGENT_INPUT_BYTES = 1_000_000
MAX_CURSOR_PROMPT_CHARS = 24_000


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
    try:
        import keyring

        if api_key:
            keyring.set_password(CREDENTIAL_SERVICE, CREDENTIAL_USERNAME, api_key)
        else:
            keyring.delete_password(CREDENTIAL_SERVICE, CREDENTIAL_USERNAME)
    except Exception as exc:
        raise RuntimeError(f"无法安全保存 API Key：{exc}") from exc


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
    return {"message": message, "changes": changes}


def _proposal_instructions(
    columns: list[str],
    data_types: list[str],
    source_name: str,
    visible_rows: list[tuple[int, dict[str, Any]]],
    prompt: str,
) -> str:
    table = {
        "source": source_name,
        "columns": [
            {"name": name, "type": data_types[index]}
            for index, name in enumerate(columns)
        ],
        "visible_rows": [
            {"row": row_number, "values": row}
            for row_number, row in visible_rows
        ],
    }
    return (
        "你是游戏配置表助手。只能根据用户提供的当前 TSV 信息提出单元格修改建议；"
        "不要声称已修改文件。只返回一个 JSON 对象，形状为 "
        '{"message":"简要说明","changes":[{"row":1,"column":"name","value":"新值"}]}。'
        "行号是 TSV 数据区从 1 开始的行号（不包括四行表头），只能修改 visible_rows 中"
        "出现的已有行；column 必须是现有列名。value 必须是非 null 的 JSON 值，并符合列类型。"
        "没有需要修改的内容时返回空 changes。不要返回 Markdown 或 JSON 代码围栏。"
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
                columns, data_types, source_name, visible_rows, prompt
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


async def request_cursor_proposal(
    history: list[dict[str, str]],
    columns: list[str],
    data_types: list[str],
    source_name: str,
    visible_rows: list[tuple[int, dict[str, Any]]],
    prompt: str,
    mode: str = "ask",
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
        columns, data_types, source_name, visible_rows, prompt
    )
    if transcript:
        full_prompt = f"此前对话：\n{transcript}\n\n{full_prompt}"
    if len(full_prompt) > MAX_CURSOR_PROMPT_CHARS:
        raise RuntimeError("当前页上下文或对话过长，请减少内容或重新打开 Agent。")

    with tempfile.TemporaryDirectory(prefix="game-config-agent-") as working_directory:
        process = await asyncio.create_subprocess_exec(
            executable,
            f"--mode={mode}",
            "--print",
            "--output-format=text",
            full_prompt,
            cwd=working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("Cursor Agent CLI 请求超时（180 秒）。") from exc
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
