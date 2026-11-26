"""Provider interface. To add a provider, subclass AIProvider and implement _complete()."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

from app.state.privacy import assert_safe

from .prompt import SYSTEM_PROMPT, build_user_message


class AIError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached: bool = False


class AIProvider(ABC):
    """Takes the structured game text and returns the model's analysis.

    The only input is a string, and it must pass the privacy check before any
    request is made. No image, file, URL or machine detail can be passed in."""

    name = "provider"
    _cache: Dict[str, AIResult] = {}

    def __init__(self, model: str, max_tokens: int = 700):
        self.model = model
        self.max_tokens = int(max_tokens)

    def analyze(self, game_text: str) -> AIResult:
        assert_safe(game_text)
        key = hashlib.sha256("\x00".join([self.name, self.model, str(self.max_tokens), SYSTEM_PROMPT, game_text])
                             .encode("utf-8")).hexdigest()
        hit = AIProvider._cache.get(key)
        if hit is not None:  # same spot asked again: no second charge
            return AIResult(hit.text, hit.provider, hit.model, hit.input_tokens, hit.output_tokens, cached=True)
        result = self._complete(SYSTEM_PROMPT, build_user_message(game_text))
        if not result.text.strip():
            raise AIError("The AI returned an empty answer.")
        AIProvider._cache[key] = result
        return result

    @abstractmethod
    def _complete(self, system: str, user: str) -> AIResult:
        ...

    @property
    def description(self) -> str:
        return f"{self.name} ({self.model})"
