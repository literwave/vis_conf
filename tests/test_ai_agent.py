import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from ai_agent import (
    _openai_compatible_request,
    parse_agent_proposal,
    request_cursor_proposal,
    validate_api_settings,
)


class AiAgentTests(unittest.TestCase):
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
            },
        )

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
        self.assertIn("--mode=agent", create_process.call_args.args)


if __name__ == "__main__":
    unittest.main()
