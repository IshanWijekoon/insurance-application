"""The costing engine.

All currency arithmetic in the system happens here, in `Decimal`, from inputs that each have
a recorded provenance. The engine will produce a *partial* estimate when a part cannot be
priced, and it says which parts are missing — it never substitutes a guess to make the total
look complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import settings
from app.core.enums import DamageSeverity, DamageType, RepairAction
from app.core.logging import get_logger
from app.core.parts import part_display_name
from app.estimation.rules import (
    ActionDecision,
    decide_action,
    labour_hours,
    paint_panels,
    repair_fraction,
)

log = get_logger(__name__)

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class PartInput:
    """One damaged part, with whatever pricing was actually obtained for it."""

    canonical_part: str
    damage_type: DamageType
    severity: DamageSeverity
    damaged_part_id: object | None = None
    model_action: RepairAction | None = None
    model_labour_hours: float | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    price_source_count: int = 0
    price_confidence: float | None = None
    detection_confidence: float | None = None

    @property
    def has_price(self) -> bool:
        return self.price_min is not None and self.price_max is not None


@dataclass
class EstimateLine:
    canonical_part: str
    display_name: str
    action: RepairAction
    part_price_available: bool
    part_price_min: Decimal | None
    part_price_max: Decimal | None
    labour_hours: float
    labour_rate: float
    labour_min: Decimal
    labour_max: Decimal
    paint_panels: float
    paint_min: Decimal
    paint_max: Decimal
    line_min: Decimal
    line_max: Decimal
    currency: str
    basis: str
    price_source_count: int
    confidence: float
    damaged_part_id: object | None = None


@dataclass
class EstimateResult:
    lines: list[EstimateLine] = field(default_factory=list)
    parts_min: Decimal = Decimal("0")
    parts_max: Decimal = Decimal("0")
    labour_min: Decimal = Decimal("0")
    labour_max: Decimal = Decimal("0")
    paint_min: Decimal = Decimal("0")
    paint_max: Decimal = Decimal("0")
    materials_min: Decimal = Decimal("0")
    materials_max: Decimal = Decimal("0")
    total_min: Decimal = Decimal("0")
    total_max: Decimal = Decimal("0")
    currency: str = "LKR"
    confidence: float = 0.0
    unpriced_parts: list[str] = field(default_factory=list)
    is_partial: bool = False
    notes: str = ""


class DamageEstimateService:
    def __init__(
        self,
        *,
        currency: str | None = None,
        labour_rate: float | None = None,
        paint_rate: float | None = None,
    ):
        self.currency = currency or settings.market_currency
        self.labour_rate = labour_rate if labour_rate is not None else settings.labour_rate_per_hour
        self.paint_rate = paint_rate if paint_rate is not None else settings.paint_rate_per_panel
        self.spread = Decimal(str(settings.estimate_range_spread))

    def estimate(self, parts: list[PartInput]) -> EstimateResult:
        result = EstimateResult(currency=self.currency)
        if not parts:
            result.notes = "No damaged parts were identified, so no estimate could be produced."
            return result

        confidences: list[float] = []

        for part in parts:
            line = self._line(part)
            result.lines.append(line)

            result.parts_min += line.part_price_min or Decimal("0")
            result.parts_max += line.part_price_max or Decimal("0")
            result.labour_min += line.labour_min
            result.labour_max += line.labour_max
            result.paint_min += line.paint_min
            result.paint_max += line.paint_max
            confidences.append(line.confidence)

            if not line.part_price_available and line.action is not RepairAction.INSPECT:
                result.unpriced_parts.append(part.canonical_part)

        materials_rate = Decimal(str(settings.materials_percent_of_parts))
        result.materials_min = _money(result.parts_min * materials_rate)
        result.materials_max = _money(result.parts_max * materials_rate)

        result.total_min = _money(
            result.parts_min + result.labour_min + result.paint_min + result.materials_min
        )
        result.total_max = _money(
            result.parts_max + result.labour_max + result.paint_max + result.materials_max
        )

        result.is_partial = bool(result.unpriced_parts)
        result.confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        result.notes = self._notes(result, parts)
        return result

    def _line(self, part: PartInput) -> EstimateLine:
        display = part_display_name(part.canonical_part)
        decision: ActionDecision = decide_action(
            part.canonical_part, part.damage_type, part.severity, part.model_action
        )
        hours, hours_note = labour_hours(
            part.canonical_part, part.severity, decision.action, part.model_labour_hours
        )
        panels = paint_panels(part.canonical_part, part.damage_type, decision.action)

        part_min, part_max, price_note = self._part_cost(part, decision.action)

        labour_cost = _money(Decimal(str(hours)) * Decimal(str(self.labour_rate)))
        labour_min = _money(labour_cost * (1 - self.spread))
        labour_max = _money(labour_cost * (1 + self.spread))

        paint_cost = _money(Decimal(str(panels)) * Decimal(str(self.paint_rate)))
        paint_min = _money(paint_cost * (1 - self.spread))
        paint_max = _money(paint_cost * (1 + self.spread))

        line_min = _money((part_min or Decimal("0")) + labour_min + paint_min)
        line_max = _money((part_max or Decimal("0")) + labour_max + paint_max)

        basis = " ".join(
            [
                decision.rationale,
                price_note,
                f"Labour: {hours:g} h at {self.labour_rate:,.0f} {self.currency}/h — {hours_note}",
                (
                    f"Paint: {panels:g} panel(s) at {self.paint_rate:,.0f} {self.currency}/panel."
                    if panels
                    else "No refinishing costed for this part."
                ),
            ]
        )

        return EstimateLine(
            canonical_part=part.canonical_part,
            display_name=display,
            action=decision.action,
            part_price_available=part.has_price,
            part_price_min=part_min,
            part_price_max=part_max,
            labour_hours=hours,
            labour_rate=self.labour_rate,
            labour_min=labour_min,
            labour_max=labour_max,
            paint_panels=panels,
            paint_min=paint_min,
            paint_max=paint_max,
            line_min=line_min,
            line_max=line_max,
            currency=self.currency,
            basis=basis,
            price_source_count=part.price_source_count,
            confidence=self._line_confidence(part, decision),
            damaged_part_id=part.damaged_part_id,
        )

    def _part_cost(
        self, part: PartInput, action: RepairAction
    ) -> tuple[Decimal | None, Decimal | None, str]:
        """Convert a researched part price into the cost of the chosen action.

        The full replacement price is used only when the part is actually being replaced.
        A repair is costed as a fraction of it, because charging a claim the price of a new
        bumper to fix a scratch is exactly the error this system exists to avoid.
        """
        if action is RepairAction.INSPECT:
            return None, None, (
                "No part cost included: the component must be inspected before a repair "
                "method can be determined."
            )

        if not part.has_price:
            return None, None, (
                "No part price available from the permitted market sources, so this line "
                "excludes the component cost and requires manual verification."
            )

        assert part.price_min is not None and part.price_max is not None

        if action is RepairAction.REPLACE:
            return (
                _money(part.price_min),
                _money(part.price_max),
                (
                    f"Replacement priced from {part.price_source_count} market source(s): "
                    f"{part.price_min:,.0f}–{part.price_max:,.0f} {self.currency}."
                ),
            )

        low_fraction, high_fraction = repair_fraction(part.severity)
        repair_min = _money(part.price_min * Decimal(str(low_fraction)))
        repair_max = _money(part.price_max * Decimal(str(high_fraction)))
        return (
            repair_min,
            repair_max,
            (
                f"Repair costed at {low_fraction:.0%}–{high_fraction:.0%} of the "
                f"{part.price_min:,.0f}–{part.price_max:,.0f} {self.currency} replacement price "
                f"({part.price_source_count} source(s)), reflecting {part.severity.value} severity."
            ),
        )

    def _line_confidence(self, part: PartInput, decision: ActionDecision) -> float:
        """Blend detection confidence, price confidence and rule certainty."""
        detection = part.detection_confidence if part.detection_confidence is not None else 0.5
        price = part.price_confidence if part.price_confidence is not None else 0.0

        if not part.has_price:
            price = 0.0

        certainty = 0.5 if decision.action is RepairAction.INSPECT else 0.9
        if decision.overrode_model:
            certainty -= 0.1

        score = 0.45 * detection + 0.35 * price + 0.20 * certainty
        return round(min(1.0, max(0.0, score)), 3)

    def _notes(self, result: EstimateResult, parts: list[PartInput]) -> str:
        fragments = [
            f"Costed {len(result.lines)} damaged part(s) at a labour rate of "
            f"{self.labour_rate:,.0f} {self.currency}/hour and "
            f"{self.paint_rate:,.0f} {self.currency}/panel for refinishing.",
            f"Materials and consumables added at "
            f"{settings.materials_percent_of_parts:.0%} of the parts subtotal.",
        ]

        if result.unpriced_parts:
            names = ", ".join(part_display_name(c) for c in result.unpriced_parts)
            fragments.append(
                f"No market price could be obtained for: {names}. Those components are "
                "excluded from the totals, so the figure below is incomplete and understates "
                "the likely cost."
            )

        inspect = [line.display_name for line in result.lines if line.action is RepairAction.INSPECT]
        if inspect:
            fragments.append(
                f"Awaiting physical inspection before costing: {', '.join(inspect)}."
            )

        return " ".join(fragments)


def damage_to_value_ratio(
    estimate_max: Decimal | None, vehicle_value_min: Decimal | None
) -> Decimal | None:
    """Damage cost as a fraction of vehicle value.

    Computed against the *lower* bound of the valuation, which is the conservative reading:
    it produces the higher ratio and is therefore more likely to escalate to human review.
    Never used to declare a total loss on its own.
    """
    if not estimate_max or not vehicle_value_min or vehicle_value_min <= 0:
        return None
    return (Decimal(estimate_max) / Decimal(vehicle_value_min)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
