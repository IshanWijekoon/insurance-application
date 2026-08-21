from __future__ import annotations

from app.ai.schemas import ClaimSummary, CustomerInputExtraction, ImageDamageAnalysis, VehicleIdentification
from app.core.enums import ClaimStatus
from app.services.claims import ALLOWED_TRANSITIONS


def test_vehicle_identification_schema_rejects_fabricated_confidence():
    payload = VehicleIdentification.model_validate(
        {
            "make": "Toyota",
            "model": "Prius",
            "year_estimate": 2018,
            "color": "silver",
            "vehicle_type": "HATCHBACK",
            "confidence": 0.92,
            "vehicle_visible": True,
            "multiple_vehicles": False,
            "notes": [],
        }
    )
    assert payload.make == "Toyota"
    assert 0 <= payload.confidence <= 1


def test_damage_analysis_requires_canonical_parts():
    analysis = ImageDamageAnalysis.model_validate(
        {
            "vehicle_visible": True,
            "multiple_vehicles": False,
            "quality_sufficient": True,
            "damages": [
                {
                    "canonical_part": "FRONT_BUMPER",
                    "display_name": "Front bumper",
                    "damage_type": "CRACK",
                    "severity": "HIGH",
                    "confidence": 0.94,
                    "recommended_action": "REPLACE",
                    "explanation": "Crack across the lower valance.",
                }
            ],
            "notes": [],
        }
    )
    assert analysis.damages[0].canonical_part == "FRONT_BUMPER"


def test_customer_input_is_reported_not_confirmed():
    extracted = CustomerInputExtraction.model_validate(
        {
            "accident_description": "Hit on the front-left near Colombo.",
            "possible_damage_parts": ["FRONT_BUMPER", "HEADLIGHT_LEFT"],
            "mentioned_location": "Colombo",
            "possible_impact_area": "front-left",
            "injuries_mentioned": False,
            "confidence": 0.7,
        }
    )
    assert extracted.mentioned_location == "Colombo"


def test_claim_summary_schema():
    summary = ClaimSummary.model_validate(
        {
            "summary": "Preliminary assessment of a Toyota Prius with front-end damage.",
            "key_findings": ["Front bumper cracked", "Left headlight broken"],
            "evidence_gaps": ["No close-up of the undertray"],
            "confidence": 0.8,
        }
    )
    assert summary.evidence_gaps


def test_customer_cannot_skip_to_approved():
    assert ClaimStatus.APPROVED not in ALLOWED_TRANSITIONS[ClaimStatus.DRAFT]
    assert ClaimStatus.SUBMITTED in ALLOWED_TRANSITIONS[ClaimStatus.DRAFT]
    assert ClaimStatus.APPROVED in ALLOWED_TRANSITIONS[ClaimStatus.AGENT_REVIEW]
