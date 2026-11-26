"""Any OpenAI-compatible chat-completions API: OpenAI, OpenRouter, or a local model
server such as Ollama or LM Studio (http://localhost:11434/v1), which costs nothing
and keeps even the text on this computer."""
from __future__ import annotations

from typing import Optional

from .base import AIError, AIProvider, AIResult
from .http import post_json


class OpenAICompatibleProvider(AIProvider):
    name = "OpenAI-compatible"

    def __init__(self, base_url: str, model: str, api_key: Optional[str] = None, max_tokens: int = 700,
                 timeout: float = 120.0):
        super().__init__(model, max_tokens)
        if not model:
            raise AIError("Set a model name for the OpenAI-compatible provider in Settings.")
        self.base_url = base_url.rstrip("/")
        self._key = api_key or ""
        self.timeout = timeout

    def _complete(self, system: str, user: str) -> AIResult:
        url = self.base_url + "/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": self.max_tokens,
        }
        try:
            data = post_json(url, payload, headers, self.timeout)
        except AIError as exc:
            if "max_completion_tokens" not in str(exc):
                raise
            # newer OpenAI models renamed the parameter
            payload.pop("max_tokens")
            payload["max_completion_tokens"] = self.max_tokens
            data = post_json(url, payload, headers, self.timeout)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise AIError("Unexpected response from the AI provider.") from None
        usage = data.get("usage") or {}
        return AIResult(text.strip(), self.name, data.get("model", self.model),
                        usage.get("prompt_tokens"), usage.get("completion_tokens"))
