"""Parts-price and vehicle-valuation research.

Both services follow the same shape:

    discover candidates → filter to whitelisted hosts → fetch politely → parse →
    normalise → verify compatibility → aggregate → score confidence → persist with sources

and both end in one of exactly two states: `AVAILABLE` with at least one stored source row,
or `UNAVAILABLE` with a reason. There is no third path where a number appears without a
source behind it.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.registry import AIRunner, StageFailure
from app.ai.schemas import PartNormalization
from app.core.config import settings
from app.core.enums import AIStage, DataStatus, MarketSourceCategory, PartGrade
from app.core.logging import get_logger
from app.core.parts import normalize_part_name, part_display_name
from app.market.confidence import ConfidenceInput, score_price_confidence, score_valuation_confidence
from app.market.fetcher import MarketFetcher
from app.market.parsers import ParsedListing, parse_listing
from app.market.search import SearchHit, get_search_provider
from app.models.assessment import DamagedPart
from app.models.market import (
    MarketSource,
    PartPriceSource,
    PartPriceSummary,
    VehicleValuation,
    VehicleValuationSource,
)

log = get_logger(__name__)

_GRADE_MARKERS: dict[PartGrade, tuple[str, ...]] = {
    PartGrade.OEM: ("oem", "genuine", "original equipment", "factory original"),
    PartGrade.REFURBISHED: ("refurbished", "reconditioned", "remanufactured"),
    PartGrade.USED: ("used", "second hand", "secondhand", "salvage", "pre-owned"),
    PartGrade.AFTERMARKET: ("aftermarket", "replacement part", "compatible", "generic"),
}


def _detect_grade(text: str) -> PartGrade:
    lowered = text.lower()
    # Ordered by specificity: "genuine OEM refurbished" should read as refurbished, so the
    # more qualifying markers are checked before the general ones.
    for grade in (PartGrade.REFURBISHED, PartGrade.USED, PartGrade.OEM, PartGrade.AFTERMARKET):
        if any(marker in lowered for marker in _GRADE_MARKERS[grade]):
            return grade
    return PartGrade.UNKNOWN


def _compatibility_score(text: str, make: str | None, model: str | None, year: int | None) -> float:
    """How strongly a listing claims to fit the target vehicle."""
    lowered = text.lower()
    score = 0.0

    if make and make.lower() in lowered:
        score += 0.4
    if model and model.lower() in lowered:
        score += 0.4
    if year:
        if str(year) in lowered:
            score += 0.2
        elif any(str(y) in lowered for y in range(year - 2, year + 3)):
            score += 0.1

    return round(min(1.0, score), 3)


@dataclass
class SourceCandidate:
    hit: SearchHit
    source: MarketSource


class _ResearchBase:
    def __init__(self, db: Session, claim_id: uuid.UUID | None = None):
        self.db = db
        self.claim_id = claim_id
        self.fetcher = MarketFetcher()
        self.search = get_search_provider()
        self.runner = AIRunner(db, claim_id)

    def _whitelist(self, category: MarketSourceCategory) -> list[MarketSource]:
        sources = self.db.scalars(
            select(MarketSource).where(
                MarketSource.is_enabled.is_(True),
                MarketSource.category.in_([category, MarketSourceCategory.BOTH]),
            )
        ).all()
        return list(sources)

    def _match_hits(
        self, hits: list[SearchHit], sources: list[MarketSource]
    ) -> list[SourceCandidate]:
        """Keep only results whose host is on the whitelist."""
        by_host: dict[str, MarketSource] = {}
        for source in sources:
            from urllib.parse import urlparse

            host = urlparse(source.base_url).netloc.lower().removeprefix("www.")
            if host:
                by_host[host] = source

        matched: list[SourceCandidate] = []
        for hit in hits:
            host = hit.host
            source = by_host.get(host)
            if source is None:
                # Allow subdomains of a whitelisted host, but nothing else.
                source = next(
                    (s for h, s in by_host.items() if host.endswith("." + h)), None
                )
            if source is not None:
                matched.append(SourceCandidate(hit, source))
        return matched


class PartsPricingResearchService(_ResearchBase):
    """Researches the market price of one damaged part."""

    def research_part(
        self,
        part: DamagedPart,
        *,
        make: str | None,
        model: str | None,
        year: int | None,
    ) -> PartPriceSummary:
        summary = part.price_summary or PartPriceSummary(damaged_part_id=part.id)
        if part.price_summary is None:
            self.db.add(summary)

        summary.currency = settings.market_currency

        if not settings.market_research_enabled:
            return self._unavailable(summary, "Market research is disabled by configuration.")

        vehicle_label = " ".join(str(p) for p in (make, model, year) if p)
        if not vehicle_label:
            return self._unavailable(
                summary,
                "The vehicle could not be identified, so no compatible part could be searched for.",
            )

        sources = self._whitelist(MarketSourceCategory.PART_PRICE)
        if not sources:
            return self._unavailable(
                summary,
                "No approved parts-price sources are configured. An administrator must add "
                "sources to the whitelist before prices can be researched.",
            )

        query = (
            f"{vehicle_label} {part_display_name(part.canonical_part)} price "
            f"{settings.market_country}"
        )
        hits = self.search.search(query, limit=settings.scraper_max_pages_per_query * 2)
        if not hits:
            return self._unavailable(
                summary,
                "No search results were returned for this part. Discovery may be "
                "unconfigured (SEARCH_PROVIDER) or the part may not be listed locally.",
            )

        candidates = self._match_hits(hits, sources)
        if not candidates:
            return self._unavailable(
                summary,
                f"Results were found, but none came from an approved source. "
                f"{len(hits)} result(s) were discarded.",
            )

        collected = 0
        for candidate in candidates[: settings.scraper_max_pages_per_query]:
            row = self._price_row(candidate, part, make, model, year, vehicle_label)
            if row is not None:
                self.db.add(row)
                collected += 1

        self.db.flush()
        if collected == 0:
            return self._unavailable(
                summary,
                "Approved sources were reachable, but none published a price that could be "
                "confirmed as compatible with this vehicle.",
            )

        return self._aggregate(summary, part)

    def _price_row(
        self,
        candidate: SourceCandidate,
        part: DamagedPart,
        make: str | None,
        model: str | None,
        year: int | None,
        vehicle_label: str,
    ) -> PartPriceSource | None:
        result = self.fetcher.fetch(
            candidate.hit.url, rate_limit_per_minute=candidate.source.rate_limit_per_minute
        )
        if not result.ok:
            log.info(
                "parts.fetch_skipped",
                url=candidate.hit.url, reason=result.blocked_reason or result.status_code,
            )
            return None

        listing: ParsedListing | None = parse_listing(
            result.text, expected_currency=candidate.source.currency
        )
        if listing is None or not listing.has_price:
            return None

        title = listing.title or candidate.hit.title
        context = f"{title} {listing.excerpt or ''} {candidate.hit.snippet}"

        canonical = normalize_part_name(title)
        compatibility_note: str | None = None
        compatibility = _compatibility_score(context, make, model, year)

        if canonical is None:
            # Deterministic matching failed; ask the model, which may also decline.
            canonical, compatibility, compatibility_note = self._normalize_with_ai(
                title, context, vehicle_label, part.canonical_part, compatibility
            )

        if canonical != part.canonical_part:
            log.info(
                "parts.listing_rejected",
                url=candidate.hit.url, expected=part.canonical_part, resolved=canonical,
            )
            return None

        if compatibility < 0.4:
            # A price for the right kind of part on the wrong car is worse than no price.
            return None

        currency = (listing.currency or candidate.source.currency or settings.market_currency).upper()

        return PartPriceSource(
            claim_id=self.claim_id,
            damaged_part_id=part.id,
            market_source_id=candidate.source.id,
            source_name=candidate.source.name,
            url=candidate.hit.url[:1000],
            product_name=title[:400],
            canonical_part=part.canonical_part,
            vehicle_compatibility=(compatibility_note or vehicle_label)[:200],
            compatibility_confidence=Decimal(str(compatibility)),
            part_grade=_detect_grade(context),
            price=Decimal(str(round(listing.price or 0, 2))),
            currency=currency[:3],
            availability=listing.availability,
            retrieved_at=result.retrieved_at or datetime.now(UTC),
            raw_excerpt=(listing.excerpt or candidate.hit.snippet)[:1000],
        )

    def _normalize_with_ai(
        self,
        title: str,
        context: str,
        vehicle_label: str,
        expected_part: str,
        fallback_compatibility: float,
    ) -> tuple[str | None, float, str | None]:
        from app.ai.prompts.templates import (
            PART_NORMALIZATION_PROMPT,
            PART_NORMALIZATION_SYSTEM,
            PROMPT_VERSION,
            render,
        )

        try:
            normalized: PartNormalization = self.runner.run_text(
                stage=AIStage.PART_NORMALIZATION,
                system=PART_NORMALIZATION_SYSTEM,
                prompt=render(
                    PART_NORMALIZATION_PROMPT,
                    product_name=title,
                    listing_text=context[:1500],
                    vehicle_label=vehicle_label,
                    expected_part=part_display_name(expected_part),
                ),
                schema=PartNormalization,
                prompt_version=PROMPT_VERSION,
            )
        except StageFailure:
            return None, fallback_compatibility, None

        if not normalized.is_relevant:
            return None, 0.0, None

        return (
            normalized.canonical_part,
            max(fallback_compatibility, normalized.compatibility_confidence),
            normalized.vehicle_compatibility,
        )

    def _aggregate(self, summary: PartPriceSummary, part: DamagedPart) -> PartPriceSummary:
        self.db.refresh(part)
        rows = [r for r in part.price_sources if not r.excluded_from_summary]
        if not rows:
            return self._unavailable(summary, "No usable price rows remained after filtering.")

        # Grades are not interchangeable. A used bumper and an OEM bumper are different
        # products, so the summary reports whichever grade is best represented rather than
        # averaging across them.
        by_grade: dict[PartGrade, list[PartPriceSource]] = {}
        for row in rows:
            by_grade.setdefault(row.part_grade, []).append(row)

        dominant = max(by_grade, key=lambda g: (len(by_grade[g]), g is not PartGrade.UNKNOWN))
        selected = by_grade[dominant]

        for row in rows:
            if row not in selected:
                row.excluded_from_summary = True
                row.exclusion_reason = (
                    f"Different part grade ({row.part_grade.value}); the summary reports "
                    f"{dominant.value} prices."
                )

        prices = [float(r.price) for r in selected]
        confidence = score_price_confidence(
            ConfidenceInput(
                prices=prices,
                reliability_weights=[
                    (r.market_source_id and self._reliability(r.market_source_id)) or 0.5
                    for r in selected
                ],
                compatibility_scores=[
                    float(r.compatibility_confidence or 0.5) for r in selected
                ],
                retrieved_at=[r.retrieved_at for r in selected],
            )
        )

        summary.status = DataStatus.AVAILABLE
        summary.unavailable_reason = None
        summary.price_min = Decimal(str(round(min(prices), 2)))
        summary.price_max = Decimal(str(round(max(prices), 2)))
        summary.price_median = Decimal(str(round(statistics.median(prices), 2)))
        summary.currency = selected[0].currency
        summary.source_count = len(selected)
        summary.dominant_grade = dominant
        summary.price_confidence = Decimal(str(confidence.score))
        summary.confidence_reason = confidence.reason
        self.db.flush()

        log.info(
            "parts.priced",
            part=part.canonical_part, sources=len(selected), confidence=confidence.score,
        )
        return summary

    def _reliability(self, source_id: uuid.UUID) -> float:
        source = self.db.get(MarketSource, source_id)
        return source.reliability_weight if source else 0.5

    def _unavailable(self, summary: PartPriceSummary, reason: str) -> PartPriceSummary:
        summary.status = DataStatus.UNAVAILABLE
        summary.unavailable_reason = reason
        summary.price_min = None
        summary.price_max = None
        summary.price_median = None
        summary.source_count = 0
        summary.price_confidence = Decimal("0")
        summary.confidence_reason = reason
        self.db.flush()
        log.info("parts.unavailable", reason=reason)
        return summary


class VehicleValuationService(_ResearchBase):
    """Researches the current market value of the insured vehicle."""

    def research(
        self, *, make: str | None, model: str | None, year: int | None
    ) -> VehicleValuation:
        valuation = VehicleValuation(
            claim_id=self.claim_id,
            make=make,
            model=model,
            year=year,
            country=settings.market_country,
            currency=settings.market_currency,
        )
        self.db.add(valuation)
        self.db.flush()

        if not settings.market_research_enabled:
            return self._unavailable(valuation, "Market research is disabled by configuration.")

        if not make or not model:
            return self._unavailable(
                valuation,
                "The vehicle make and model could not be established, so its market value "
                "could not be researched.",
            )

        sources = self._whitelist(MarketSourceCategory.VEHICLE_VALUE)
        if not sources:
            return self._unavailable(
                valuation,
                "No approved vehicle-valuation sources are configured. An administrator must "
                "add sources to the whitelist.",
            )

        label = " ".join(str(p) for p in (make, model, year) if p)
        hits = self.search.search(
            f"{label} for sale price {settings.market_country}",
            limit=settings.scraper_max_pages_per_query * 2,
        )
        if not hits:
            return self._unavailable(
                valuation, "No search results were returned for this vehicle."
            )

        candidates = self._match_hits(hits, sources)
        if not candidates:
            return self._unavailable(
                valuation, "No results came from an approved vehicle-valuation source."
            )

        collected: list[VehicleValuationSource] = []
        for candidate in candidates[: settings.scraper_max_pages_per_query]:
            row = self._valuation_row(candidate, valuation, make, model, year)
            if row is not None:
                self.db.add(row)
                collected.append(row)

        self.db.flush()
        if not collected:
            return self._unavailable(
                valuation,
                "Approved sources were reachable, but none published a comparable listing "
                "with a usable price.",
            )

        prices = [float(r.price) for r in collected]
        confidence = score_valuation_confidence(
            ConfidenceInput(
                prices=prices,
                reliability_weights=[
                    (r.market_source_id and self._reliability(r.market_source_id)) or 0.5
                    for r in collected
                ],
                compatibility_scores=[1.0 for _ in collected],
                retrieved_at=[r.retrieved_at for r in collected],
            )
        )

        valuation.status = DataStatus.AVAILABLE
        valuation.estimated_min = Decimal(str(round(min(prices), 2)))
        valuation.estimated_max = Decimal(str(round(max(prices), 2)))
        valuation.median_value = Decimal(str(round(statistics.median(prices), 2)))
        valuation.source_count = len(collected)
        valuation.confidence = Decimal(str(confidence.score))
        valuation.confidence_reason = confidence.reason
        self.db.flush()

        log.info("valuation.available", vehicle=label, sources=len(collected))
        return valuation

    def _valuation_row(
        self,
        candidate: SourceCandidate,
        valuation: VehicleValuation,
        make: str | None,
        model: str | None,
        year: int | None,
    ) -> VehicleValuationSource | None:
        result = self.fetcher.fetch(
            candidate.hit.url, rate_limit_per_minute=candidate.source.rate_limit_per_minute
        )
        if not result.ok:
            return None

        listing = parse_listing(result.text, expected_currency=candidate.source.currency)
        if listing is None or not listing.has_price:
            return None

        title = listing.title or candidate.hit.title
        context = f"{title} {listing.excerpt or ''}"

        if _compatibility_score(context, make, model, year) < 0.6:
            return None

        # A listing five or more years off the target is a different vehicle for valuation
        # purposes, however similar the name.
        if year and listing.year and abs(listing.year - year) > 4:
            return None

        return VehicleValuationSource(
            valuation_id=valuation.id,
            market_source_id=candidate.source.id,
            source_name=candidate.source.name,
            url=candidate.hit.url[:1000],
            listing_title=title[:400],
            price=Decimal(str(round(listing.price or 0, 2))),
            currency=(listing.currency or candidate.source.currency)[:3].upper(),
            listing_year=listing.year,
            mileage_km=listing.mileage_km,
            retrieved_at=result.retrieved_at or datetime.now(UTC),
            raw_excerpt=(listing.excerpt or "")[:1000],
        )

    def _reliability(self, source_id: uuid.UUID) -> float:
        source = self.db.get(MarketSource, source_id)
        return source.reliability_weight if source else 0.5

    def _unavailable(self, valuation: VehicleValuation, reason: str) -> VehicleValuation:
        valuation.status = DataStatus.UNAVAILABLE
        valuation.unavailable_reason = reason
        valuation.estimated_min = None
        valuation.estimated_max = None
        valuation.median_value = None
        valuation.source_count = 0
        valuation.confidence = Decimal("0")
        valuation.confidence_reason = reason
        self.db.flush()
        log.info("valuation.unavailable", reason=reason)
        return valuation
