# API contract

Base path `/api/v1`. JSON in, JSON out. Bearer access token in `Authorization`, refresh token
in an HttpOnly cookie. All list endpoints paginate with `?page=&page_size=` and return
`{items, total, page, page_size}`.

## Conventions

**Errors** use a single envelope so the frontend has one code path:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": { "field": "…" } } }
```

`401 UNAUTHENTICATED` · `403 FORBIDDEN` · `404 NOT_FOUND` · `409 CONFLICT` ·
`422 VALIDATION_ERROR` · `429 RATE_LIMITED` · `503 PROVIDER_UNAVAILABLE`.

**Unavailable data** is never `0` or `null` alone. Any economic value is returned as:

```json
{ "status": "UNAVAILABLE", "reason": "No whitelisted source returned a compatible listing",
  "manual_verification_required": true }
```

or as `{ "status": "AVAILABLE", "min": 110000, "max": 145000, "currency": "LKR",
"confidence": 0.82, "sources": [...] }`.

## Auth

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/auth/register` | customer self-registration only; agents/admins are provisioned |
| POST | `/auth/login` | returns access token + sets refresh cookie |
| POST | `/auth/refresh` | rotates the refresh token family |
| POST | `/auth/logout` | revokes the current session |
| GET | `/auth/me` | current user with role-specific profile |

## Customer

| Method | Path | Notes |
| --- | --- | --- |
| GET/PATCH | `/customers/me` | profile |
| GET/POST | `/vehicles` | list / create; every descriptive field optional |
| GET/PATCH/DELETE | `/vehicles/{id}` | soft delete |
| GET/POST | `/policies` | link a policy to a vehicle |

## Claims — customer

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/claims` | creates a `DRAFT`; vehicle optional at this point |
| GET | `/claims` | own claims, filterable by status |
| GET | `/claims/{id}` | full detail incl. assessment when complete |
| PATCH | `/claims/{id}` | edit draft fields (descriptions, accident time) |
| POST | `/claims/{id}/images` | multipart, ≤ `MAX_IMAGE_MB` each, ≤ `MAX_IMAGES` per claim |
| DELETE | `/claims/{id}/images/{imageId}` | draft only |
| POST | `/claims/{id}/images/{imageId}/annotations` | annotation regions + optional rendered overlay |
| POST | `/claims/{id}/damage-report` | selected canonical parts + free text |
| POST | `/claims/{id}/location` | device GPS or map-selected point, with explicit `source` |
| POST | `/claims/{id}/confirm-registration` | customer corrects low-confidence OCR |
| POST | `/claims/{id}/submit` | validates completeness, enqueues pipeline, returns `202` |
| GET | `/claims/{id}/status` | lightweight poll fallback for the WebSocket |

## Claims — analysis read models

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/claims/{id}/assessment` | vehicle ID, damaged parts, confidence, review flags |
| GET | `/claims/{id}/estimate` | totals plus per-line breakdown and `basis` strings |
| GET | `/claims/{id}/market-data` | vehicle valuation with every contributing source |
| GET | `/claims/{id}/part-prices` | per part: range, median, confidence, source rows |
| GET | `/claims/{id}/reconciliation` | customer-reported vs AI-detected part diff |
| GET | `/claims/{id}/timeline` | status events, notes, agent actions |
| POST | `/claims/{id}/analyze` | agent/admin re-run of the pipeline (audited) |

## Agent

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/agent/dashboard` | counters: total, new, under review, high priority, approved, rejected, pending info |
| GET | `/agent/claims` | queue with filters: status, priority, region, amount band |
| POST | `/claims/{id}/assign` | self-assign or admin-assign |
| POST | `/claims/{id}/notes` | internal or customer-visible |
| PATCH | `/claims/{id}/assessment` | correct AI output; original is retained, change audited |
| PATCH | `/claims/{id}/estimate` | agent-adjusted range, stored beside the AI range |
| POST | `/claims/{id}/request-information` | sets `MORE_INFORMATION_REQUIRED`, notifies customer |
| POST | `/claims/{id}/decision` | `APPROVED` / `REJECTED` / `FURTHER_ASSESSMENT` + reason |

An agent correction never overwrites the AI record. `damage_assessments` keeps the model
output; agent edits land in adjustment columns and `audit_logs`. Both are shown side by side.

## Admin

| Method | Path | Notes |
| --- | --- | --- |
| GET/POST/PATCH | `/admin/users` | manage customers and agents |
| GET/POST/PATCH/DELETE | `/admin/market-sources` | the fetch whitelist |
| GET/PATCH | `/admin/ai-config` | active provider, fallback chain, confidence floors |
| GET/PATCH | `/admin/pricing-config` | labour rate, paint rates, severity multipliers |
| GET | `/admin/analytics` | volumes, cycle time, AI-vs-agent deltas |
| GET | `/admin/audit-logs` | filterable, read-only |

Keys are write-only: `PATCH /admin/ai-config` accepts a key, `GET` returns
`{"gemini": {"configured": true}}` and never the value.

## Notifications

| Method | Path |
| --- | --- |
| GET | `/notifications` |
| POST | `/notifications/{id}/read` |
| POST | `/notifications/read-all` |

## WebSocket

`GET /api/v1/ws?token=<access token>` — token is validated on connect, then the socket joins
role-scoped rooms (`user:{id}`, and `agents` for agent/admin).

Server → client frames:

```json
{ "type": "claim.progress", "claim_id": "…", "stage": "DETECTING_DAMAGE",
  "step": 6, "of": 15, "status": "OK", "message": "Detecting damage…" }

{ "type": "claim.completed", "claim_id": "…", "manual_review_required": true }

{ "type": "claim.new", "claim_id": "…", "claim_number": "CLM-2026-000123",
  "vehicle": "Toyota Prius 2018", "estimate": {"min": 110000, "max": 145000,
  "currency": "LKR"}, "location": "Colombo", "images": 4 }

{ "type": "notification", "id": "…", "title": "…", "body": "…" }
```

The customer's progress UI is driven entirely by `claim.progress`; `GET /claims/{id}/status`
exists so a dropped socket degrades to polling rather than a frozen screen.
