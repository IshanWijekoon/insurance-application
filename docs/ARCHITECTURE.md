# Architecture — AI Motor Insurance Claim Assessment Platform

## 1. Guiding principles

Ordered by precedence. When two principles conflict, the earlier one wins.

1. **Accuracy** — never assert something the evidence does not support.
2. **Evidence** — every claim-level fact is traceable to an image, a customer input, an EXIF field, or a named web source.
3. **Explainability** — every number in an estimate can be expanded into the inputs that produced it.
4. **Data sources** — a price without a source is a bug, not a feature.
5. **Security** — provider keys, customer PII and claim images never leave the trust boundary unnecessarily.
6. **Human review** — the AI produces a *recommendation*; an authorised agent produces the *decision*.
7. **Reliability** — an AI or network failure degrades to manual review, never to a lost claim.
8. **User experience** — mobile-first capture, live progress, no blocking waits.

> **The system must never fabricate data.** Absence of data is represented explicitly as
> `unavailable` plus a `manual verification required` flag. There is no default price,
> no default market value, and no placeholder damage.

## 2. Technology decisions

| Concern | Choice | Rationale |
| --- | --- | --- |
| API backend | Python 3.12 + FastAPI | Async I/O, Pydantic schema validation on AI output, first-class Celery/Pillow/EXIF/OCR ecosystem |
| ORM / migrations | SQLAlchemy 2.0 (typed) + Alembic | Explicit schema versioning |
| Database | PostgreSQL 16 | Relational integrity for claims; `JSONB` for provider payloads |
| Queue / broker | Redis 7 + Celery | Spec-mandated; long AI + scraping work off the request path |
| Object storage | S3-compatible; MinIO locally | Images must not live in Postgres |
| Realtime | FastAPI WebSocket + Redis pub/sub | Multi-worker fan-out to agent dashboards |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | Mobile camera capture, canvas annotation, SSR dashboards |
| Auth | JWT access (15 min) + rotating refresh (30 d), Argon2id | Short-lived bearer tokens, revocable sessions |

### 2.1 Modular monolith, not microservices

The brief lists `ai-service`, `market-research-service` and `notification-service` as separate
deployables. We implement them as **hard-bounded modules inside one FastAPI application**:

```
app/ai/         app/market/       app/notifications/     app/estimation/
```

Each module exposes a narrow interface (`VisionProvider`, `MarketSource`, `Notifier`,
`DamageEstimator`) and holds no imports from `app/api`. The separation the brief actually
cares about — AI, business logic, data retrieval and UI concerns must not bleed into each
other — is enforced by those interfaces and by an import-linter rule, not by network hops.

This buys the ability to extract any module into its own process later (the interface is
already the wire contract) without paying for service discovery, distributed tracing and
cross-service transactions before the first claim is processed.

## 3. Trust boundaries

```
┌─────────────────────────── PUBLIC ────────────────────────────┐
│ Browser / mobile web                                          │
│  · holds: access token in memory, refresh token in HttpOnly   │
│  · never holds: any AI provider key, storage key, DB password  │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTPS
┌───────────────────────────────▼───────────────────────────────┐
│ FastAPI (API + WebSocket)         PRIVATE                     │
│  · authn/authz, validation, rate limit, audit                 │
│  · presigned GET URLs for images (short TTL, per-request)     │
└───────┬───────────────┬───────────────┬───────────────────────┘
        │               │               │
┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────────────────┐
│ PostgreSQL   │ │ Redis       │ │ Celery workers               │
│ (no images)  │ │ broker+pub  │ │  · vision, OCR, scraping     │
└──────────────┘ └─────────────┘ └──────┬───────────────────────┘
                                        │ egress allow-list
                    ┌───────────────────▼────────────────────┐
                    │ EXTERNAL: Gemini / OpenRouter /        │
                    │ DeepSeek / search API / whitelisted    │
                    │ market sources / geocoder              │
                    └────────────────────────────────────────┘
```

Only the workers and the API server hold provider credentials. The browser receives
presigned, expiring URLs — never bucket credentials.

## 4. Claim processing pipeline

Submission is synchronous and cheap; everything expensive is a Celery chain. The claim row
exists and is durable before any AI call is attempted.

```
POST /claims/{id}/submit  ──►  status=SUBMITTED, 202 returned immediately
                                        │
                                        ▼   (celery chain, per-step status published to WS)
   1  validate_images          image integrity, dimensions, blur score, dedupe hash
   2  extract_metadata         EXIF datetime/GPS/device  → image_metadata
   3  identify_vehicle         multimodal vision         → vehicle candidate + confidence
   4  read_number_plate        detect → crop → OCR       → registration + confidence
   5  process_customer_input   LLM structuring of free text → possible parts, impact area
   6  detect_damage            per-image damage regions  → damaged_parts rows
   7  reconcile_customer_ai    customer vs AI part diff  → agreement report
   8  research_vehicle_value   whitelisted sources       → vehicle_valuations
   9  research_part_prices     whitelisted sources       → part_price_sources
  10  estimate_repair          repair-vs-replace + labour + paint → repair_estimates
  11  reason_assessment        LLM narrative over structured facts only
  12  score_confidence         per-stage → aggregate
  13  analyse_risk             fraud/consistency signals → fraud_signals
  14  decide_manual_review     rule set (§6)
  15  notify_agent             WS + email + SMS fan-out
```

Every step is **idempotent and independently retryable**. A step that cannot produce a
grounded result writes `status=UNAVAILABLE` with a reason and raises the manual-review flag;
it does not halt the chain and does not invent a value.

## 5. AI provider abstraction

```
AIProvider (chat/JSON)              VisionProvider (image+text→JSON)
 ├── GeminiProvider                  ├── GeminiVisionProvider
 ├── OpenRouterProvider              ├── OpenRouterVisionProvider
 ├── DeepSeekProvider                └── MockVisionProvider   (dev/test only)
 └── MockProvider (dev/test only)
```

Selected by `AI_PROVIDER` / `VISION_PROVIDER`; fallback order by `AI_FALLBACK_CHAIN`.

**One prompt per task.** A single mega-call is prohibited — it destroys attributability and
makes failures undebuggable. Prompts live in `app/ai/prompts/` as versioned templates, and
the prompt version is recorded on every `ai_analysis_logs` row alongside provider, model,
request id, latency, token usage and outcome.

Every response is parsed against a Pydantic schema **before** it touches the database. A
schema violation is retried once with a repair instruction, then falls through to the next
provider, then to manual review.

## 6. Manual review triggers

Evaluated after scoring; any single match sets `manual_review_required = true` with reasons.

- any stage confidence below its configured floor (`REVIEW_MIN_*`)
- customer-stated vehicle conflicts with AI/OCR identification
- customer-reported damaged parts differ from AI-detected set
- suspected structural damage, or any `CRITICAL` severity
- estimate exceeds `REVIEW_AMOUNT_THRESHOLD`
- damage-to-value ratio above `REVIEW_RATIO_THRESHOLD`
- fewer images than `MIN_EVIDENCE_IMAGES`, or any image failing quality checks
- no reliable part price, or no reliable market valuation
- any non-`LOW` fraud signal

The damage-to-value ratio is an **assessment signal only**. Total loss is never declared
automatically.

## 7. Market data policy

A source is queried only if it is in the database whitelist (`market_sources`, admin-managed)
**and** its `robots.txt` permits the path. The fetcher enforces per-host rate limits, a
descriptive User-Agent, response caching with TTL, and a hard rule against authentication
walls and CAPTCHA circumvention. Official APIs and licensed datasets take priority over
scraping; a source can be flagged `api` and skip the HTML path entirely.

Retrieved prices are normalised to canonical parts (`FRONT_BUMPER`, …) and tagged
`OEM | AFTERMARKET | USED | REFURBISHED | UNKNOWN`. Incompatible grades are never averaged
into one another. Price confidence is a function of source count, source reliability weight,
vehicle-compatibility strength, inter-source spread and data freshness.

## 8. Repository layout

```
backend/    FastAPI app, Celery workers, Alembic migrations, tests
  app/api/            HTTP + WebSocket layer only
  app/core/           config, security, logging, dependencies
  app/models/         SQLAlchemy models
  app/schemas/        Pydantic request/response + AI output contracts
  app/services/       claim/vehicle/user business logic
  app/ai/             providers, prompts, orchestration
  app/market/         source registry, fetcher, valuation, parts pricing
  app/estimation/     repair-vs-replace, labour, paint, totals
  app/media/          storage client, EXIF, image quality, annotations
  app/fraud/          risk signal detectors
  app/notifications/  websocket hub, email, sms
  app/workers/        celery app + task definitions
frontend/   Next.js app router, components, API client
docker/     Dockerfiles and compose profiles
docs/       this file and its companions
```

## 9. Companion documents

- `docs/DATABASE.md` — table-by-table schema and relationships
- `docs/API.md` — REST + WebSocket contracts
- `docs/AI_PIPELINE.md` — prompts, output schemas, confidence model
- `docs/ROADMAP.md` — the eight delivery phases and their exit criteria
