# Implementation notes

## Design and hardest decisions

PostgreSQL is the source of truth. `users` own `requests`; `episodes` are imported inventory;
`assignments` retain assignment/release history and a partial unique index allows only one active
request per episode. `request_status_history` is append-only. Requests also hold the export job's
status and retry metadata. FastAPI routes authenticate callers, application services enforce
business and ownership rules, and SQLAlchemy repositories implement persistence and analytics.

Three decisions shaped the design:

1. **Serialize assignment and delivery.** Mutations lock the request, then episode rows in sorted
   order; automatic assignment uses `FOR UPDATE SKIP LOCKED`. A partial unique index is a database
   backstop. The shared request lock makes the delivery count check atomic with assignment.
2. **Release on rejection, retain on acceptance.** Rejected deliveries need their episodes back in
   the pool for rework; retaining released assignment rows preserves the audit trail. Accepted data
   remains committed to that client.
3. **Quarantine ambiguous import data; normalize only clear cases.** Import is streaming and
   batched, canonicalizes categorical fields and IDs, parses supported timestamps to UTC, and
   reports every duplicate/rejection. Conflicting duplicate IDs keep the first row and report
   differing fields. Bad-quality episodes are never assignment candidates.

The selected optional stretch is **background work**: a simulated export runs after full assignment,
retries transient failures, records status, and recovers pending or stale work after restart. A
compare-and-set generation fences off stale workers. This is intentionally a small single-process
worker, not a distributed queue; it exports one request package rather than tracking a separate
export status for each episode, which remains future work.

## Simplifications and next steps

The export is simulated, not a real object-store integration. Login throttling is process-local,
tokens have no refresh/revocation list, and the browser stores the access token in `sessionStorage`.
Robot names use a configured allow-list rather than a managed fleet table. Imports run in the API
request, with a 1 GiB cap and bounded memory, rather than in a durable import-job queue.

With two more days I would move imports and exports behind a durable queue/outbox, use shared
rate-limits, move browser auth to secure `httpOnly` cookies with CSRF protection, and add operational
metrics and request IDs. The current public `/health` and `/health/ready` endpoints are intentional
probe endpoints; all business/API operations require authentication except login.

## What went wrong

An end-to-end sign-out test found that the next user could be redirected to the previous user's
deep link. I traced it to preserving the expired-session `from` location on explicit sign-out. I
separated the flows: expired sessions may retain their return path; explicit sign-out clears it. The
real UI/API lifecycle test covers the regression.

## Security

Passwords use Argon2id; verification runs off the event loop, and unknown accounts use a dummy hash
to reduce enumeration by timing. JWT algorithms are pinned; issuer, audience, expiry, issue time,
and subject are required. The database role is re-read on each request, and object-level request
ownership is checked server-side. Inputs are constrained by Pydantic and service-level validation;
SQL is parameterized, analytics grouping/buckets are whitelisted, imports stream under a byte cap,
and page/assignment sizes are bounded. Production refuses the default JWT secret. CORS is
allow-listed; nginx sets CSP and other browser security headers.

The two risks I would prioritize before production are **XSS exposing a sessionStorage bearer token**
(mitigate with a strict CSP, careful output handling, and preferably `httpOnly` cookie sessions) and
**credential stuffing across multiple API replicas** (the current throttle is process-local; use a
shared, rate-limited store and alert on abuse). The public health probes disclose only service
availability and no business data.

## Scale and evidence

Analytics are SQL aggregates, not Python-side row loads. At 5 million episodes, full-range percentile
queries and unindexed groupings will become the first analytics bottleneck; pre-aggregated rollups
and workload-specific indexes are the next step. The measured 1-million-row PostgreSQL run showed
keyset page latency staying effectively flat with cursor depth and import at about 20k rows/s on one
shared CPU core; 5-million figures are extrapolations, not measurements. A 5-million-row import
would take several minutes in one HTTP request, so it should become a tracked background job.

At 10× users, process-local throttling and database connection capacity are early limits: centralize
rate limits, monitor pool saturation, and scale API workers against measured load. At 100× episodes,
index/storage and analytics/import write costs dominate; normalize repeated task/robot strings,
benchmark indexes against ingestion, consider time partitioning, and roll up analytics. Do not
assume the 1-million measurements prove production capacity.

The test suite uses real PostgreSQL for locking, constraints, migrations, imports, and analytics;
frontend lifecycle tests drive the real UI against the API. Compose orders database readiness,
migrations, seeding, API, and frontend startup. CI runs backend tests/lint and frontend build/lifecycle
checks. `/health` is liveness; `/health/ready` checks database connectivity.

**AI tooling:** I used the Copilot SDK in VS Code for repository analysis, implementation assistance,
and test/documentation review. I reviewed the changes and can explain the behavior and trade-offs.
