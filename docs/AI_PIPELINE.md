# AI pipeline

## Rule zero

The model is given evidence and asked to describe it. It is never asked to supply a fact it
cannot see. Prices, market values, timestamps and locations are supplied to the model as
retrieved data or withheld entirely — the model never produces them from memory.

Every prompt ends with the same contract clause:

> Return only valid JSON matching the given schema. If the evidence does not support a
> field, return null and add a reason to `notes`. Never estimate a value you cannot derive
> from the supplied evidence.

## Stages, one prompt each

| # | Stage | Provider kind | Input | Output schema |
| --- | --- | --- | --- | --- |
| 1 | `customer_input_extraction` | text | accident + vehicle free text | `CustomerInputExtraction` |
| 2 | `vehicle_identification` | vision | wide-shot images + customer-stated vehicle | `VehicleIdentification` |
| 3 | `plate_ocr` | vision | plate crop (or full image fallback) | `PlateReading` |
| 4 | `damage_detection` | vision | each image + its annotations + customer note | `ImageDamageAnalysis` |
| 5 | `part_normalization` | text | scraped product titles | `PartNormalization` |
| 6 | `market_interpretation` | text | scraped listing rows | `MarketInterpretation` |
| 7 | `estimate_reasoning` | text | parts + severities + price ranges + config rates | `EstimateReasoning` |
| 8 | `claim_summary` | text | the full structured record | `ClaimSummary` |

Splitting these is not stylistic. When stage 4 returns garbage we retry stage 4 with a
different provider and keep stages 1–3; a monolithic call would force us to redo everything
and would make the confidence score meaningless.

## Output schemas (abridged)

```jsonc
// VehicleIdentification
{ "make": "Toyota", "model": "Prius", "variant": null, "year_estimate": 2018,
  "year_range": [2016, 2019], "color": "silver", "vehicle_type": "HATCHBACK",
  "orientation": "FRONT_LEFT_QUARTER", "confidence": 0.92,
  "conflicts_with_customer_input": false, "notes": [] }

// ImageDamageAnalysis
{ "image_id": "…", "vehicle_visible": true, "multiple_vehicles": false,
  "quality_sufficient": true,
  "damages": [ { "canonical_part": "FRONT_BUMPER", "display_name": "Front bumper",
      "damage_type": "CRACK", "severity": "HIGH", "confidence": 0.94,
      "bounding_box": {"x":0.31,"y":0.52,"w":0.28,"h":0.19},
      "recommended_action": "REPLACE",
      "explanation": "Continuous crack across the lower valance with edge separation." } ],
  "notes": [] }

// EstimateReasoning  (per part; the arithmetic is done in Python, not by the model)
{ "canonical_part": "FRONT_BUMPER", "action": "REPAIR",
  "action_rationale": "Crack under 15 cm on a thermoplastic bumper is normally repairable.",
  "labour_hours_estimate": 3.5, "paint_panels": 1, "confidence": 0.78 }
```

`bounding_box` is normalised 0–1 so overlays survive resizing.

## Why the model does not compute money

The LLM chooses *repair vs replace* and *labour hours* — judgement calls where language
models are useful. Multiplication, range arithmetic, severity multipliers and totals happen
in `app/estimation/`, in deterministic, unit-tested Python. This keeps every currency figure
reproducible and auditable, and stops a hallucinated multiplication from reaching an agent.

## Confidence model

Per-stage confidence comes from the provider where it is meaningful (vision, OCR) and is
computed where it is not:

```
price_confidence   = w_sources(n) · w_reliability(avg) · w_compat(avg) · w_spread(σ/median) · w_freshness(age)
overall_confidence = min( weighted_mean(stage confidences), lowest_critical_stage )
```

`overall` is capped by the weakest critical stage — a 95 %-confident damage read on a vehicle
we could not identify is not a 90 % assessment. Floors that trigger manual review are
configurable per stage (`REVIEW_MIN_VEHICLE`, `REVIEW_MIN_DAMAGE`, `REVIEW_MIN_OCR`, …).

## Failure handling

| Failure | Behaviour |
| --- | --- |
| Schema violation | one repair-retry, then next provider, then stage marked `SCHEMA_ERROR` |
| Provider 5xx / timeout | exponential backoff, then fallback chain |
| Rate limited | requeue with delay, respecting `Retry-After` |
| All providers down | stage `SKIPPED`, claim still completes, manual review forced |
| No vehicle detected | claim completes with the finding recorded; customer asked for a wider shot |
| Blurry / unusable image | image flagged, excluded from detection, listed as missing evidence |

The chain never aborts the claim. A claim that reaches the agent with three skipped stages
and a loud manual-review banner is a correct outcome; a lost claim is not.

## Provider configuration

```
AI_PROVIDER=gemini            # text/reasoning
VISION_PROVIDER=gemini        # multimodal
AI_FALLBACK_CHAIN=openrouter,deepseek
AI_REQUEST_TIMEOUT_SECONDS=60
```

Setting either to `mock` activates the local development provider in
`app/ai/providers/mock.py`. It reads deterministic fixtures, is refused at startup when
`APP_ENV=production`, and stamps every result it produces with `"provider": "mock"` so a
mock-derived record can never be mistaken for a real assessment.

## Privacy

Images and the free-text descriptions go to the provider. Name, email, phone, address,
policy number and national ID do not — the vision call receives an opaque claim reference
only. `ai_analysis_logs` stores metadata and a truncated response excerpt, never image bytes.
