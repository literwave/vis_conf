import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from ai_agent import (
    _cursor_cli_argv,
    _openai_compatible_request,
    parse_agent_proposal,
    parse_cursor_model_list,
    request_cursor_proposal,
    run_api_workspace,
    run_cursor_workspace,
    validate_api_settings,
)


class AiAgentTests(unittest.TestCase):
    def test_parse_cursor_model_list_keeps_ids_and_labels(self):
        models = parse_cursor_model_list(
            "Available models\n\n"
            "auto - Auto (current, default)\n"
            "grok-4.7-high - Grok 4.7  High\n"
            "\n"
            "Tip: use --model <id> to switch.\n"
        )

        self.assertEqual(
            models,
            [
                ("auto", "Auto (current, default)"),
                ("grok-4.7-high", "Grok 4.7  High"),
            ],
        )

    def test_parse_agent_proposal_accepts_json_fenced_response(self):
        proposal = parse_agent_proposal(
            '```json\n{"message":"Updated","changes":'
            '[{"row":1,"column":"name","value":"Potion"}]}\n```'
        )

        self.assertEqual(
            proposal,
            {
                "message": "Updated",
                "changes": [{"row": 1, "column": "name", "value": "Potion"}],
                "column_additions": [],
                "column_deletions": [],
            },
        )

    def test_parse_agent_proposal_accepts_column_additions_and_deletions(self):
        proposal = parse_agent_proposal(
            '{"message":"调整列","changes":[],'
            '"column_additions":[{"name":"desc","type":"string","target":"both",'
            '"annotation":"说明","default":""}],'
            '"column_deletions":["rarity"]}'
        )

        self.assertEqual(proposal["column_deletions"], ["rarity"])
        self.assertEqual(proposal["column_additions"][0]["name"], "desc")

    def test_parse_agent_proposal_rejects_invalid_change_shape(self):
        with self.assertRaisesRegex(ValueError, "修改项需要包含"):
            parse_agent_proposal(
                '{"message":"Updated","changes":[{"row":"1","column":"name"}]}'
            )

    def test_api_settings_require_https_and_model(self):
        self.assertEqual(
            validate_api_settings("https://example.com/v1/", " model "),
            ("https://example.com/v1", "model"),
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_api_settings("http://example.com/v1", "model")
        with self.assertRaisesRegex(ValueError, "模型名称"):
            validate_api_settings("https://example.com/v1", "")

    def test_openai_compatible_request_sends_key_and_parses_response(self):
        response_body = json.dumps(
            {"choices": [{"message": {"content": '{"message":"ok","changes":[]}'}}]}
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self, _):
                return response_body

        opener = Mock()
        opener.open.return_value = Response()
        with patch("ai_agent.urllib.request.build_opener", return_value=opener):
            result = _openai_compatible_request(
                "https://example.com/v1",
                "test-model",
                "secret",
                [{"role": "user", "content": "hello"}],
            )

        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(result, '{"message":"ok","changes":[]}')

    def test_cursor_agent_mode_is_passed_to_cli(self):
        process = SimpleNamespace(
            communicate=AsyncMock(
                return_value=(
                    b'{"message":"ok","changes":[]}',
                    b"",
                )
            ),
            returncode=0,
        )
        with (
            patch("ai_agent.shutil.which", return_value="agent"),
            patch(
                "ai_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as create_process,
        ):
            response = asyncio.run(
                request_cursor_proposal(
                    [],
                    ["id"],
                    ["integer"],
                    "items.tsv",
                    [(1, {"id": 1})],
                    "check this row",
                    mode="agent",
                )
            )
            self.assertEqual(response, '{"message":"ok","changes":[]}')
            self.assertNotIn("--mode=agent", create_process.call_args.args)
            self.assertIn("--force", create_process.call_args.args)
            self.assertNotIn("--model", create_process.call_args.args)
            self.assertIn("--trust", create_process.call_args.args)
            prompt = create_process.call_args.args[-1]
            self.assertIn("check this row", prompt)
            self.assertIn("\n", prompt)

            asyncio.run(
                request_cursor_proposal(
                    [],
                    ["id"],
                    ["integer"],
                    "items.tsv",
                    [(1, {"id": 1})],
                    "explain this row",
                    mode="ask",
                )
            )
            self.assertIn("--mode=ask", create_process.call_args.args)
            self.assertNotIn("--force", create_process.call_args.args)

            asyncio.run(
                request_cursor_proposal(
                    [],
                    ["id"],
                    ["integer"],
                    "items.tsv",
                    [(1, {"id": 1})],
                    "check this row",
                    mode="ask",
                    model="grok-4.7-high",
                )
            )
            args = create_process.call_args.args
            self.assertEqual(args[args.index("--model") + 1], "grok-4.7-high")

    def test_cursor_workspace_uses_the_configuration_directory(self):
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"done", b"")),
            returncode=0,
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("ai_agent.shutil.which", return_value="agent"),
            patch(
                "ai_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as create_process,
        ):
            response = asyncio.run(
                run_cursor_workspace(
                    directory,
                    "把名称改短",
                    mode="agent",
                    active_table=str(Path(directory) / "Hero.tsv"),
                )
            )

        self.assertEqual(response, "done")
        self.assertEqual(create_process.call_args.kwargs["cwd"], directory)
        prompt = create_process.call_args.args[-1]
        self.assertIn("把名称改短", prompt)
        self.assertIn("Hero.tsv", prompt)
        self.assertNotIn("只返回一个 JSON", prompt)
        self.assertIn("--force", create_process.call_args.args)
        self.assertNotIn("--mode=ask", create_process.call_args.args)

    def test_deepseek_writes_only_inside_the_configuration_directory(self):
        def fake_completion(base_url, model, api_key, messages, tools):
            self.assertEqual(base_url, "https://api.deepseek.com")
            self.assertEqual(model, "deepseek-chat")
            self.assertEqual(api_key, "secret")
            self.assertIn("write_file", [tool["function"]["name"] for tool in tools])
            if not any(item.get("role") == "tool" for item in messages):
                return {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "outside",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "../secret.txt", "content": "nope"}
                                ),
                            },
                        },
                        {
                            "id": "inside",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "Hero.tsv", "content": "id\tname\n"}
                                ),
                            },
                        },
                    ],
                }
            joined = "\n".join(item["content"] for item in messages if item.get("role") == "tool")
            self.assertIn("路径超出配置目录", joined)
            self.assertIn("已写入 Hero.tsv", joined)
            return {"content": "改好了"}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("ai_agent._chat_completion", side_effect=fake_completion),
        ):
            reply = asyncio.run(
                run_api_workspace(
                    "deepseek",
                    directory,
                    "改表",
                    api_key="secret",
                    mode="agent",
                )
            )
            root = Path(directory)
            self.assertEqual(reply, "改好了")
            self.assertEqual((root / "Hero.tsv").read_text(encoding="utf-8"), "id\tname\n")
            self.assertFalse((root.parent / "secret.txt").exists())

    def test_locked_workdir_does_not_fail_the_request(self):
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory, True)
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b'{"message":"ok","changes":[]}', b"")),
            returncode=0,
        )
        with (
            patch("ai_agent.shutil.which", return_value="agent"),
            patch(
                "ai_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch("ai_agent.tempfile.mkdtemp", return_value=directory),
            patch("ai_agent.shutil.rmtree", side_effect=OSError(32, "in use")),
            patch("ai_agent.time.sleep"),
        ):
            response = asyncio.run(
                request_cursor_proposal(
                    [],
                    ["id"],
                    ["integer"],
                    "items.tsv",
                    [(1, {"id": 1})],
                    "check this row",
                )
            )
        self.assertEqual(response, '{"message":"ok","changes":[]}')

    def test_windows_cmd_wrapper_launches_node_directly(self):
        root = self._cli_install("agent.CMD")
        with patch("ai_agent.os.name", "nt"):
            argv = _cursor_cli_argv(str(root / "agent.CMD"))
        self.assertEqual(
            argv,
            [
                str(root / "versions" / "2026.10.09-aaaa" / "node.exe"),
                str(root / "versions" / "2026.10.09-aaaa" / "index.js"),
            ],
        )

    def _cli_install(self, wrapper_name: str) -> Path:
        root = Path(self._tmpdir())
        (root / wrapper_name).write_text("@echo off\r\n", encoding="utf-8")
        older = root / "versions" / "2026.9.1-bbbb"
        newer = root / "versions" / "2026.10.09-aaaa"
        for version in (older, newer):
            version.mkdir(parents=True)
            (version / "node.exe").write_bytes(b"")
            (version / "index.js").write_text("", encoding="utf-8")
        return root

    def _tmpdir(self) -> str:
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        return directory


if __name__ == "__main__":
    unittest.main()
