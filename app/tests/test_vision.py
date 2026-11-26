"""Optional card reading by Claude: only crops of unclear cards are sent."""
import json

import numpy as np
import pytest

from app.ai.base import AIError
from app.ai.vision import ClaudeCardReader, crop_cards, normalize, parse
from app.tests.test_ai_providers import ALLOWED_HEADERS, _Server


class _CardServer(_Server):
    def __init__(self, answer: str):
        super().__init__()
        self.answer = answer
        handler = self.httpd.RequestHandlerClass
        outer = self

        def do_POST(h):
            body = h.rfile.read(int(h.headers.get("Content-Length", 0)))
            outer.requests.append({"path": h.path, "headers": {k.lower(): v for k, v in h.headers.items()},
                                   "body": json.loads(body)})
            h._send(200, {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": outer.answer}],
                          "usage": {"input_tokens": 300, "output_tokens": 20}})

        handler.do_POST = do_POST


@pytest.fixture()
def server():
    s = _CardServer('{"hero": ["Qd", "10h"], "board": ["2h", null, "Tc"]}')
    yield s
    s.close()


def test_card_codes_are_cleaned_up():
    assert normalize("10h") == "Th" and normalize("qD") == "Qd" and normalize("A s") == "As"
    assert normalize("1h") is None and normalize(None) is None and normalize("Kx") is None
    assert parse('Sure: {"hero": ["As", "Kd"]}') == (["As", "Kd"], [])
    with pytest.raises(AIError):
        parse("I can't tell")


def test_crop_holds_only_the_cards():
    img = np.zeros((600, 800, 3), np.uint8)
    crop = crop_cards(img, [(300, 400, 60, 90), (350, 395, 60, 90)])
    assert crop.shape[0] < 110 and crop.shape[1] < 130  # the two cards and a sliver around them
    assert crop_cards(img, []) is None


def test_only_card_pictures_and_fixed_words_are_sent(server):
    reader = ClaudeCardReader("test-key", api_url=f"http://127.0.0.1:{server.port}/v1/messages")
    hero = np.full((80, 120, 3), 255, np.uint8)
    board = np.full((90, 300, 3), 255, np.uint8)
    got = reader.read(hero, board)
    assert got.hero == ["Qd", "Th"] and got.board == ["2h", None, "Tc"]
    req = server.requests[-1]
    assert set(req["headers"]) <= ALLOWED_HEADERS and req["headers"]["x-api-key"] == "test-key"
    body = req["body"]
    assert set(body) == {"model", "max_tokens", "system", "messages"} and body["model"] == "claude-haiku-5-5"
    content = body["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"]
    assert all(c["source"]["media_type"] == "image/png" for c in content[:2])
    dumped = json.dumps(body["system"]) + content[2]["text"]
    for leak in ("darwin", "macos", "python", "247", "poker site", "http"):
        assert leak not in dumped.lower(), leak


def test_needs_a_key():
    with pytest.raises(AIError):
        ClaudeCardReader("")
