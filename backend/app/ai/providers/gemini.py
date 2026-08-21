"""Google Gemini provider (REST, via httpx — no vendor SDK pinned into the image)."""

from __future__ import annotations

import base64
import time
import uuid
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

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class _GeminiBase:
    name = "gemini"

    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key)

    def _post(self, model: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        if not self.is_configured():
            raise ProviderError("GEMINI_API_KEY is not configured.", retryable=False)

        url = f"{API_ROOT}/{model}:generateContent"
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
                response = client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Gemini timed out after {settings.ai_request_timeout_seconds}s.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 429:
            raise ProviderError("Gemini rate limit reached.", rate_limited=True)
        if response.status_code in {400, 401, 403}:
            raise ProviderError(
                f"Gemini rejected the request ({response.status_code}): {response.text[:300]}",
                retryable=False,
            )
        if response.status_code >= 500:
            raise ProviderError(f"Gemini server error ({response.status_code}).")
        if response.status_code != 200:
            raise ProviderError(f"Unexpected Gemini status {response.status_code}.")

        return response.json(), latency_ms

    @staticmethod
    def _read(payload: dict[str, Any]) -> tuple[str, int | None, int | None]:
        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback", {})
            reason = feedback.get("blockReason", "no candidates returned")
            raise ProviderError(f"Gemini produced no output ({reason}).", retryable=False)

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)

        usage = payload.get("usageMetadata", {})
        return text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")

    @staticmethod
    def _generation_config(temperature: float, max_tokens: int) -> dict[str, Any]:
        return {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            # Native JSON mode: the model is constrained to emit a JSON object, which
            # removes most of the fence-stripping and repair-retry traffic.
            "responseMimeType": "application/json",
        }


class GeminiProvider(_GeminiBase, AIProvider):
    @property
    def text_model(self) -> str:
        return settings.gemini_text_model

    def complete(
        self, *, system: str, prompt: str, temperature: float = 0.1, max_tokens: int = 4096
    ) -> CompletionResult:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": self._generation_config(temperature, max_tokens),
        }
        payload, latency = self._post(self.text_model, body)
        text, input_tokens, output_tokens = self._read(payload)
        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.text_model,
            request_id=uuid.uuid4().hex,
            latency_ms=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class GeminiVisionProvider(_GeminiBase, VisionProvider):
    @property
    def vision_model(self) -> str:
        return settings.gemini_vision_model

    def analyze(
        self,
        *,
        system: str,
        prompt: str,
        images: list[ImagePayload],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            if image.reference:
                parts.append({"text": f"[{image.reference}]"})
            parts.append(
                {
                    "inlineData": {
                        "mimeType": image.mime_type,
                        "data": base64.b64encode(image.data).decode(),
                    }
                }
            )

        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": self._generation_config(temperature, max_tokens),
        }
        payload, latency = self._post(self.vision_model, body)
        text, input_tokens, output_tokens = self._read(payload)
        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.vision_model,
            request_id=uuid.uuid4().hex,
            latency_ms=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
