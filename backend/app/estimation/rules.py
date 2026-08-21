"""Repair-versus-replace rules and severity multipliers.

Deterministic and independently testable. The model contributes judgement (its suggested
action and labour hours); these rules are the guardrail that catches an implausible
suggestion — for example replacing a bumper because of a light scratch, or repairing a
headlight that is described as broken.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import DamageSeverity, DamageType, RepairAction
from app.core.parts import PARTS_BY_CODE

# Damage that cannot be repaired on any part: the component is replaced or inspected.
_ALWAYS_REPLACE = {DamageType.BROKEN, DamageType.MISSING}

# Glass and lighting are replacement items; there is no economical repair path.
_NON_REPAIRABLE_MATERIALS = {"GLASS"}

# Fraction of a new part's price that a repair typically costs, by severity. Applied to the
# researched part price only when the recommended action is REPAIR.
REPAIR_COST_FRACTION: dict[DamageSeverity, tuple[float, float]] = {
    DamageSeverity.LOW: (0.10, 0.22),
    DamageSeverity.MEDIUM: (0.25, 0.45),
    DamageSeverity.HIGH: (0.45, 0.70),
    DamageSeverity.CRITICAL: (0.70, 1.00),
}

# Labour multipliers relative to a part's baseline hours.
LABOUR_MULTIPLIER: dict[DamageSeverity, float] = {
    DamageSeverity.LOW: 0.6,
    DamageSeverity.MEDIUM: 1.0,
    DamageSeverity.HIGH: 1.4,
    DamageSeverity.CRITICAL: 2.0,
}


@dataclass
class ActionDecision:
    action: RepairAction
    rationale: str
    overrode_model: bool = False


def decide_action(
    canonical_part: str,
    damage_type: DamageType,
    severity: DamageSeverity,
    model_suggestion: RepairAction | None = None,
) -> ActionDecision:
    """Choose repair, replace or inspect, and explain why in one sentence."""
    part = PARTS_BY_CODE.get(canonical_part)
    display = part.display_name if part else canonical_part.replace("_", " ").lower()

    if damage_type is DamageType.POSSIBLE_STRUCTURAL or (part and part.structural and severity.rank >= 3):
        return ActionDecision(
            RepairAction.INSPECT,
            f"Possible structural involvement of the {display}; a photograph cannot "
            "establish the extent, so physical inspection is required before costing.",
            overrode_model=model_suggestion not in (None, RepairAction.INSPECT),
        )

    if damage_type is DamageType.UNKNOWN:
        return ActionDecision(
            RepairAction.INSPECT,
            f"The damage to the {display} could not be classified from the photographs.",
            overrode_model=model_suggestion not in (None, RepairAction.INSPECT),
        )

    if damage_type in _ALWAYS_REPLACE:
        return ActionDecision(
            RepairAction.REPLACE,
            f"The {display} is {damage_type.value.lower()} and cannot be repaired.",
            overrode_model=model_suggestion is RepairAction.REPAIR,
        )

    if part and part.material in _NON_REPAIRABLE_MATERIALS:
        return ActionDecision(
            RepairAction.REPLACE,
            f"The {display} is a glass or lens component, which is replaced rather than repaired.",
            overrode_model=model_suggestion is RepairAction.REPAIR,
        )

    if severity is DamageSeverity.CRITICAL:
        return ActionDecision(
            RepairAction.REPLACE,
            f"Damage to the {display} is severe enough that replacement is the expected outcome.",
            overrode_model=model_suggestion is RepairAction.REPAIR,
        )

    repairable = part.repairable_damage if part else frozenset()
    if damage_type in repairable and severity.rank <= 2:
        return ActionDecision(
            RepairAction.REPAIR,
            f"A {severity.value.lower()}-severity {damage_type.value.lower().replace('_', ' ')} "
            f"on the {display} is normally repaired and refinished.",
            overrode_model=model_suggestion is RepairAction.REPLACE,
        )

    if damage_type in repairable and severity is DamageSeverity.HIGH:
        # The genuinely ambiguous band. Defer to the model's read of the photograph, since
        # it saw the extent and these rules only see a label.
        if model_suggestion in {RepairAction.REPAIR, RepairAction.REPLACE}:
            return ActionDecision(
                model_suggestion,
                f"High-severity {damage_type.value.lower().replace('_', ' ')} on the {display} "
                f"could go either way; the visual assessment favoured "
                f"{model_suggestion.value.lower()}.",
            )
        return ActionDecision(
            RepairAction.INSPECT,
            f"High-severity {damage_type.value.lower().replace('_', ' ')} on the {display} "
            "sits on the repair/replace boundary and needs an in-person judgement.",
        )

    return ActionDecision(
        RepairAction.REPLACE,
        f"{damage_type.value.lower().replace('_', ' ').capitalize()} on the {display} is "
        "outside the range normally repaired for this component.",
        overrode_model=model_suggestion is RepairAction.REPAIR,
    )


def labour_hours(
    canonical_part: str,
    severity: DamageSeverity,
    action: RepairAction,
    model_estimate: float | None = None,
) -> tuple[float, str]:
    """Return labour hours and a note on where the figure came from."""
    part = PARTS_BY_CODE.get(canonical_part)
    baseline = part.base_labour_hours if part else 2.0

    rule_hours = baseline * LABOUR_MULTIPLIER[severity]
    if action is RepairAction.REPAIR:
        rule_hours *= 1.15  # repairing usually takes longer than bolting on a new part
    elif action is RepairAction.INSPECT:
        return 0.0, "No labour costed: the part requires inspection before a method is chosen."

    if model_estimate is None:
        return round(rule_hours, 2), f"Standard time for this part at {severity.value} severity."

    # Accept the model's figure only within a sane band around the rule-based value; a
    # hallucinated 40-hour bumper repair should not reach an estimate.
    low, high = rule_hours * 0.5, rule_hours * 2.0
    if low <= model_estimate <= high:
        return round(model_estimate, 2), "Visual assessment, within the expected range for this part."

    return (
        round(rule_hours, 2),
        f"Standard time used; the visual estimate of {model_estimate:g} h fell outside the "
        f"plausible range of {low:.1f}–{high:.1f} h for this part.",
    )


def paint_panels(canonical_part: str, damage_type: DamageType, action: RepairAction) -> float:
    part = PARTS_BY_CODE.get(canonical_part)
    if part is None or part.paint_panels == 0:
        return 0.0
    if action is RepairAction.INSPECT:
        return 0.0
    if damage_type in {DamageType.GLASS_DAMAGE}:
        return 0.0
    return part.paint_panels


def repair_fraction(severity: DamageSeverity) -> tuple[float, float]:
    return REPAIR_COST_FRACTION[severity]
