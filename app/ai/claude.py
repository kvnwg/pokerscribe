"""Anthropic Claude via the Messages API."""
from __future__ import annotations

from .base import AIError, AIProvider, AIResult
from .http import post_json

CLAUDE_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"


class ClaudeProvider(AIProvider):
    name = "Claude"

    def __init__(self, api_key: str, model: str = "claude-haiku-5-5", max_tokens: int = 700,
                 api_url: str = API_URL, timeout: float = 60.0):
        super().__init__(model, max_tokens)
        if not api_key:
            raise AIError("No Claude API key. Add one in Settings.")
        self._key = api_key
        self.api_url = api_url
        self.timeout = timeout

    def _complete(self, system: str, user: str) -> AIResult:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION}
        data = post_json(self.api_url, payload, headers, self.timeout)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return AIResult(text.strip(), self.name, data.get("model", self.model),
                        usage.get("input_tokens"), usage.get("output_tokens"))
