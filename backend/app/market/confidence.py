"""Price confidence scoring.

Confidence answers "how much should an agent trust this range?", and it is built from
observable properties of the evidence rather than from a model's self-report:

    source count · source reliability · vehicle compatibility · price agreement · freshness

Each factor is a 0–1 multiplier, so any single weak factor drags the result down. Four
sources that disagree wildly should not score higher than two that agree.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ConfidenceInput:
    prices: list[float]
    reliability_weights: list[float]
    compatibility_scores: list[float]
    retrieved_at: list[datetime]


@dataclass
class ConfidenceResult:
    score: float
    reason: str


def _source_count_factor(n: int) -> float:
    # Diminishing returns: the jump from one source to three matters far more than
    # the jump from six to ten.
    return {0: 0.0, 1: 0.45, 2: 0.65, 3: 0.80, 4: 0.88, 5: 0.93}.get(n, 0.97)


def _spread_factor(prices: list[float]) -> tuple[float, float]:
    """Agreement between sources, as 1 − (coefficient of variation), floored at 0.2."""
    if len(prices) < 2:
        return 0.6, 0.0

    median = statistics.median(prices)
    if median <= 0:
        return 0.3, 0.0

    deviation = statistics.pstdev(prices)
    cv = deviation / median
    return max(0.2, min(1.0, 1.0 - cv)), cv


def _freshness_factor(timestamps: list[datetime]) -> float:
    if not timestamps:
        return 0.5

    now = datetime.now(UTC)
    ages = [
        (now - (t if t.tzinfo else t.replace(tzinfo=UTC))).days
        for t in timestamps
    ]
    average_age = sum(ages) / len(ages)

    if average_age <= 1:
        return 1.0
    if average_age <= 7:
        return 0.95
    if average_age <= 30:
        return 0.85
    if average_age <= 90:
        return 0.65
    return 0.4


def score_price_confidence(data: ConfidenceInput) -> ConfidenceResult:
    n = len(data.prices)
    if n == 0:
        return ConfidenceResult(0.0, "No price sources were found.")

    count_factor = _source_count_factor(n)
    reliability = (
        sum(data.reliability_weights) / len(data.reliability_weights)
        if data.reliability_weights
        else 0.5
    )
    compatibility = (
        sum(data.compatibility_scores) / len(data.compatibility_scores)
        if data.compatibility_scores
        else 0.5
    )
    spread_factor, cv = _spread_factor(data.prices)
    freshness = _freshness_factor(data.retrieved_at)

    score = count_factor * (0.3 + 0.7 * reliability) * (0.3 + 0.7 * compatibility)
    score *= spread_factor * freshness
    score = round(min(1.0, max(0.0, score)), 3)

    fragments = [f"{n} matching source(s)"]
    if n >= 2:
        agreement = "closely" if cv < 0.15 else "broadly" if cv < 0.35 else "poorly"
        fragments.append(f"prices agree {agreement} (spread {cv:.0%})")
    if compatibility < 0.6:
        fragments.append("vehicle compatibility is uncertain")
    if freshness < 0.7:
        fragments.append("some data is more than a month old")
    if reliability < 0.5:
        fragments.append("sources have low reliability weighting")

    return ConfidenceResult(score, ". ".join(f.capitalize() for f in fragments) + ".")


def score_valuation_confidence(data: ConfidenceInput) -> ConfidenceResult:
    """Vehicle valuations tolerate more spread than parts: condition and mileage vary."""
    result = score_price_confidence(data)
    if len(data.prices) >= 2:
        _, cv = _spread_factor(data.prices)
        if cv < 0.4:
            return ConfidenceResult(
                min(1.0, round(result.score * 1.15, 3)),
                result.reason + " Spread is normal for used-vehicle listings.",
            )
    return result
