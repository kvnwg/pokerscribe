"""AI providers against a local mock server: what exactly goes over the wire."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.ai.base import AIError, AIProvider
from app.ai.claude import ClaudeProvider
from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.prompt import SYSTEM_PROMPT, build_user_message
from app.ai.registry import create_provider
from app.config import Settings
from app.state.privacy import PrivacyError
from app.state.text_format import render_text
from app.tests.test_state_text import spec_example_state

ALLOWED_HEADERS = {"host", "content-type", "accept", "user-agent", "content-length", "accept-encoding", "connection",
                   "x-api-key", "anthropic-version", "authorization"}


class _Server:
    def __init__(self):
        self.requests = []
        self.mode = "ok"
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                       "body": json.loads(body)})
                if outer.mode == "401":
                    self._send(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
                elif outer.mode == "rename" and "max_tokens" in outer.requests[-1]["body"]:
                    self._send(400, {"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."}})
                elif self.path.endswith("/messages"):
                    self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
                                     "content": [{"type": "text", "text": "Missing information: none. Call."}],
                                     "stop_reason": "end_turn", "usage": {"input_tokens": 412, "output_tokens": 9}})
                else:
                    self._send(200, {"model": "local-model", "choices": [{"message": {"role": "assistant", "content": "Call."}}],
                                     "usage": {"prompt_tokens": 400, "completion_tokens": 2}})

            def _send(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture()
def server():
    AIProvider._cache.clear()
    s = _Server()
    yield s
    s.close()


@pytest.fixture()
def game_text():
    return render_text(spec_example_state())


def test_claude_sends_only_the_text(server, game_text):
    p = ClaudeProvider("test-key", "claude-haiku-5-5", 600, api_url=f"http://127.0.0.1:{server.port}/v1/messages")
    result = p.analyze(game_text)
    assert result.text.startswith("Missing information") and result.input_tokens == 412 and not result.cached
    req = server.requests[-1]
    assert set(req["body"]) == {"model", "max_tokens", "system", "messages"}
    assert req["body"]["system"] == SYSTEM_PROMPT
    assert req["body"]["messages"] == [{"role": "user", "content": build_user_message(game_text)}]
    assert set(req["headers"]) <= ALLOWED_HEADERS, set(req["headers"]) - ALLOWED_HEADERS
    assert req["headers"]["user-agent"] == "text-client/1.0"
    assert req["headers"]["x-api-key"] == "test-key"
    dumped = json.dumps(req).lower()
    for leak in ("darwin", "macos", "python", "image", "base64", "screen", "maverick", "riverrat"):
        assert leak not in dumped, leak


def test_same_spot_is_answered_from_cache(server, game_text):
    p = ClaudeProvider("k", api_url=f"http://127.0.0.1:{server.port}/v1/messages")
    p.analyze(game_text)
    again = p.analyze(game_text)
    assert again.cached and len(server.requests) == 1


def test_privacy_check_runs_before_any_request(server, game_text):
    p = ClaudeProvider("k", api_url=f"http://127.0.0.1:{server.port}/v1/messages")
    with pytest.raises(PrivacyError):
        p.analyze(game_text + "\nTABLE: PokerStars Zoom")
    assert server.requests == []


def test_errors_are_readable(server, game_text):
    server.mode = "401"
    p = ClaudeProvider("bad", api_url=f"http://127.0.0.1:{server.port}/v1/messages")
    with pytest.raises(AIError, match="check the API key"):
        p.analyze(game_text)
    with pytest.raises(AIError, match="localhost"):
        ClaudeProvider("k", api_url="http://example.com/v1/messages").analyze(game_text)
    with pytest.raises(AIError, match="Could not reach"):
        ClaudeProvider("k", api_url="http://127.0.0.1:9/v1/messages", timeout=2).analyze(game_text)


def test_openai_compatible_provider(server, game_text):
    p = OpenAICompatibleProvider(f"http://127.0.0.1:{server.port}/v1", "local-model", api_key=None, max_tokens=300)
    result = p.analyze(game_text)
    assert result.text == "Call." and result.output_tokens == 2
    req = server.requests[-1]
    assert req["path"] == "/v1/chat/completions"
    assert "authorization" not in req["headers"]  # local servers need no key
    assert req["body"]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert req["body"]["messages"][1]["content"] == build_user_message(game_text)
    assert set(req["headers"]) <= ALLOWED_HEADERS


def test_openai_parameter_rename_retry(server, game_text):
    server.mode = "rename"
    p = OpenAICompatibleProvider(f"http://127.0.0.1:{server.port}/v1", "gpt-x", api_key="sk-test")
    assert p.analyze(game_text).text == "Call."
    assert "max_completion_tokens" in server.requests[-1]["body"]
    assert server.requests[-1]["headers"]["authorization"] == "Bearer sk-test"


def test_registry(monkeypatch):
    s = Settings()
    assert create_provider(s) is None  # "none": text only
    s.ai_provider = "claude"
    monkeypatch.setattr("app.ai.registry.get_api_key", lambda name: (None, ""))
    with pytest.raises(AIError, match="API key"):
        create_provider(s)
    monkeypatch.setattr("app.ai.registry.get_api_key", lambda name: ("sk-ant-test", "environment variable"))
    p = create_provider(s)
    assert isinstance(p, ClaudeProvider) and p.model == "claude-haiku-5-5"
    s.ai_provider = "openai_compat"
    s.openai_model = "llama3.1"
    s.openai_base_url = "http://localhost:11434/v1"
    assert isinstance(create_provider(s), OpenAICompatibleProvider)


def test_keys_come_from_environment_first(monkeypatch):
    from app.config import secrets

    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets.get_api_key("claude") == ("from-env", "environment variable ANTHROPIC_API_KEY")
