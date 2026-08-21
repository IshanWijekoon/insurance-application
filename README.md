# AI Motor Insurance Claim Assessment

A production-oriented web application for **preliminary** motor-insurance damage assessment.

Customers upload photographs, optionally describe the accident and damaged parts, and mark damage on images. The backend combines vision analysis, number-plate OCR, EXIF/GPS evidence, customer input, and **whitelisted web sources** for part prices and vehicle market value. An insurance agent always makes the final decision.

> The AI never represents its estimate as a guaranteed settlement.

## What was built

| Layer | Implementation |
| --- | --- |
| API | FastAPI, JWT + refresh cookies, RBAC (customer / agent / admin) |
| Data | PostgreSQL, SQLAlchemy 2, Alembic |
| Images | MinIO / S3-compatible object storage, EXIF, quality checks, annotations |
| Queue | Redis + Celery (15-stage assessment pipeline) |
| AI | Gemini / OpenRouter / DeepSeek providers, mock provider for local use |
| Market | `PartsPricingResearchService` + `VehicleValuationService` with source whitelist, robots.txt, no fabricated prices |
| Estimation | Deterministic repair-vs-replace rules, labour/paint rates, auditable `basis` strings |
| Realtime | WebSocket over Redis pub/sub + polling fallback |
| Web | Next.js 15, TypeScript, Tailwind, mobile claim wizard |

## Run locally (Docker)

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux

docker compose up --build
```

- Client portal: http://localhost:3000/login
- Agent portal: http://localhost:3000/login/agent
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001

### Demo accounts (password `ChangeMe123!`)

| Portal | Role | Email |
| --- | --- | --- |
| Client | Customer | customer@insure.local |
| Agent | Agent | agent@insure.local |
| Admin | Admin | admin@insure.local |

The seeded customer already has a 2018 Toyota Prius (`WP ABC-1234`).

## Deploy on Railway

See **[docs/RAILWAY.md](docs/RAILWAY.md)** for the full checklist: Postgres + Redis plugins, api / worker / web services, Cloudflare R2 (or S3), JWT and AI keys, CORS, and post-deploy verification.

Summary: production needs `APP_ENV=production`, a strong `JWT_SECRET`, real `AI_PROVIDER` / `VISION_PROVIDER` + API keys, S3-compatible `STORAGE_*` credentials, and `NEXT_PUBLIC_API_URL` on the web service pointing at the public API URL.

## Run without Docker

1. Start PostgreSQL 16, Redis 7, and MinIO.
2. `cd backend && python -m venv ../.venv && ..\.venv\Scripts\activate`
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and point `DATABASE_URL` / `REDIS_URL` / storage at your services.
5. `alembic upgrade head && python -m scripts.seed`
6. `uvicorn app.main:app --reload --port 8000`
7. `celery -A app.workers.celery_app worker --loglevel=info`
8. `cd ../frontend && npm install && npm run dev`

## Tests

```bash
cd backend
pytest
```

## AI providers

Set `AI_PROVIDER` / `VISION_PROVIDER` to `gemini`, `openrouter`, or `deepseek`, and supply the matching API key. Leave them as `mock` for local development — the mock never invents prices; market research reports `UNAVAILABLE` unless real sources return listings.

`SEARCH_PROVIDER` (`serper` / `tavily` / `brave`) is required for live web pricing. With `SEARCH_PROVIDER=none`, part prices and valuations are explicitly **unavailable** and the claim is routed to manual review.

## Principles

Accuracy → Evidence → Explainability → Named data sources → Security → Human review → Reliability → UX.

The system assists the assessor. It does not replace the authorised insurance decision-maker.
