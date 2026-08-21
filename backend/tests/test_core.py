"""Unit tests that do not require PostgreSQL, Redis or network."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.enums import DamageSeverity, DamageType, RepairAction
from app.core.parts import normalize_part_name, part_display_name
from app.core.security import hash_password, verify_password
from app.estimation.engine import DamageEstimateService, PartInput, damage_to_value_ratio
from app.estimation.rules import decide_action
from app.market.confidence import ConfidenceInput, score_price_confidence
from app.schemas.auth import LoginRequest
from app.schemas.common import MoneyRange


def test_demo_local_email_is_accepted():
    payload = LoginRequest(email="agent@insure.local", password="ChangeMe123!")
    assert payload.email == "agent@insure.local"


def test_password_round_trip():
    hashed = hash_password("ChangeMe123!")
    assert hashed.startswith("$argon2")
    assert verify_password("ChangeMe123!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_part_name_normalization():
    assert normalize_part_name("Front bumper cover") == "FRONT_BUMPER"
    assert normalize_part_name("LH headlight") == "HEADLIGHT_LEFT"
    assert normalize_part_name("completely unrelated listing") is None
    assert part_display_name("FRONT_BUMPER") == "Front bumper"


def test_broken_headlight_is_replaced_not_repaired():
    decision = decide_action("HEADLIGHT_LEFT", DamageType.BROKEN, DamageSeverity.MEDIUM, RepairAction.REPAIR)
    assert decision.action is RepairAction.REPLACE
    assert decision.overrode_model is True


def test_minor_scratch_is_repaired():
    decision = decide_action("FRONT_BUMPER", DamageType.SCRATCH, DamageSeverity.LOW)
    assert decision.action is RepairAction.REPAIR


def test_repair_uses_fraction_of_replacement_price():
    service = DamageEstimateService(labour_rate=2500, paint_rate=12000)
    result = service.estimate(
        [
            PartInput(
                canonical_part="FRONT_BUMPER",
                damage_type=DamageType.SCRATCH,
                severity=DamageSeverity.LOW,
                price_min=Decimal("75000"),
                price_max=Decimal("90000"),
                price_source_count=3,
                price_confidence=0.84,
                detection_confidence=0.9,
            )
        ]
    )
    line = result.lines[0]
    assert line.action is RepairAction.REPAIR
    assert line.part_price_available is True
    assert line.part_price_max < Decimal("90000")
    assert "Preliminary" not in line.basis
    assert result.is_partial is False


def test_missing_price_marks_estimate_partial():
    service = DamageEstimateService()
    result = service.estimate(
        [
            PartInput(
                canonical_part="HEADLIGHT_LEFT",
                damage_type=DamageType.BROKEN,
                severity=DamageSeverity.MEDIUM,
            )
        ]
    )
    assert result.is_partial is True
    assert "HEADLIGHT_LEFT" in result.unpriced_parts
    assert result.lines[0].part_price_available is False


def test_money_range_never_fabricates_zero():
    missing = MoneyRange.unavailable("No source returned a listing.")
    assert missing.status == "UNAVAILABLE"
    assert missing.min is None
    assert missing.manual_verification_required is True

    present = MoneyRange.available(Decimal("110000"), Decimal("145000"), "LKR", confidence=0.82)
    assert present.status == "AVAILABLE"
    assert present.currency == "LKR"


def test_price_confidence_rewards_agreement():
    now = datetime.now(UTC)
    tight = score_price_confidence(
        ConfidenceInput(
            prices=[75000, 82000, 90000],
            reliability_weights=[0.8, 0.7, 0.75],
            compatibility_scores=[0.9, 0.85, 0.8],
            retrieved_at=[now, now, now],
        )
    )
    wide = score_price_confidence(
        ConfidenceInput(
            prices=[20000, 90000, 250000],
            reliability_weights=[0.8, 0.7, 0.75],
            compatibility_scores=[0.9, 0.85, 0.8],
            retrieved_at=[now, now, now],
        )
    )
    assert tight.score > wide.score
    assert tight.score > 0.5


def test_damage_to_value_ratio_is_a_signal_only():
    ratio = damage_to_value_ratio(Decimal("400000"), Decimal("8000000"))
    assert ratio == Decimal("0.0500")
    assert damage_to_value_ratio(Decimal("100"), None) is None
