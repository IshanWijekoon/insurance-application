# Database schema

PostgreSQL 16. All tables carry `id UUID PK`, `created_at`, `updated_at`. Tables holding
customer or claim data also carry `deleted_at` for soft deletion. Money is stored as
`NUMERIC(14,2)` with an explicit `currency CHAR(3)` — never as float.

## Identity and roles

**users** — `email UNIQUE`, `password_hash` (Argon2id), `full_name`, `phone`,
`role ∈ {CUSTOMER, AGENT, ADMIN}`, `is_active`, `last_login_at`.
Index: `(email)`, `(role)`.

**refresh_sessions** — `user_id FK`, `token_hash UNIQUE`, `expires_at`, `revoked_at`,
`user_agent`, `ip`. Rotation: each use revokes the old row and issues a new one; reuse of a
revoked token revokes the whole family.

**customers** — `user_id FK UNIQUE`, `national_id`, `address`, `city`, `preferred_language`.

**agents** — `user_id FK UNIQUE`, `employee_code UNIQUE`, `branch`, `region`,
`is_available`, `max_concurrent_claims`.

## Vehicles and policies

**vehicles** — `customer_id FK`, `registration_number`, `make`, `model`, `variant`, `year`,
`vehicle_type`, `color`, `vin`, `is_primary`.
Index: `(customer_id)`, `(registration_number)`. Only `customer_id` is required; every
descriptive field is nullable because the customer may know none of them.

**insurance_policies** — `vehicle_id FK`, `customer_id FK`, `policy_number UNIQUE`,
`insurer_name`, `policy_type`, `coverage_amount`, `deductible`, `valid_from`, `valid_to`,
`status`.

## Claims

**claims** — `claim_number UNIQUE` (`CLM-YYYY-NNNNNN`), `customer_id FK`, `vehicle_id FK NULL`,
`policy_id FK NULL`, `assigned_agent_id FK NULL`, `status` (see below), `priority`,
`accident_datetime`, `accident_description`, `customer_vehicle_description`,
`submitted_at`, `ai_completed_at`, `decided_at`, `manual_review_required`,
`manual_review_reasons JSONB`, `overall_confidence`.
Index: `(status)`, `(customer_id)`, `(assigned_agent_id)`, `(created_at DESC)`.

`status ∈ DRAFT, SUBMITTED, PROCESSING, AI_ANALYZING, MARKET_RESEARCH, ESTIMATING,
AI_COMPLETED, AGENT_REVIEW, MORE_INFORMATION_REQUIRED, APPROVED, REJECTED,
SETTLEMENT_PROCESSING, COMPLETED`.

**claim_status_events** — `claim_id FK`, `from_status`, `to_status`, `actor_user_id FK NULL`,
`actor_type ∈ {CUSTOMER, AGENT, ADMIN, SYSTEM}`, `note`. Powers the claim timeline; append-only.

## Evidence

**claim_images** — `claim_id FK`, `storage_key UNIQUE`, `annotated_storage_key NULL`,
`original_filename`, `mime_type`, `file_size`, `width`, `height`, `sha256` (dedupe),
`perceptual_hash` (near-dupe), `image_role ∈ {FRONT, REAR, LEFT, RIGHT, DAMAGE_CLOSEUP,
NUMBER_PLATE, INTERIOR, OTHER}`, `quality_score`, `blur_score`, `validation_status`,
`validation_errors JSONB`, `customer_note`.
Index: `(claim_id)`, `(sha256)`.

**image_metadata** — `image_id FK UNIQUE`, `captured_at NULL`, `gps_latitude NULL`,
`gps_longitude NULL`, `camera_make`, `camera_model`, `orientation`, `raw_exif JSONB`,
`has_exif BOOL`. Every nullable field is genuinely absent when EXIF is missing; the loader
never substitutes upload time for capture time.

**image_annotations** — `image_id FK`, `annotation_type ∈ {RECTANGLE, POLYGON, CIRCLE,
FREEHAND, TEXT}`, `label`, `points JSONB` (`[[x,y], …]`, image-pixel coordinates),
`color`, `note`, `created_by_user_id FK`.

**customer_damage_reports** — `claim_id FK`, `reported_parts JSONB` (canonical part codes
selected via checkbox), `free_text_parts`, `structured_extraction JSONB` (LLM output over
the free text), `possible_impact_area`, `mentioned_location`.

## AI results

**damage_assessments** — `claim_id FK`, `provider`, `model`, `prompt_version`,
`vehicle_make`, `vehicle_model`, `vehicle_variant`, `vehicle_year`, `vehicle_color`,
`vehicle_confidence`, `detected_registration`, `ocr_confidence`,
`registration_confirmed_by_customer`, `vehicle_conflict BOOL`, `vehicle_conflict_detail`,
`damage_confidence`, `summary_text`, `raw_response JSONB`.

**damaged_parts** — `assessment_id FK`, `image_id FK NULL`, `canonical_part`, `display_name`,
`damage_type ∈ {SCRATCH, DENT, CRACK, BROKEN, MISSING, DEFORMATION, PAINT_DAMAGE,
GLASS_DAMAGE, POSSIBLE_STRUCTURAL, UNKNOWN}`, `severity ∈ {LOW, MEDIUM, HIGH, CRITICAL}`,
`confidence`, `bounding_box JSONB`, `recommended_action ∈ {REPAIR, REPLACE, INSPECT}`,
`explanation`, `customer_reported BOOL`, `ai_detected BOOL`.

The `customer_reported` / `ai_detected` pair is what drives the reconciliation view: rows
with only one flag set are exactly the disagreements an agent must look at.

## Market data

**market_sources** — `name UNIQUE`, `base_url`, `source_type ∈ {API, SCRAPE, DATASET}`,
`category ∈ {VEHICLE_VALUE, PART_PRICE, BOTH}`, `country`, `reliability_weight` (0–1),
`is_enabled`, `rate_limit_per_minute`, `robots_checked_at`, `robots_allows`, `notes`.
This is the whitelist: a host absent from this table is never fetched.

**vehicle_valuations** — `claim_id FK`, `make`, `model`, `year`, `country`,
`estimated_min`, `estimated_max`, `median_value`, `currency`, `confidence`,
`source_count`, `status ∈ {AVAILABLE, UNAVAILABLE}`, `unavailable_reason`.

**vehicle_valuation_sources** — `valuation_id FK`, `market_source_id FK`, `url`,
`listing_title`, `price`, `currency`, `retrieved_at`, `raw_excerpt`.

**part_price_sources** — `claim_id FK`, `damaged_part_id FK`, `market_source_id FK`, `url`,
`product_name`, `canonical_part`, `vehicle_compatibility`, `compatibility_confidence`,
`part_grade ∈ {OEM, AFTERMARKET, USED, REFURBISHED, UNKNOWN}`, `price`, `currency`,
`availability`, `retrieved_at`, `raw_excerpt`.
Index: `(claim_id)`, `(damaged_part_id)`. `retrieved_at` is mandatory — a price with no
retrieval timestamp is not storable.

**part_price_summaries** — `damaged_part_id FK UNIQUE`, `price_min`, `price_max`,
`price_median`, `currency`, `source_count`, `price_confidence`, `confidence_reason`,
`status ∈ {AVAILABLE, UNAVAILABLE}`, `unavailable_reason`.

## Estimation

**repair_estimates** — `claim_id FK`, `estimated_min`, `estimated_max`, `currency`,
`parts_subtotal_min/max`, `labour_min/max`, `paint_min/max`, `materials_min/max`,
`confidence`, `damage_to_value_ratio`, `calculation_notes`, `superseded_by_agent BOOL`,
`agent_adjusted_min/max`, `adjusted_by_agent_id FK NULL`.

**repair_estimate_lines** — `estimate_id FK`, `damaged_part_id FK`, `action`,
`part_price_min/max`, `labour_hours`, `labour_rate`, `labour_min/max`, `paint_min/max`,
`line_min/max`, `basis` (human-readable derivation, e.g. *"crack + HIGH severity on a
plastic bumper ⇒ replace; part range from 3 sources"*).

`basis` is what makes §45 of the brief work: the UI expands a number into this string plus
the linked `part_price_sources` rows.

## Operations

**claim_locations** — `claim_id FK`, `latitude`, `longitude`, `address`, `city`, `country`,
`source ∈ {EXIF_GPS, DEVICE_GPS, CUSTOMER_SELECTED, GEOCODED_FROM_TEXT}`, `accuracy_meters`.
`source` is never inferred; if no location is obtainable, no row exists.

**fraud_signals** — `claim_id FK`, `signal_code`, `risk_level ∈ {LOW, MEDIUM, HIGH}`,
`description`, `evidence JSONB`, `detector_version`.

**notifications** — `recipient_user_id FK`, `claim_id FK NULL`, `channel ∈ {IN_APP,
WEBSOCKET, EMAIL, SMS, PUSH}`, `type`, `title`, `body`, `payload JSONB`, `is_read`,
`delivery_status`, `delivery_attempts`, `last_error`, `sent_at`.

**claim_notes** — `claim_id FK`, `author_user_id FK`, `body`, `visibility ∈ {INTERNAL,
CUSTOMER_VISIBLE}`.

**ai_analysis_logs** — `claim_id FK NULL`, `stage`, `provider`, `model`, `prompt_version`,
`request_id`, `status ∈ {SUCCESS, SCHEMA_ERROR, PROVIDER_ERROR, TIMEOUT, RATE_LIMITED,
SKIPPED}`, `latency_ms`, `input_tokens`, `output_tokens`, `error_message`,
`response_excerpt`. Deliberately stores no image bytes and no customer PII.

**audit_logs** — `actor_user_id FK NULL`, `action`, `entity_type`, `entity_id`,
`before JSONB`, `after JSONB`, `ip`, `user_agent`. Append-only; no update or delete grant.

## Relationship overview

```
users ──1:1── customers ──1:N── vehicles ──1:N── insurance_policies
  │                │                              │
  │                └──1:N── claims ───────────────┘
  └──1:1── agents        │
                         ├──1:N── claim_images ──1:1── image_metadata
                         │                       └──1:N── image_annotations
                         ├──1:1── customer_damage_reports
                         ├──1:N── damage_assessments ──1:N── damaged_parts
                         │                                    ├──1:N── part_price_sources
                         │                                    └──1:1── part_price_summaries
                         ├──1:N── vehicle_valuations ──1:N── vehicle_valuation_sources
                         ├──1:N── repair_estimates ──1:N── repair_estimate_lines
                         ├──0:1── claim_locations
                         ├──1:N── fraud_signals / claim_notes / claim_status_events
                         └──1:N── notifications
```
