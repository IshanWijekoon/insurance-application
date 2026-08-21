# Delivery roadmap

Each phase ends in a state you can run and demonstrate. Nothing is stubbed with fake
results — a capability that is not built yet reports itself as unavailable and routes to
manual review, which is the same behaviour it will have in production when a provider fails.

## Phase 1 — Foundation
Docker compose (Postgres, Redis, MinIO, API, worker, web), configuration and secrets
handling, Alembic baseline covering every table in `DATABASE.md`, Argon2 password hashing,
JWT access + rotating refresh, RBAC dependency, users/customers/agents, vehicles, policies,
claim CRUD with status events, MinIO client with presigned URLs, seed script.
**Exit:** a customer can register, add a vehicle and create a draft claim; an agent can see it.

## Phase 2 — Claim evidence
Multipart upload with type/size/dimension validation, SHA-256 + perceptual hashing, blur and
exposure scoring, EXIF extraction with explicit `has_exif`, GPS resolution chain
(EXIF → device → manual map pick) with recorded `source`, annotation storage and overlay
rendering, customer damage report with canonical part checkboxes and free text, the
mobile capture wizard with guidance screens.
**Exit:** a complete, submittable evidence package with honest metadata provenance.

## Phase 3 — AI vision
`AIProvider` / `VisionProvider` abstractions, Gemini + OpenRouter + DeepSeek + mock
implementations, versioned prompt templates, Pydantic validation with repair-retry, fallback
chain, vehicle identification, plate detection → crop → OCR with customer correction,
per-image damage detection, `ai_analysis_logs`.
**Exit:** real images produce validated, attributed damage findings with confidence.

## Phase 4 — Market intelligence
`market_sources` whitelist with admin CRUD, robots.txt checker, rate-limited cached fetcher,
search-provider adapter, listing parsers, part-name normalisation to canonical codes, grade
tagging (OEM/aftermarket/used/refurbished), multi-source aggregation into ranges, price
confidence scoring, vehicle valuation service.
**Exit:** part prices and vehicle values with source rows and timestamps, or an explicit
`UNAVAILABLE` — never a fabricated figure.

## Phase 5 — Estimation
Repair-vs-replace rules keyed on part × damage type × severity, labour hours × configurable
rate, paint panels × rate, materials, per-line and total ranges, damage-to-value ratio,
`basis` strings for every line.
**Exit:** an expandable, auditable estimate where each number traces to its inputs.

## Phase 6 — AI claim agent
Celery chain wiring all stages, customer-vs-AI reconciliation, fraud/risk detectors,
confidence aggregation, manual-review rule set, claim summary generation.
**Exit:** submit a claim and get a complete assessment end to end.

## Phase 7 — Real-time insurance operations
WebSocket hub over Redis pub/sub, per-stage progress frames, agent queue and claim detail,
assignment, notes, AI correction with retained original, request-more-information loop,
decision workflow, email/SMS fan-out with retry, notification centre.
**Exit:** an agent is notified within seconds of submission and can work the claim to a decision.

## Phase 8 — Production hardening
Rate limiting, security headers, CORS, CSRF on cookie flows, audit logging on every mutation,
retention policy jobs, structured logging with request ids, health and readiness probes,
Prometheus metrics, pytest suite (unit + integration + pipeline with mock providers),
Playwright smoke tests, production compose and deployment notes.
**Exit:** deployable with tests green and no secret reachable from the browser.

## Cross-cutting rules

- No hard-coded AI results anywhere outside `tests/fixtures` and the mock provider.
- Every money value carries a currency and, if derived from the web, a source and a timestamp.
- Every mutation writes an audit row.
- Every AI-facing schema is validated before persistence.
- Manual review is the default when confidence or evidence is insufficient.
