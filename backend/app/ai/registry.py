"""Provider selection, fallback and schema-validated invocation.

`AIRunner` is the only thing the pipeline calls. It owns retry, failover, schema validation
and the `ai_analysis_logs` audit row, so no stage has to reimplement any of that.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.ai.base import (
    AIProvider,
    CompletionResult,
    ImagePayload,
    ProviderError,
    ProviderTimeout,
    VisionProvider,
    extract_json,
)
from app.ai.providers.gemini import GeminiProvider, GeminiVisionProvider
from app.ai.providers.mock import MockProvider, MockVisionProvider
from app.ai.providers.openai_compatible import (
    DeepSeekProvider,
    OpenRouterProvider,
    OpenRouterVisionProvider,
)
from app.core.config import settings
from app.core.enums import AICallStatus, AIStage
from app.core.logging import get_logger
from app.models.ops import AIAnalysisLog

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_TEXT_PROVIDERS: dict[str, Callable[[], AIProvider]] = {
    "gemini": GeminiProvider,
    "openrouter": OpenRouterProvider,
    "deepseek": DeepSeekProvider,
    "mock": MockProvider,
}

_VISION_PROVIDERS: dict[str, Callable[[], VisionProvider]] = {
    "gemini": GeminiVisionProvider,
    "openrouter": OpenRouterVisionProvider,
    "mock": MockVisionProvider,
}

REPAIR_INSTRUCTION = (
    "\n\nYour previous response did not match the required schema. "
    "The validation errors were:\n{errors}\n"
    "Return ONLY a corrected JSON object. Do not include explanations or code fences."
)


class StageFailure(Exception):
    """Every provider in the chain failed for this stage.

    The pipeline catches this, records the stage as skipped, forces manual review and moves
    on. It never aborts the claim.
    """

    def __init__(self, stage: AIStage, message: str):
        super().__init__(message)
        self.stage = stage


def _chain(selected: str, available: dict[str, Callable]) -> list[str]:
    """Primary provider first, then the configured fallbacks, de-duplicated."""
    ordered = [selected, *settings.fallback_chain]
    seen: list[str] = []
    for name in ordered:
        if name in available and name not in seen:
            seen.append(name)
    return seen or ["mock"]


def text_providers() -> list[AIProvider]:
    return [_TEXT_PROVIDERS[name]() for name in _chain(settings.ai_provider, _TEXT_PROVIDERS)]


def vision_providers() -> list[VisionProvider]:
    return [_VISION_PROVIDERS[name]() for name in _chain(settings.vision_provider, _VISION_PROVIDERS)]


class AIRunner:
    def __init__(self, db: Session, claim_id: uuid.UUID | None = None):
        self.db = db
        self.claim_id = claim_id

    # ── Public API ──────────────────────────────────────────

    def run_text(
        self,
        *,
        stage: AIStage,
        system: str,
        prompt: str,
        schema: type[T],
        prompt_version: str,
        temperature: float = 0.1,
    ) -> T:
        return self._run(
            stage=stage,
            schema=schema,
            prompt_version=prompt_version,
            providers=text_providers(),
            call=lambda provider, extra: provider.complete(  # type: ignore[union-attr]
                system=system, prompt=prompt + extra, temperature=temperature
            ),
            model_of=lambda p: p.text_model,  # type: ignore[union-attr]
            image_count=0,
        )

    def run_vision(
        self,
        *,
        stage: AIStage,
        system: str,
        prompt: str,
        images: list[ImagePayload],
        schema: type[T],
        prompt_version: str,
        temperature: float = 0.1,
    ) -> T:
        return self._run(
            stage=stage,
            schema=schema,
            prompt_version=prompt_version,
            providers=vision_providers(),
            call=lambda provider, extra: provider.analyze(  # type: ignore[union-attr]
                system=system, prompt=prompt + extra, images=images, temperature=temperature
            ),
            model_of=lambda p: p.vision_model,  # type: ignore[union-attr]
            image_count=len(images),
        )

    # ── Core loop ───────────────────────────────────────────

    def _run(
        self,
        *,
        stage: AIStage,
        schema: type[T],
        prompt_version: str,
        providers: list,
        call: Callable[[object, str], CompletionResult],
        model_of: Callable[[object], str],
        image_count: int,
    ) -> T:
        last_error = "No provider was available."

        for index, provider in enumerate(providers):
            is_fallback = index > 0

            if not provider.is_configured():
                self._log(
                    stage, provider.name, model_of(provider), prompt_version,
                    AICallStatus.SKIPPED, attempt=1, is_fallback=is_fallback,
                    error="Provider is not configured.", image_count=image_count,
                )
                last_error = f"{provider.name} is not configured."
                continue

            repair_suffix = ""
            for attempt in range(1, settings.ai_max_retries + 2):
                try:
                    result = call(provider, repair_suffix)
                except ProviderTimeout as exc:
                    last_error = str(exc)
                    self._log(
                        stage, provider.name, model_of(provider), prompt_version,
                        AICallStatus.TIMEOUT, attempt=attempt, is_fallback=is_fallback,
                        error=last_error, image_count=image_count,
                    )
                    break  # a timeout will very likely repeat; move to the next provider
                except ProviderError as exc:
                    last_error = str(exc)
                    self._log(
                        stage, provider.name, model_of(provider), prompt_version,
                        AICallStatus.RATE_LIMITED if exc.rate_limited else AICallStatus.PROVIDER_ERROR,
                        attempt=attempt, is_fallback=is_fallback,
                        error=last_error, image_count=image_count,
                    )
                    if not exc.retryable or exc.rate_limited:
                        break
                    continue

                try:
                    payload = extract_json(result.text)
                    validated = schema.model_validate(payload)
                except (ValueError, ValidationError) as exc:
                    last_error = str(exc)[:500]
                    self._log(
                        stage, provider.name, result.model, prompt_version,
                        AICallStatus.SCHEMA_ERROR, attempt=attempt, is_fallback=is_fallback,
                        error=last_error, latency_ms=result.latency_ms,
                        excerpt=result.text[:800], image_count=image_count,
                        request_id=result.request_id,
                    )
                    if attempt <= settings.ai_max_retries:
                        # One targeted repair attempt: hand the validator's complaint back
                        # to the model rather than re-rolling the same prompt.
                        repair_suffix = REPAIR_INSTRUCTION.format(errors=last_error[:800])
                        continue
                    break

                self._log(
                    stage, provider.name, result.model, prompt_version, AICallStatus.SUCCESS,
                    attempt=attempt, is_fallback=is_fallback, latency_ms=result.latency_ms,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    excerpt=result.text[:800], image_count=image_count,
                    request_id=result.request_id,
                )
                log.info(
                    "ai.stage_ok",
                    stage=stage.value, provider=provider.name, attempt=attempt,
                    fallback=is_fallback,
                )
                return validated

        log.warning("ai.stage_failed", stage=stage.value, error=last_error)
        raise StageFailure(stage, last_error)

    def _log(
        self,
        stage: AIStage,
        provider: str,
        model: str,
        prompt_version: str,
        status: AICallStatus,
        *,
        attempt: int = 1,
        is_fallback: bool = False,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        excerpt: str | None = None,
        image_count: int = 0,
        request_id: str | None = None,
    ) -> None:
        self.db.add(
            AIAnalysisLog(
                claim_id=self.claim_id,
                stage=stage,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                request_id=request_id,
                status=status,
                attempt=attempt,
                is_fallback=is_fallback,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_count=image_count,
                error_message=error,
                response_excerpt=excerpt,
            )
        )
        self.db.flush()

    @staticmethod
    def active_provider_names() -> dict[str, str]:
        return {"text": settings.ai_provider, "vision": settings.vision_provider}
