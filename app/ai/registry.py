"""Builds the configured provider from Settings. Add new providers here."""
from __future__ import annotations

from typing import Optional

from app.config import Settings
from app.config.secrets import get_api_key

from .base import AIError, AIProvider
from .claude import ClaudeProvider
from .openai_compat import OpenAICompatibleProvider

PROVIDERS = {
    "none": "None (text only, nothing is sent)",
    "claude": "Claude (Anthropic API)",
    "openai_compat": "OpenAI-compatible (OpenAI, OpenRouter, Ollama, LM Studio)",
}


def create_provider(settings: Settings) -> Optional[AIProvider]:
    if settings.ai_provider == "claude":
        key, _ = get_api_key("claude")
        if not key:
            raise AIError("No Claude API key yet. Open Settings and paste your key.")
        return ClaudeProvider(key, settings.claude_model, settings.max_tokens)
    if settings.ai_provider == "openai_compat":
        key, _ = get_api_key("openai_compat")
        return OpenAICompatibleProvider(settings.openai_base_url, settings.openai_model, key, settings.max_tokens)
    return None
