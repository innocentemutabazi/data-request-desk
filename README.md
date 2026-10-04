# Dataset Request Desk

Clients request robot-demonstration datasets; operators match recorded episodes to each request and
deliver them; clients accept or reject. Built to stay correct under concurrency and fast at millions of
episodes.

**Stack:** FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 · Pydantic v2 · Pytest ·
React 18 · Vite · TypeScript · Tailwind · TanStack Query

> Design rationale, benchmarks and trade-offs are in **[NOTES.md](NOTES.md)**. Start there for the
> locking model, pagination at scale, data-cleaning decisions and security.

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env and set a local POSTGRES_PASSWORD before starting.
docker compose up --build
```

|                    | URL                        |
| ------------------ | -------------------------- |
| App                | http://localhost:8080      |
| API docs (Swagger) | http://localhost:8000/docs |

Startup is ordered by real dependencies: `db` (healthy) → `migrate` (`alembic upgrade head`) →
`seed` (users from `users.json`, episodes from `episodes.csv`) → `backend` (healthy) → `frontend`.
Re-running is safe: migrations and the seed are idempotent.

**Demo accounts** (seeded; one-click buttons on the login page):

| Role     | Email                                           | Password    |
| -------- | ----------------------------------------------- | ----------- |
| Client   | `client-a@example.com` / `client-b@example.com` | `client123` |
| Operator | `ops1@example.com` / `ops2@example.com`         | `ops123`    |
| Admin    | `admin@example.com`                             | `admin123`  |

**Try it:** sign in as a client → _New request_ → sign out → sign in as an operator → open the request →
_Start work_ → _Auto-assign_ (watch the export toast) → _Mark delivered_ → sign back in as the client → _Accept_.
To see the failure toast + retry, run with `EXPORT_FAILURE_RATE=1 docker compose up`.

## Local development (no Docker)

```bash
# 1. database
createdb desk && createdb desk_test        # configure your local PostgreSQL credentials as needed

# 2. backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://desk:desk@localhost:5432/desk
alembic upgrade head
python -m scripts.seed                      # users.json + episodes.csv  (SEED_DIR defaults to ../seed)
uvicorn app.main:app --reload               # http://localhost:8000/docs

# 3. frontend (proxies /api → :8000)
cd ../frontend
npm ci && npm run dev                       # http://localhost:5173
```

## Tests

```bash
# Backend: full test suite against REAL PostgreSQL (refuses to run unless the DB name ends in `_test`)
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://desk:desk@localhost:5432/desk_test pytest -q

# Frontend: strict typecheck + production build
cd frontend && npm run build

# Frontend end-to-end (mounts the real app in jsdom, drives it against a RUNNING backend)
cd backend && uvicorn app.main:app --port 8000 &     # EXPORT_MIN_SECONDS=0.3 EXPORT_MAX_SECONDS=0.6 for speed
cd frontend && E2E_API_URL=http://localhost:8000 npm test
#   E2E_EXPECT=failure with EXPORT_FAILURE_RATE=1 on the backend exercises the failed-export path
```

What the backend suite covers: RBAC matrix and object-level isolation · exhaustive state-machine table
(5×5×3) · concurrency (row locks, `SKIP LOCKED`, constraint safety net, lock timeout) · import cleaning,
idempotency and concurrent imports · keyset pagination (ties, tampering, index usage) · analytics values ·
background-export claim/retry/crash recovery · migration ⇄ model drift.

## Architecture

```
backend/app
├─ domain/          pure rules: enums, state machine, errors, criteria, SQLAlchemy entities
├─ application/     use cases: services (request, import, export, analytics…), DTOs, ports (Protocols),
│                   CSV cleaning (pure functions), keyset-cursor helpers
├─ infrastructure/  PostgreSQL repositories + Unit of Work, JWT, Argon2, export simulator
├─ interfaces/api/  FastAPI routers, Pydantic schemas, RBAC dependencies, error envelope
└─ composition.py   the only place that wires ports to concrete implementations

frontend/src
├─ app/             shell, router, providers
├─ shared/          api client, UI primitives (Button, Dialog, Skeleton…), toast system
└─ features/        auth · requests · episodes · exports · analytics · imports · inventory
                    (each owns its types / api / hooks / components / pages)
```

Dependency rule: `domain` ← `application` ← `infrastructure` / `interfaces`. Frontend features may use
another feature's barrel or its leaf `api`/`types`, never its internals; there are no import cycles.

## API at a glance

| Endpoint                                                                   | Who                             | Notes                                                         |
| -------------------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------- |
| `POST /auth/login` · `GET /auth/me`                                        | all                             | OAuth2 password form → JWT                                    |
| `POST /requests`                                                           | client                          |                                                               |
| `GET /requests` · `/requests/summary` · `/requests/{id}`                   | all (clients: own only)         | keyset-paginated, newest first                                |
| `POST /requests/{id}/start` · `/deliver`                                   | operator, admin                 | `deliver` needs `assigned ≥ requested`                        |
| `POST /requests/{id}/rework`                                               | operator, admin                 | moves a rejected request back to `in_progress`                |
| `POST /requests/{id}/accept` · `/reject`                                   | owning client only              |                                                               |
| `POST /requests/{id}/assignments` · `/assignments/auto`                    | operator, admin                 | pessimistic locks · `SKIP LOCKED`; arms the background export |
| `GET /requests/{id}/assignments` · `/candidates`                           | staff (clients: after delivery) | keyset-paginated                                              |
| `POST /requests/{id}/export/retry`                                         | operator, admin                 | only for a failed export                                      |
| `GET/POST /users` · `PATCH /users/{id}`                                    | admin                           | create, activate/deactivate, and change roles                 |
| `POST /episodes/import`                                                    | operator, admin                 | multipart CSV; idempotent; returns a full cleaning report     |
| `GET /episodes`                                                            | staff                           | filters + keyset pagination                                   |
| `GET /analytics/overview` · `/episodes/breakdown` · `/episodes/timeseries` | staff                           | pure SQL aggregates (`percentile_cont`); use `recorded_from`/`recorded_to` consistently; add `per_robot=true` for daily robot counts |
| `GET /catalog/tasks`                                                       | all                             | cached task list for the request form                         |
| `GET /health` · `/health/ready`                                            | public                          | liveness / readiness                                          |

Errors share one envelope: `{"error": {"code", "message", "details"}}`. Every request emits a JSON log
record with method, path, status, duration, and authenticated user ID. Request status changes are stored in
`request_status_history` with actor, timestamp, previous status, new status, and decision reason.

Requests include a delivery `deadline` (date) and optional operator-facing `notes`. Analytics range
parameters use inclusive `recorded_from` and exclusive `recorded_to` timestamps; the UI converts its
date pickers to that boundary convention.

## Configuration

All via environment variables (see `.env.example`, `backend/app/core/config.py`):
`DATABASE_URL`, `JWT_SECRET` (≥ 32 chars; the app refuses the default when `ENVIRONMENT=production`),
`CORS_ORIGINS`, `KNOWN_ROBOTS`, `IMPORT_BATCH_SIZE`, `DB_LOCK_TIMEOUT_MS`, `EXPORT_MIN_SECONDS`,
`EXPORT_MAX_SECONDS`, `EXPORT_FAILURE_RATE`, `EXPORT_MAX_ATTEMPTS`, `IMPORT_MAX_FUTURE_SKEW_HOURS`, …

## Seed data

`seed/` holds the provided `users.json`, `episodes.csv` (deliberately dirty), the generator and its README.
Generate a large file to try the scale behaviour:

```bash
python seed/generate_episodes.py 1000000 > /tmp/big.csv
cd backend && python -m scripts.bench_import /tmp/big.csv     # streaming import: constant memory
```
