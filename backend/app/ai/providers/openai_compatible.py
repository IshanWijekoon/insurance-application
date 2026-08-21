"""OpenRouter and DeepSeek.

Both speak the OpenAI chat-completions dialect, so one client covers them; only the base
URL, key and model differ. DeepSeek's chat models are text-only, so it registers as a
reasoning provider and not a vision one.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from app.ai.base import (
    AIProvider,
    CompletionResult,
    ImagePayload,
    ProviderError,
    ProviderTimeout,
    VisionProvider,
)
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class _ChatCompletionsClient:
    def __init__(self, *, name: str, base_url: str, api_key: str, extra_headers: dict[str, str] | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.extra_headers = extra_headers or {}

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _chat(self, body: dict[str, Any]) -> CompletionResult:
        if not self.is_configured():
            raise ProviderError(f"{self.name.upper()}_API_KEY is not configured.", retryable=False)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                f"{self.name} timed out after {settings.ai_request_timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 429:
            raise ProviderError(f"{self.name} rate limit reached.", rate_limited=True)
        if response.status_code in {400, 401, 403}:
            raise ProviderError(
                f"{self.name} rejected the request ({response.status_code}): {response.text[:300]}",
                retryable=False,
            )
        if response.status_code >= 500:
            raise ProviderError(f"{self.name} server error ({response.status_code}).")
        if response.status_code != 200:
            raise ProviderError(f"Unexpected {self.name} status {response.status_code}.")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name} returned no choices.", retryable=False)

        usage = payload.get("usage", {})
        return CompletionResult(
            text=choices[0].get("message", {}).get("content", "") or "",
            provider=self.name,
            model=payload.get("model", body.get("model", "unknown")),
            request_id=payload.get("id"),
            latency_ms=latency_ms,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class OpenRouterProvider(_ChatCompletionsClient, AIProvider):
    name = "openrouter"

    def __init__(self) -> None:
        super().__init__(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            extra_headers={
                "HTTP-Referer": "https://localhost",
                "X-Title": settings.app_name,
            },
        )

    @property
    def text_model(self) -> str:
        return settings.openrouter_text_model

    def complete(
        self, *, system: str, prompt: str, temperature: float = 0.1, max_tokens: int = 4096
    ) -> CompletionResult:
        return self._chat(
            {
                "model": self.text_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
        )


class OpenRouterVisionProvider(_ChatCompletionsClient, VisionProvider):
    name = "openrouter"

    def __init__(self) -> None:
        super().__init__(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            extra_headers={
                "HTTP-Referer": "https://localhost",
                "X-Title": settings.app_name,
            },
        )

    @property
    def vision_model(self) -> str:
        return settings.openrouter_vision_model

    def analyze(
        self,
        *,
        system: str,
        prompt: str,
        images: list[ImagePayload],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            if image.reference:
                content.append({"type": "text", "text": f"[{image.reference}]"})
            encoded = base64.b64encode(image.data).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.mime_type};base64,{encoded}"},
                }
            )

        return self._chat(
            {
                "model": self.vision_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )


class DeepSeekProvider(_ChatCompletionsClient, AIProvider):
    """Text and reasoning only — DeepSeek's chat models do not accept images."""

    name = "deepseek"

    def __init__(self) -> None:
        super().__init__(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key=settings.deepseek_api_key,
        )

    @property
    def text_model(self) -> str:
        return settings.deepseek_text_model

    def complete(
        self, *, system: str, prompt: str, temperature: float = 0.1, max_tokens: int = 4096
    ) -> CompletionResult:
        return self._chat(
            {
                "model": self.text_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
        )
