"""The claim assessment pipeline.

Fifteen stages, run in order. The governing rule is that **the claim always completes**. A
stage that cannot produce a grounded result records why, adds a manual-review reason and
returns; it never aborts the run and never substitutes a plausible value.

The pipeline also publishes a progress frame per stage, which is what drives the customer's
live processing screen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai.ocr import find_plate_candidates, read_with_tesseract, reconcile_readings
from app.ai.prompts.templates import (
    CLAIM_SUMMARY_PROMPT,
    CLAIM_SUMMARY_SYSTEM,
    CUSTOMER_INPUT_PROMPT,
    CUSTOMER_INPUT_SYSTEM,
    DAMAGE_DETECTION_PROMPT,
    DAMAGE_DETECTION_SYSTEM,
    ESTIMATE_REASONING_PROMPT,
    ESTIMATE_REASONING_SYSTEM,
    PLATE_OCR_PROMPT,
    PLATE_OCR_SYSTEM,
    PROMPT_VERSION,
    VEHICLE_ID_PROMPT,
    VEHICLE_ID_SYSTEM,
    render,
)
from app.ai.base import ImagePayload
from app.ai.registry import AIRunner, StageFailure
from app.ai.schemas import (
    ClaimSummary,
    CustomerInputExtraction,
    EstimateReasoning,
    ImageDamageAnalysis,
    PlateReading,
    VehicleIdentification,
)
from app.core.config import settings
from app.core.enums import (
    AIStage,
    ClaimStatus,
    DamageSeverity,
    DataStatus,
    ImageRole,
    RepairAction,
    RiskLevel,
)
from app.core.logging import get_logger
from app.core.parts import is_structural, part_display_name
from app.estimation.engine import DamageEstimateService, PartInput, damage_to_value_ratio
from app.fraud import detectors
from app.market.research import PartsPricingResearchService, VehicleValuationService
from app.media.images import crop_normalised, to_jpeg_bytes
from app.media.storage import get_storage
from app.models.assessment import DamageAssessment, DamagedPart
from app.models.claim import Claim
from app.models.estimate import RepairEstimate, RepairEstimateLine
from app.notifications import hub
from app.notifications.service import NotificationService
from app.services.claims import ClaimService

log = get_logger(__name__)

STAGES = [
    ("VALIDATING_IMAGES", "Checking image quality"),
    ("EXTRACTING_METADATA", "Reading image metadata"),
    ("IDENTIFYING_VEHICLE", "Identifying the vehicle"),
    ("READING_PLATE", "Reading the number plate"),
    ("PROCESSING_CUSTOMER_INPUT", "Reading your description"),
    ("DETECTING_DAMAGE", "Detecting damage"),
    ("RECONCILING", "Comparing your report with the analysis"),
    ("VEHICLE_VALUATION", "Checking vehicle market value"),
    ("PART_PRICING", "Researching part prices"),
    ("ESTIMATING", "Calculating the repair estimate"),
    ("SUMMARISING", "Preparing the assessment"),
    ("SCORING_CONFIDENCE", "Scoring confidence"),
    ("RISK_ANALYSIS", "Checking consistency"),
    ("REVIEW_DECISION", "Determining review requirements"),
    ("NOTIFYING_AGENT", "Notifying an insurance agent"),
]


@dataclass
class PipelineState:
    claim: Claim
    assessment: DamageAssessment
    stage_confidences: dict[str, float] = field(default_factory=dict)
    review_reasons: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    customer_input: CustomerInputExtraction | None = None
    image_payloads: dict[uuid.UUID, bytes] = field(default_factory=dict)

    def flag(self, reason: str) -> None:
        if reason not in self.review_reasons:
            self.review_reasons.append(reason)


class ClaimAssessmentPipeline:
    def __init__(self, db: Session, claim: Claim):
        self.db = db
        self.claim = claim
        self.runner = AIRunner(db, claim.id)
        self.claims = ClaimService(db)
        self.storage = get_storage()

    # ── Entry point ─────────────────────────────────────────

    def run(self) -> Claim:
        claim = self.claim
        log.info("pipeline.start", claim_id=str(claim.id), claim_number=claim.claim_number)

        self.claims.transition(claim, ClaimStatus.PROCESSING, None, "Automated analysis started.")
        self.db.commit()

        assessment = DamageAssessment(
            claim_id=claim.id,
            provider=settings.vision_provider,
            model="pending",
            prompt_version=PROMPT_VERSION,
        )
        self.db.add(assessment)
        self.db.flush()

        state = PipelineState(claim=claim, assessment=assessment)

        try:
            self._stage(state, 0, self._validate_images)
            self._stage(state, 1, self._extract_metadata)

            self.claims.transition(claim, ClaimStatus.AI_ANALYZING, None, "Vision analysis.")
            self.db.commit()

            self._stage(state, 2, self._identify_vehicle)
            self._stage(state, 3, self._read_plate)
            self._stage(state, 4, self._process_customer_input)
            self._stage(state, 5, self._detect_damage)
            self._stage(state, 6, self._reconcile)

            self.claims.transition(claim, ClaimStatus.MARKET_RESEARCH, None, "Market research.")
            self.db.commit()

            self._stage(state, 7, self._research_valuation)
            self._stage(state, 8, self._research_part_prices)

            self.claims.transition(claim, ClaimStatus.ESTIMATING, None, "Cost estimation.")
            self.db.commit()

            self._stage(state, 9, self._estimate)
            self._stage(state, 10, self._summarise)
            self._stage(state, 11, self._score_confidence)
            self._stage(state, 12, self._analyse_risk)
            self._stage(state, 13, self._decide_review)

            self.claims.transition(claim, ClaimStatus.AI_COMPLETED, None, "Analysis complete.")
            self.db.commit()

            self._stage(state, 14, self._notify)

            self.claims.transition(
                claim, ClaimStatus.AGENT_REVIEW, None, "Awaiting insurance agent review."
            )
            self.db.commit()

        except Exception as exc:  # noqa: BLE001 — the claim must survive any failure
            log.exception("pipeline.unhandled", claim_id=str(claim.id), error=str(exc))
            self.db.rollback()
            self._fail_to_manual_review(str(exc))

        log.info("pipeline.finished", claim_id=str(claim.id), status=claim.status.value)
        return claim

    # ── Stage plumbing ──────────────────────────────────────

    def _stage(self, state: PipelineState, index: int, fn) -> None:
        code, label = STAGES[index]
        self._publish_progress(index, code, label, "RUNNING")

        try:
            fn(state)
            status = "OK"
        except StageFailure as exc:
            # Every provider failed. Record it, keep going.
            status = "SKIPPED"
            state.flag(
                f"The '{label.lower()}' step could not be completed automatically "
                f"({exc}). Manual assessment is required for this part of the claim."
            )
            state.unavailable.append(label)
            log.warning("pipeline.stage_skipped", stage=code, claim_id=str(state.claim.id))
        except Exception as exc:  # noqa: BLE001
            status = "ERROR"
            state.flag(f"The '{label.lower()}' step failed unexpectedly and needs manual review.")
            state.unavailable.append(label)
            log.exception("pipeline.stage_error", stage=code, error=str(exc))

        self.claim.pipeline_stage = code
        progress = dict(self.claim.pipeline_progress or {})
        progress[code] = {"status": status, "label": label, "step": index + 1, "of": len(STAGES)}
        self.claim.pipeline_progress = progress
        self.db.flush()
        self.db.commit()

        self._publish_progress(index, code, label, status)

    def _publish_progress(self, index: int, code: str, label: str, status: str) -> None:
        customer_user_id = (
            self.claim.customer.user_id if self.claim.customer else None
        )
        event = {
            "type": "claim.progress",
            "claim_id": str(self.claim.id),
            "stage": code,
            "message": label,
            "step": index + 1,
            "of": len(STAGES),
            "status": status,
        }
        if customer_user_id:
            hub.publish_to_user(customer_user_id, event)
        hub.publish_to_agents(event)

    def _fail_to_manual_review(self, error: str) -> None:
        try:
            self.claims.set_manual_review(
                self.claim,
                True,
                [
                    "Automated analysis did not complete. This claim requires full manual "
                    "assessment by an agent.",
                ],
            )
            self.claims.transition(
                self.claim, ClaimStatus.AGENT_REVIEW, None,
                f"Automated analysis failed: {error[:200]}", force=True,
            )
            self.db.commit()
        except Exception:  # noqa: BLE001
            self.db.rollback()
            log.exception("pipeline.failover_failed", claim_id=str(self.claim.id))

    # ── Stage 1: image validation ───────────────────────────

    def _validate_images(self, state: PipelineState) -> None:
        images = [i for i in state.claim.images if i.is_usable_for_analysis]

        if len(images) < settings.min_evidence_images:
            state.flag(
                f"Only {len(images)} usable photograph(s) were supplied; "
                f"{settings.min_evidence_images} is the minimum for a reliable assessment."
            )

        poor = [i for i in images if (i.quality_score or 1) < 0.35]
        if poor:
            state.flag(
                f"{len(poor)} photograph(s) are of low quality, which reduces the reliability "
                "of damage detection."
            )

        for image in images:
            try:
                raw = self.storage.get(image.storage_key)
                state.image_payloads[image.id] = to_jpeg_bytes(raw)
            except Exception as exc:  # noqa: BLE001
                log.warning("pipeline.image_load_failed", image_id=str(image.id), error=str(exc))

        if not state.image_payloads:
            raise StageFailure(
                AIStage.DAMAGE_DETECTION, "No images could be loaded from storage."
            )

    # ── Stage 2: metadata ───────────────────────────────────

    def _extract_metadata(self, state: PipelineState) -> None:
        """Metadata was captured at upload; this stage reports on what is available."""
        from app.services.images import ImageService

        metadata = [i.image_metadata for i in state.claim.images if i.image_metadata]
        with_exif = [m for m in metadata if m.has_exif]

        if not with_exif:
            state.notes.append(
                "No photograph carried EXIF metadata, so capture time and camera details "
                "could not be established from the files."
            )

        location = ImageService(self.db).resolve_location_from_exif(state.claim)
        if location is None and state.claim.location is None:
            state.notes.append(
                "No location was available from image metadata or the device, so the "
                "accident location is unconfirmed."
            )

    # ── Stage 3: vehicle identification ─────────────────────

    def _identify_vehicle(self, state: PipelineState) -> None:
        images = self._images_for(state, prefer=[ImageRole.FRONT, ImageRole.REAR, ImageRole.LEFT, ImageRole.RIGHT], limit=3)
        if not images:
            raise StageFailure(AIStage.VEHICLE_IDENTIFICATION, "No usable images.")

        claim = state.claim
        result: VehicleIdentification = self.runner.run_vision(
            stage=AIStage.VEHICLE_IDENTIFICATION,
            system=VEHICLE_ID_SYSTEM,
            prompt=render(
                VEHICLE_ID_PROMPT,
                stated_make=claim.stated_make,
                stated_model=claim.stated_model,
                stated_year=claim.stated_year,
                stated_color=claim.stated_color,
                vehicle_description=claim.customer_vehicle_description,
            ),
            images=images,
            schema=VehicleIdentification,
            prompt_version=PROMPT_VERSION,
        )

        assessment = state.assessment
        assessment.vehicle_make = result.make
        assessment.vehicle_model = result.model
        assessment.vehicle_variant = result.variant
        assessment.vehicle_year = result.year_estimate
        assessment.vehicle_color = result.color
        assessment.vehicle_type = result.vehicle_type
        assessment.vehicle_confidence = Decimal(str(result.confidence))
        if result.year_range:
            assessment.vehicle_year_min, assessment.vehicle_year_max = result.year_range

        state.stage_confidences["vehicle_identification"] = result.confidence
        state.notes.extend(result.notes)

        if not result.vehicle_visible:
            state.flag("No vehicle could be identified in the photographs supplied.")
        if result.multiple_vehicles:
            state.flag(
                "More than one vehicle appears in the photographs; the subject vehicle "
                "must be confirmed manually."
            )
        if result.confidence < settings.review_min_vehicle:
            state.flag(
                f"Vehicle identification confidence is {result.confidence:.0%}, below the "
                f"{settings.review_min_vehicle:.0%} threshold for automatic acceptance."
            )

        self._check_vehicle_conflict(state, result)
        self.db.flush()

    def _check_vehicle_conflict(self, state: PipelineState, result: VehicleIdentification) -> None:
        claim = state.claim
        conflicts: list[str] = []

        if claim.stated_make and result.make and claim.stated_make.lower() != result.make.lower():
            conflicts.append(f"make (stated {claim.stated_make}, detected {result.make})")
        if claim.stated_model and result.model and claim.stated_model.lower() != result.model.lower():
            conflicts.append(f"model (stated {claim.stated_model}, detected {result.model})")
        if (
            claim.stated_year
            and result.year_estimate
            and abs(claim.stated_year - result.year_estimate) > 2
        ):
            conflicts.append(
                f"year (stated {claim.stated_year}, detected around {result.year_estimate})"
            )

        if not conflicts:
            return

        detail = (
            "The vehicle identified from the photographs does not match the details the "
            "customer provided: " + "; ".join(conflicts) + ". This may be an honest mistake, "
            "a similar-looking model, or the wrong vehicle — it must be resolved before the "
            "claim is assessed."
        )
        state.assessment.vehicle_conflict = True
        state.assessment.vehicle_conflict_detail = detail
        state.flag("Vehicle information mismatch: manual verification required.")

    # ── Stage 4: plate OCR ──────────────────────────────────

    def _read_plate(self, state: PipelineState) -> None:
        plate_images = [
            i for i in state.claim.images
            if i.image_role is ImageRole.NUMBER_PLATE and i.id in state.image_payloads
        ]
        source_images = plate_images or [
            i for i in state.claim.images
            if i.image_role in {ImageRole.FRONT, ImageRole.REAR} and i.id in state.image_payloads
        ]
        if not source_images:
            source_images = [i for i in state.claim.images if i.id in state.image_payloads][:2]

        if not source_images:
            state.notes.append("No photograph suitable for reading a number plate was supplied.")
            return

        best_text: str | None = None
        best_confidence = 0.0
        best_note = ""

        for image in source_images[:2]:
            raw = state.image_payloads[image.id]

            # A tight crop around a plate candidate reads far more reliably than the whole
            # photo; fall back to the full frame when detection finds nothing.
            candidates = find_plate_candidates(raw, limit=1)
            crop = raw
            if candidates:
                try:
                    crop = crop_normalised(raw, candidates[0].box, padding=0.08)
                except Exception:  # noqa: BLE001
                    crop = raw

            try:
                reading: PlateReading = self.runner.run_vision(
                    stage=AIStage.PLATE_OCR,
                    system=PLATE_OCR_SYSTEM,
                    prompt=render(PLATE_OCR_PROMPT),
                    images=[ImagePayload(data=crop, reference="plate_crop")],
                    schema=PlateReading,
                    prompt_version=PROMPT_VERSION,
                )
            except StageFailure:
                continue

            tesseract_text, tesseract_confidence = read_with_tesseract(crop)
            text, confidence, note = reconcile_readings(
                reading.registration_number, reading.confidence,
                tesseract_text, tesseract_confidence,
            )

            if text and confidence > best_confidence:
                best_text, best_confidence, best_note = text, confidence, note

        assessment = state.assessment
        assessment.detected_registration = best_text
        assessment.ocr_confidence = Decimal(str(best_confidence))
        state.stage_confidences["plate_ocr"] = best_confidence

        if best_note:
            state.notes.append(best_note)

        if best_text is None:
            state.notes.append(
                "No registration number could be read. Ask the customer to confirm it."
            )
        elif best_confidence < settings.review_min_ocr:
            state.flag(
                f"The number plate was read as '{best_text}' with only "
                f"{best_confidence:.0%} confidence. Customer confirmation is required."
            )

        if (
            best_text
            and state.claim.stated_registration
            and best_text.replace(" ", "").replace("-", "")
            != state.claim.stated_registration.replace(" ", "").replace("-", "")
        ):
            state.flag(
                f"The plate read from the photographs ('{best_text}') differs from the "
                f"registration the customer gave ('{state.claim.stated_registration}')."
            )

        self.db.flush()

    # ── Stage 5: customer input ─────────────────────────────

    def _process_customer_input(self, state: PipelineState) -> None:
        claim = state.claim
        report = claim.damage_report

        has_text = any(
            [claim.accident_description, claim.customer_vehicle_description,
             report.free_text_parts if report else None]
        )
        if not has_text:
            state.notes.append("The customer did not provide a written description.")
            return

        extraction: CustomerInputExtraction = self.runner.run_text(
            stage=AIStage.CUSTOMER_INPUT_EXTRACTION,
            system=CUSTOMER_INPUT_SYSTEM,
            prompt=render(
                CUSTOMER_INPUT_PROMPT,
                accident_description=claim.accident_description,
                vehicle_description=claim.customer_vehicle_description,
                selected_parts=", ".join(
                    part_display_name(c) for c in (report.reported_parts if report else [])
                ),
                free_text_parts=report.free_text_parts if report else None,
            ),
            schema=CustomerInputExtraction,
            prompt_version=PROMPT_VERSION,
        )

        state.customer_input = extraction
        state.stage_confidences["customer_input"] = extraction.confidence

        if report is not None:
            report.structured_extraction = extraction.model_dump()
            report.extracted_parts = extraction.possible_damage_parts
            report.possible_impact_area = extraction.possible_impact_area
            report.mentioned_location = extraction.mentioned_location
            report.extraction_confidence = extraction.confidence
            self.db.flush()

        if extraction.injuries_mentioned:
            state.flag(
                "The customer's description mentions injuries. This claim needs priority "
                "handling by an agent."
            )

    # ── Stage 6: damage detection ───────────────────────────

    def _detect_damage(self, state: PipelineState) -> None:
        claim = state.claim
        report = claim.damage_report
        customer_parts = report.all_reported_part_codes if report else []

        images = [i for i in claim.images if i.id in state.image_payloads]
        if not images:
            raise StageFailure(AIStage.DAMAGE_DETECTION, "No images available.")

        # part code → the strongest finding across all photographs. The same bumper seen in
        # three photos is one damaged part, not three.
        best: dict[str, tuple[float, DamagedPart]] = {}
        confidences: list[float] = []
        analysed = 0

        for image in images:
            annotation_summary = (
                "; ".join(
                    f"{a.annotation_type.value.lower()} labelled '{a.label}'"
                    for a in image.annotations
                )
                or "None"
            )

            try:
                analysis: ImageDamageAnalysis = self.runner.run_vision(
                    stage=AIStage.DAMAGE_DETECTION,
                    system=DAMAGE_DETECTION_SYSTEM,
                    prompt=render(
                        DAMAGE_DETECTION_PROMPT,
                        accident_description=claim.accident_description,
                        customer_parts=", ".join(part_display_name(c) for c in customer_parts),
                        image_note=image.customer_note,
                        annotation_summary=annotation_summary,
                    ),
                    images=[
                        ImagePayload(
                            data=state.image_payloads[image.id],
                            reference=f"image_{image.display_order + 1}",
                        )
                    ],
                    schema=ImageDamageAnalysis,
                    prompt_version=PROMPT_VERSION,
                )
            except StageFailure:
                continue

            analysed += 1
            state.notes.extend(analysis.notes)

            if not analysis.quality_sufficient:
                state.flag(
                    f"Photograph {image.display_order + 1} was not clear enough to assess."
                )
                continue

            for damage in analysis.damages:
                part = DamagedPart(
                    assessment_id=state.assessment.id,
                    image_id=image.id,
                    canonical_part=damage.canonical_part,
                    display_name=damage.display_name or part_display_name(damage.canonical_part),
                    damage_type=damage.damage_type,
                    severity=damage.severity,
                    confidence=Decimal(str(damage.confidence)),
                    bounding_box=(
                        damage.bounding_box.model_dump() if damage.bounding_box else None
                    ),
                    recommended_action=damage.recommended_action,
                    explanation=damage.explanation,
                    ai_detected=True,
                    customer_reported=damage.canonical_part in customer_parts,
                )
                confidences.append(damage.confidence)

                existing = best.get(damage.canonical_part)
                if existing is None or damage.confidence > existing[0]:
                    best[damage.canonical_part] = (damage.confidence, part)

        if analysed == 0:
            raise StageFailure(AIStage.DAMAGE_DETECTION, "No photograph could be analysed.")

        for _, part in best.values():
            self.db.add(part)

        average = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        state.assessment.damage_confidence = Decimal(str(average))
        state.stage_confidences["damage_detection"] = average
        state.assessment.provider = settings.vision_provider
        state.assessment.model = (
            self.runner.active_provider_names()["vision"] + "/" + PROMPT_VERSION
        )
        self.db.flush()

        if not best:
            state.flag(
                "No damage was detected in any photograph. If the vehicle is damaged, "
                "clearer or closer photographs are needed."
            )
        if average and average < settings.review_min_damage:
            state.flag(
                f"Damage detection confidence averaged {average:.0%}, below the "
                f"{settings.review_min_damage:.0%} threshold."
            )

        structural = [c for c in best if is_structural(c)]
        if structural:
            state.flag(
                "Possible structural damage was identified ("
                + ", ".join(part_display_name(c) for c in structural)
                + "). Physical inspection is required."
            )

        critical = [
            part.display_name for _, part in best.values()
            if part.severity is DamageSeverity.CRITICAL
        ]
        if critical:
            state.flag(f"Critical-severity damage reported on: {', '.join(critical)}.")

    # ── Stage 7: reconciliation ─────────────────────────────

    def _reconcile(self, state: PipelineState) -> None:
        """Add customer-reported parts the AI did not find, as unconfirmed rows.

        They are stored with `ai_detected=False` so they appear in the agent's diff view.
        They are never priced or costed — an unverified report is not evidence of damage.
        """
        report = state.claim.damage_report
        if report is None:
            return

        self.db.refresh(state.assessment)
        detected = {p.canonical_part for p in state.assessment.damaged_parts}
        customer_parts = set(report.all_reported_part_codes)

        for code in sorted(customer_parts - detected):
            self.db.add(
                DamagedPart(
                    assessment_id=state.assessment.id,
                    canonical_part=code,
                    display_name=part_display_name(code),
                    customer_reported=True,
                    ai_detected=False,
                    recommended_action=RepairAction.INSPECT,
                    explanation=(
                        "Reported by the customer but not confirmed from the photographs. "
                        "This may be damage that is not visible in the images supplied, or "
                        "a mistaken report — an agent must verify it."
                    ),
                )
            )

        self.db.flush()
        self.db.refresh(state.assessment)

        unconfirmed = customer_parts - detected
        additional = detected - customer_parts

        if unconfirmed:
            state.flag(
                "The customer reported damage the analysis could not confirm: "
                + ", ".join(part_display_name(c) for c in sorted(unconfirmed))
                + "."
            )
        if additional:
            state.flag(
                "The analysis found possible damage the customer did not report: "
                + ", ".join(part_display_name(c) for c in sorted(additional))
                + "."
            )

    # ── Stage 8: vehicle valuation ──────────────────────────

    def _research_valuation(self, state: PipelineState) -> None:
        assessment = state.assessment
        make = assessment.vehicle_make or state.claim.stated_make
        model = assessment.vehicle_model or state.claim.stated_model
        year = assessment.vehicle_year or state.claim.stated_year

        valuation = VehicleValuationService(self.db, state.claim.id).research(
            make=make, model=model, year=year
        )

        if valuation.status is DataStatus.UNAVAILABLE:
            state.unavailable.append("Vehicle market value")
            state.flag(
                "No reliable market valuation could be obtained for this vehicle: "
                + (valuation.unavailable_reason or "no sources returned usable data.")
            )
        else:
            state.stage_confidences["vehicle_valuation"] = float(valuation.confidence or 0)

    # ── Stage 9: part pricing ───────────────────────────────

    def _research_part_prices(self, state: PipelineState) -> None:
        self.db.refresh(state.assessment)
        assessment = state.assessment

        make = assessment.vehicle_make or state.claim.stated_make
        model = assessment.vehicle_model or state.claim.stated_model
        year = assessment.vehicle_year or state.claim.stated_year

        service = PartsPricingResearchService(self.db, state.claim.id)
        priced = 0
        confidences: list[float] = []

        for part in assessment.damaged_parts:
            if not part.ai_detected:
                continue  # unconfirmed customer reports are not costed

            summary = service.research_part(part, make=make, model=model, year=year)
            if summary.status is DataStatus.AVAILABLE:
                priced += 1
                confidences.append(float(summary.price_confidence or 0))

        costable = [p for p in assessment.damaged_parts if p.ai_detected]
        if costable and priced == 0:
            state.unavailable.append("Part prices")
            state.flag(
                "No part prices could be obtained from the approved market sources, so the "
                "repair estimate excludes component costs entirely."
            )
        elif priced < len(costable):
            state.flag(
                f"Prices were found for {priced} of {len(costable)} damaged part(s); the "
                "estimate is incomplete."
            )

        if confidences:
            average = round(sum(confidences) / len(confidences), 3)
            state.stage_confidences["part_pricing"] = average
            if average < settings.review_min_price:
                state.flag(
                    f"Part price confidence averaged {average:.0%}, below the "
                    f"{settings.review_min_price:.0%} threshold."
                )

    # ── Stage 10: estimation ────────────────────────────────

    def _estimate(self, state: PipelineState) -> None:
        self.db.refresh(state.assessment)
        parts = [p for p in state.assessment.damaged_parts if p.ai_detected]

        if not parts:
            state.notes.append("No confirmed damage, so no repair estimate was produced.")
            return

        reasoning = self._estimate_reasoning(state, parts)

        inputs: list[PartInput] = []
        for part in parts:
            summary = part.price_summary
            suggestion = reasoning.get(part.canonical_part)

            inputs.append(
                PartInput(
                    canonical_part=part.canonical_part,
                    damage_type=part.damage_type,
                    severity=part.severity,
                    damaged_part_id=part.id,
                    model_action=suggestion.action if suggestion else part.recommended_action,
                    model_labour_hours=suggestion.labour_hours_estimate if suggestion else None,
                    price_min=(
                        summary.price_min if summary and summary.status is DataStatus.AVAILABLE else None
                    ),
                    price_max=(
                        summary.price_max if summary and summary.status is DataStatus.AVAILABLE else None
                    ),
                    price_source_count=summary.source_count if summary else 0,
                    price_confidence=float(summary.price_confidence) if summary and summary.price_confidence else None,
                    detection_confidence=float(part.confidence) if part.confidence else None,
                )
            )

        result = DamageEstimateService().estimate(inputs)

        estimate = RepairEstimate(
            claim_id=state.claim.id,
            estimated_min=result.total_min,
            estimated_max=result.total_max,
            currency=result.currency,
            parts_subtotal_min=result.parts_min,
            parts_subtotal_max=result.parts_max,
            labour_min=result.labour_min,
            labour_max=result.labour_max,
            paint_min=result.paint_min,
            paint_max=result.paint_max,
            materials_min=result.materials_min,
            materials_max=result.materials_max,
            confidence=Decimal(str(result.confidence)),
            unpriced_parts=result.unpriced_parts,
            is_partial=result.is_partial,
            labour_rate_used=settings.labour_rate_per_hour,
            paint_rate_used=settings.paint_rate_per_panel,
            calculation_notes=result.notes,
        )
        self.db.add(estimate)
        self.db.flush()

        for line in result.lines:
            self.db.add(
                RepairEstimateLine(
                    estimate_id=estimate.id,
                    damaged_part_id=line.damaged_part_id,
                    canonical_part=line.canonical_part,
                    display_name=line.display_name,
                    action=line.action,
                    part_price_min=line.part_price_min,
                    part_price_max=line.part_price_max,
                    part_price_available=line.part_price_available,
                    labour_hours=line.labour_hours,
                    labour_rate=line.labour_rate,
                    labour_min=line.labour_min,
                    labour_max=line.labour_max,
                    paint_panels=line.paint_panels,
                    paint_min=line.paint_min,
                    paint_max=line.paint_max,
                    line_min=line.line_min,
                    line_max=line.line_max,
                    currency=line.currency,
                    basis=line.basis,
                    price_source_count=line.price_source_count,
                    confidence=Decimal(str(line.confidence)),
                )
            )

        # Write the engine's action decisions back so the assessment view and the estimate
        # never disagree about whether a part is being repaired or replaced.
        by_code = {line.canonical_part: line for line in result.lines}
        for part in parts:
            line = by_code.get(part.canonical_part)
            if line is not None:
                part.recommended_action = line.action
                part.action_rationale = line.basis
                part.labour_hours = line.labour_hours
                part.paint_panels = line.paint_panels

        valuation = state.claim.latest_valuation
        if valuation and valuation.status is DataStatus.AVAILABLE:
            ratio = damage_to_value_ratio(result.total_max, valuation.estimated_min)
            estimate.damage_to_value_ratio = ratio
            if ratio is not None and float(ratio) > settings.review_ratio_threshold:
                state.flag(
                    f"The estimated damage is {float(ratio):.0%} of the lower bound of the "
                    f"vehicle's market value. This is an assessment signal only — a total-loss "
                    f"determination requires an authorised agent."
                )

        state.stage_confidences["estimation"] = result.confidence

        if float(result.total_max) > settings.review_amount_threshold:
            state.flag(
                f"The estimate exceeds the "
                f"{settings.review_amount_threshold:,.0f} {result.currency} threshold for "
                f"mandatory senior review."
            )

        self.db.flush()

    def _estimate_reasoning(self, state: PipelineState, parts: list[DamagedPart]) -> dict:
        vehicle_label = state.assessment.vehicle_label
        damage_list = "\n".join(
            f"  - {p.canonical_part}: {p.damage_type.value} at {p.severity.value} severity"
            f" — {p.explanation or 'no further detail'}"
            for p in parts
        )

        try:
            reasoning: EstimateReasoning = self.runner.run_text(
                stage=AIStage.ESTIMATE_REASONING,
                system=ESTIMATE_REASONING_SYSTEM,
                prompt=render(
                    ESTIMATE_REASONING_PROMPT,
                    vehicle_label=vehicle_label,
                    damage_list=damage_list,
                ),
                schema=EstimateReasoning,
                prompt_version=PROMPT_VERSION,
            )
        except StageFailure:
            # The rules engine has defaults for every part, so losing this stage degrades
            # the estimate's nuance but not its validity.
            state.notes.append(
                "Repair-method reasoning was unavailable; standard repair times were used."
            )
            return {}

        return {item.canonical_part: item for item in reasoning.items}

    # ── Stage 11: summary ───────────────────────────────────

    def _summarise(self, state: PipelineState) -> None:
        from app.services.presenters import ClaimPresenter

        self.db.refresh(state.claim)
        presenter = ClaimPresenter(self.db)
        reconciliation = presenter.reconciliation(state.assessment)

        ai_damage = "\n".join(
            f"  - {p.display_name}: {p.damage_type.value}, {p.severity.value} severity, "
            f"{float(p.confidence or 0):.0%} confidence"
            for p in state.assessment.damaged_parts
            if p.ai_detected
        ) or "None detected"

        evidence = (
            f"{len(state.claim.images)} photograph(s); "
            f"{sum(len(i.annotations) for i in state.claim.images)} customer annotation(s); "
            f"location {'available' if state.claim.location else 'not available'}"
        )

        risk = "\n".join(f"  - {s.description}" for s in state.claim.fraud_signals) or "None raised"

        summary: ClaimSummary = self.runner.run_text(
            stage=AIStage.CLAIM_SUMMARY,
            system=CLAIM_SUMMARY_SYSTEM,
            prompt=render(
                CLAIM_SUMMARY_PROMPT,
                vehicle_summary=state.assessment.vehicle_label,
                customer_account=state.claim.accident_description,
                customer_parts=", ".join(reconciliation.customer_reported) or "None reported",
                ai_damage=ai_damage,
                reconciliation=reconciliation.summary,
                evidence_summary=evidence,
                unavailable_data=", ".join(state.unavailable) or "None",
                risk_signals=risk,
            ),
            schema=ClaimSummary,
            prompt_version=PROMPT_VERSION,
        )

        state.assessment.summary_text = summary.summary
        state.notes.extend(summary.key_findings)
        for gap in summary.evidence_gaps:
            state.notes.append(f"Evidence gap: {gap}")
        state.stage_confidences["summary"] = summary.confidence
        self.db.flush()

    # ── Stage 12: confidence ────────────────────────────────

    def _score_confidence(self, state: PipelineState) -> None:
        """Weighted mean, capped by the weakest critical stage.

        A 95 %-confident damage read on a vehicle nobody could identify is not a 90 %
        assessment, so the cap matters more than the average.
        """
        weights = {
            "vehicle_identification": 0.25,
            "damage_detection": 0.35,
            "plate_ocr": 0.05,
            "customer_input": 0.05,
            "vehicle_valuation": 0.10,
            "part_pricing": 0.10,
            "estimation": 0.10,
        }
        critical = ("vehicle_identification", "damage_detection")

        scored = {k: v for k, v in state.stage_confidences.items() if k in weights}
        if not scored:
            state.claim.overall_confidence = Decimal("0")
            state.assessment.stage_confidences = state.stage_confidences
            self.db.flush()
            return

        total_weight = sum(weights[k] for k in scored)
        weighted = sum(weights[k] * v for k, v in scored.items()) / total_weight

        critical_scores = [state.stage_confidences[k] for k in critical if k in state.stage_confidences]
        overall = min([weighted, *critical_scores]) if critical_scores else weighted

        state.claim.overall_confidence = Decimal(str(round(overall, 3)))
        state.assessment.stage_confidences = state.stage_confidences
        state.assessment.notes = state.notes[:60]
        self.db.flush()

    # ── Stage 13: risk ──────────────────────────────────────

    def _analyse_risk(self, state: PipelineState) -> None:
        self.db.refresh(state.claim)
        signals = detectors.run_all(self.db, state.claim)
        level = detectors.overall_risk(signals)

        if level is RiskLevel.HIGH:
            state.flag(
                "High-risk consistency signals were raised on this claim and must be "
                "reviewed before any decision."
            )
        elif level is RiskLevel.MEDIUM:
            state.flag("Consistency signals were raised that warrant a closer look.")

    # ── Stage 14: review decision ───────────────────────────

    def _decide_review(self, state: PipelineState) -> None:
        """Decide whether a human must review — the answer is usually yes.

        This system assists an assessor; it does not replace one. Manual review is cleared
        only when every stage succeeded with good confidence, the customer and the analysis
        agree, all costs are grounded in sources, and nothing was flagged.
        """
        required = bool(state.review_reasons)

        if not required:
            confidence = float(state.claim.overall_confidence or 0)
            if confidence < max(settings.review_min_vehicle, settings.review_min_damage):
                required = True
                state.flag(
                    f"Overall assessment confidence is {confidence:.0%}, which is below the "
                    "threshold for acceptance without review."
                )

        estimate = state.claim.latest_estimate
        if estimate is not None and estimate.is_partial:
            required = True
            state.flag(
                "The repair estimate is incomplete because some parts could not be priced."
            )

        self.claims.set_manual_review(state.claim, required, state.review_reasons)
        self.db.flush()

    # ── Stage 15: notification ──────────────────────────────

    def _notify(self, state: PipelineState) -> None:
        from app.services.presenters import ClaimPresenter

        self.db.refresh(state.claim)
        presenter = ClaimPresenter(self.db)
        claim = state.claim

        estimate_range = presenter.estimate_range(claim)
        market = presenter.market_data(claim)
        reconciliation = presenter.reconciliation(state.assessment)

        summary = {
            "vehicle": state.assessment.vehicle_label,
            "customer_reported": ", ".join(reconciliation.customer_reported) or None,
            "ai_detected": ", ".join(reconciliation.ai_detected) or None,
            "estimate": (
                f"{estimate_range.min:,.0f}–{estimate_range.max:,.0f} {estimate_range.currency}"
                if estimate_range and estimate_range.status == "AVAILABLE"
                else None
            ),
            "vehicle_value": (
                f"{market.valuation.min:,.0f}–{market.valuation.max:,.0f} "
                f"{market.valuation.currency}"
                if market.valuation.status == "AVAILABLE"
                else None
            ),
            "location": (claim.location.city or claim.location.address) if claim.location else None,
            "image_count": len(claim.images),
            "manual_review_reasons": claim.manual_review_reasons or [],
        }

        service = NotificationService(self.db)
        service.notify_new_claim(claim, summary)
        service.notify_claim_status(
            claim,
            f"Your claim {claim.claim_number} has been analysed",
            "Your claim has been assessed and passed to an insurance agent for review. "
            "The estimate shown is preliminary and may change after inspection.",
        )

        hub.publish_to_agents(
            {
                "type": "claim.completed",
                "claim_id": str(claim.id),
                "claim_number": claim.claim_number,
                "manual_review_required": claim.manual_review_required,
            }
        )
        if claim.customer:
            hub.publish_to_user(
                claim.customer.user_id,
                {
                    "type": "claim.completed",
                    "claim_id": str(claim.id),
                    "manual_review_required": claim.manual_review_required,
                },
            )

        claim.ai_completed_at = claim.ai_completed_at or datetime.now(UTC)
        self.db.flush()

    # ── Helpers ─────────────────────────────────────────────

    def _images_for(
        self, state: PipelineState, *, prefer: list[ImageRole], limit: int
    ) -> list[ImagePayload]:
        images = [i for i in state.claim.images if i.id in state.image_payloads]
        preferred = [i for i in images if i.image_role in prefer]
        chosen = (preferred or images)[:limit]
        return [
            ImagePayload(
                data=state.image_payloads[i.id],
                reference=f"image_{i.display_order + 1}_{i.image_role.value.lower()}",
            )
            for i in chosen
        ]
