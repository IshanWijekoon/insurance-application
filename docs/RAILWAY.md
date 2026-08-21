# Deploying on Railway

This guide walks through deploying the monorepo as three services (**api**, **worker**, **web**) plus managed **PostgreSQL** and **Redis**, with claim images in **Cloudflare R2** (or any S3-compatible store).

Do **not** use MinIO or local disk on Railway — the filesystem is ephemeral and is not shared between api and worker.

## Architecture

```
Browser ──► web (Next.js) ──► api (FastAPI) ──► Postgres
                │                    │              Redis
                │                    └──► R2 / S3
                │
                └──► api (WebSocket + REST via NEXT_PUBLIC_API_URL)

worker (Celery) ──► Postgres, Redis, R2, AI providers
```

| Service | Root directory | Start |
| --- | --- | --- |
| Postgres | Railway plugin | managed |
| Redis | Railway plugin | managed |
| **api** | `backend/` | `uvicorn` on `$PORT` (Dockerfile default) |
| **worker** | `backend/` | `celery -A app.workers.celery_app worker --loglevel=info` |
| **web** | `frontend/` | `node server.js` (standalone) |

Celery beat is optional (notification retries, robots refresh). Skip it for the first deploy.

**Important:** If Redis is running but the worker is not, claim jobs sit in the queue forever. Always deploy **api + worker** together, or omit Redis and rely on the in-process thread fallback.

---

## One-time prerequisites (before first production boot)

Production startup refuses to start unless these are set (`validate_for_environment` in `backend/app/core/config.py`).

### 1. JWT secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set as `JWT_SECRET` (≥ 32 characters).

### 2. AI provider

`AI_PROVIDER` and `VISION_PROVIDER` cannot be `mock` in production.

Recommended starter:

1. Create a key at [Google AI Studio](https://aistudio.google.com/apikey)
2. Set:
   - `AI_PROVIDER=gemini`
   - `VISION_PROVIDER=gemini`
   - `GEMINI_API_KEY=...`

Alternatives: `openrouter` + `OPENROUTER_API_KEY`, or `deepseek` + `DEEPSEEK_API_KEY`.

### 3. Object storage (Cloudflare R2 or AWS S3)

1. Create a private bucket (e.g. `claim-images`)
2. Create an API access key + secret
3. Set:

| Variable | Example (R2) |
| --- | --- |
| `STORAGE_BACKEND` | `s3` |
| `STORAGE_ENDPOINT` | `https://<accountid>.r2.cloudflarestorage.com` |
| `STORAGE_PUBLIC_ENDPOINT` | same as endpoint, or a custom public/r2.dev host |
| `STORAGE_ACCESS_KEY` | R2 access key id |
| `STORAGE_SECRET_KEY` | R2 secret |
| `STORAGE_BUCKET` | `claim-images` |
| `STORAGE_REGION` | `auto` (R2) or e.g. `us-east-1` (AWS) |

### 4. Optional: live market prices

Without a search API, part prices and valuations stay `UNAVAILABLE` and claims route to manual review (by design).

- `SEARCH_PROVIDER=serper` (or `tavily` / `brave`) + matching `SERPER_API_KEY` / `TAVILY_API_KEY` / `BRAVE_API_KEY`

Email/SMS and maps are also optional and not required to boot.

---

## Create the Railway project

1. Push this repository to GitHub.
2. In Railway: **New Project → Deploy from GitHub**.
3. Add **PostgreSQL** and **Redis** plugins in the same project.
4. Create service **api**:
   - Root directory: `backend`
   - Builder: Dockerfile (`backend/Dockerfile` / `railway.toml`)
5. Create service **worker**:
   - Same root / Dockerfile as api
   - **Custom start command:**  
     `celery -A app.workers.celery_app worker --loglevel=info`
   - Set `RUN_MIGRATIONS=false`
6. Create service **web**:
   - Root directory: `frontend`
   - Builder: Dockerfile (`frontend/Dockerfile`)
7. Share / reference variables from api → worker (same secrets and plugin URLs).

Suggested resources: **api** and **worker** at least **1 GB RAM** (OpenCV + vision). Web can stay on the smallest plan.

Generate a **public domain** on both **api** and **web** in the Railway service settings.

---

## Environment variables

### api + worker

Use Railway variable references for plugins (do not paste passwords by hand).

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (code rewrites `postgres://` → `postgresql+psycopg://`) |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `CELERY_BROKER_URL` | optional — defaults to `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | optional — defaults to `REDIS_URL` |
| `JWT_SECRET` | generated secret |
| `CORS_ORIGINS` | `https://<web-service>.up.railway.app` (update after web has a domain) |
| `AI_PROVIDER` / `VISION_PROVIDER` | e.g. `gemini` |
| `GEMINI_API_KEY` | your key |
| `STORAGE_*` | from R2 / S3 table above |
| `RUN_MIGRATIONS` | `true` on **api only**; `false` on **worker** |
| `RUN_SEED` | `false` (or `true` once for demo logins, then turn off) |

### web (required at **build** time)

`NEXT_PUBLIC_*` values are inlined into the client bundle during `next build`.

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://<api-service>.up.railway.app` (no trailing slash) |

After the web service exists:

1. Set `CORS_ORIGINS` on **api** → redeploy **api**
2. Set `NEXT_PUBLIC_API_URL` on **web** → redeploy **web** (rebuild required)

---

## Deploy order

1. Postgres + Redis plugins online
2. Deploy **api** (runs Alembic migrations on start)
3. Deploy **worker** with the same env (except `RUN_MIGRATIONS=false`)
4. Deploy **web** with `NEXT_PUBLIC_API_URL` pointing at the api public URL
5. Fix `CORS_ORIGINS` to the web public URL and redeploy api if needed

---

## After it is live

1. Open `https://<api>/ready` — JSON with DB health. Swagger: `https://<api>/docs`.
2. Open the web URL → `/login`.
   - If you used `RUN_SEED=true`, demo accounts are in the README (`ChangeMe123!`). Change those passwords immediately, or turn seed off and register a real customer; create agent/admin via admin UI or a one-off seed.
3. Submit a test claim with 2+ photos. Worker logs should show the pipeline. The processing page polls every 2s even if WebSocket is flaky.
4. Confirm a claim image loads (presigned R2/S3 URL). If images 403, fix `STORAGE_PUBLIC_ENDPOINT`.
5. Optional: attach a custom domain on **web**, add that origin to `CORS_ORIGINS`, redeploy api.

### Demo seed accounts (only if `RUN_SEED=true`)

| Portal | Role | Email | Password |
| --- | --- | --- | --- |
| Client | Customer | `customer@insure.local` | `ChangeMe123!` |
| Agent | Agent | `agent@insure.local` | `ChangeMe123!` |
| Admin | Admin | `admin@insure.local` | `ChangeMe123!` |

---

## Local vs Railway

| Concern | Local (`docker compose`) | Railway |
| --- | --- | --- |
| Frontend image | `docker/frontend.Dockerfile` (`next dev`) | `frontend/Dockerfile` (standalone) |
| Backend image | `backend/Dockerfile` | same |
| API URL in browser | relative `/api` via Next rewrite | `NEXT_PUBLIC_API_URL` |
| Storage | MinIO | R2 / S3 |
| Seed | `RUN_SEED=true` in compose | opt-in only |

---

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Api exits on start with config errors | Missing `JWT_SECRET`, mock AI, or storage keys with `APP_ENV=production` |
| Claims stuck in queued / processing | Worker not deployed, or Redis URL wrong |
| Login works but refresh fails | `CORS_ORIGINS` missing web origin, or `NEXT_PUBLIC_API_URL` wrong |
| Images broken | Wrong `STORAGE_PUBLIC_ENDPOINT` / bucket policy |
| Web build has empty API calls to relative paths | `NEXT_PUBLIC_API_URL` not set at **build** time — rebuild after setting it |
