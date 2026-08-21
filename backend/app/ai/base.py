"""Provider interfaces and the JSON-extraction helper shared by all of them."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    """Provider call failed in a way that should trigger retry or failover."""

    def __init__(self, message: str, *, retryable: bool = True, rate_limited: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.rate_limited = rate_limited


class ProviderTimeout(ProviderError):
    pass


@dataclass
class ImagePayload:
    """An image on its way to a provider. Carries no claim or customer identifiers."""

    data: bytes
    mime_type: str = "image/jpeg"
    reference: str = ""  # opaque label such as "image_1", used in prompts


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    request_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    """Text/reasoning provider."""

    name: str = "base"

    @property
    @abstractmethod
    def text_model(self) -> str: ...

    @abstractmethod
    def complete(
        self, *, system: str, prompt: str, temperature: float = 0.1, max_tokens: int = 4096
    ) -> CompletionResult: ...

    @abstractmethod
    def is_configured(self) -> bool: ...


class VisionProvider(ABC):
    """Multimodal provider."""

    name: str = "base"

    @property
    @abstractmethod
    def vision_model(self) -> str: ...

    @abstractmethod
    def analyze(
        self,
        *,
        system: str,
        prompt: str,
        images: list[ImagePayload],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> CompletionResult: ...

    @abstractmethod
    def is_configured(self) -> bool: ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or code fences no matter how firmly the prompt forbids it,
    so this tolerates the packaging — but not malformed JSON. A parse failure raises, which
    is what triggers the repair-retry rather than a silent partial record.
    """
    if not text or not text.strip():
        raise ValueError("The provider returned an empty response.")

    candidate = text.strip()

    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object was found in the provider response.") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"The provider response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("The provider returned JSON that is not an object.")
    return parsed
