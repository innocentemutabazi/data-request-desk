# NOTES

Design decisions, trade-offs and evidence for the Dataset Request Desk. Every number below was
measured on the code in this repo (PostgreSQL 16, one shared CPU core, no tuning) unless it is
explicitly labelled an extrapolation.

- [1. Handling race conditions with locks](#1-handling-race-conditions-with-locks)
- [2. Cursor pagination for 5M rows](#2-cursor-pagination-for-5m-rows)
- [3. Data cleaning decisions](#3-data-cleaning-decisions)
- [4. Security](#4-security)
- [5. Other design decisions](#5-other-design-decisions)
- [6. What was verified, and what was not](#6-what-was-verified-and-what-was-not)
- [7. Known limitations / what I'd do next](#7-known-limitations--what-id-do-next)

---

## 1. Handling race conditions with locks

### The problem

Two operators can try to assign the same episode at the same moment. A naive
`SELECT … WHERE NOT assigned` followed by `INSERT` has a window between the check and the write in
which both operators see "available", and both write. The same family of race exists for state
transitions (two operators both pressing _Start_), for _deliver_ racing a final _assign_, and for a
client double-clicking _accept_ and _reject_.

### Two independent layers

**Layer 1: pessimistic locks (good behaviour).** Every mutation runs in one transaction following
the same protocol (see `application/services/request_service.py`):

```
1. SELECT … FROM requests WHERE id = :id            FOR UPDATE     -- serialise everything touching this request
2. re-read status / counts *after* the lock is held                -- decide on committed truth, not a stale read
3. SELECT … FROM episodes WHERE episode_id IN (…)   ORDER BY episode_id  FOR UPDATE
4. re-check availability with a fresh statement                    -- READ COMMITTED: new statement ⇒ new snapshot
5. INSERT assignments; COMMIT                                      -- locks released
```

- **No deadlocks by construction.** The lock order is always _request row → episode rows sorted by
  primary key_. Two operators locking overlapping episode sets queue up in the same order instead
  of each holding what the other wants.
- **Auto-assign uses `FOR UPDATE SKIP LOCKED`.** Operators filling different requests from the same
  pool get _disjoint_ episodes immediately instead of waiting on one another. It queries one
  quality tier at a time (good → usable → bad), each an equality probe on the
  `(task_name, quality, recorded_at)` index walked backwards, so "best and newest first" needs no sort
  over the candidate set. Because a `SKIP LOCKED` scan can start before another transaction's commit
  and still lock a row that transaction just assigned, the chosen rows are re-verified with a
  fresh query before insert (and the fill loop tops up, max 3 rounds).
- **Fail fast, don't hang.** `lock_timeout` is 5 s (configurable). A stuck lock-holder surfaces as
  HTTP `503` + `Retry-After` (`ResourceBusy`) instead of silently queueing every other operator.
  Deadlock (`40P01`) and serialization failure (`40001`) map to the same response.

**Layer 2: the database constraint (correctness).** `assignments` has a _partial unique index_:

```sql
CREATE UNIQUE INDEX uq_assignments_active_episode ON assignments (episode_id) WHERE released_at IS NULL;
```

"An episode belongs to only one request **at a time**" is therefore enforced by PostgreSQL itself.
If a future code path forgets to lock, the second claim is refused. It is a _partial_ index (not a
plain unique column) because a rejected request **releases** its episodes: the row is kept for audit
with `released_at` stamped, and the episode may be assigned again. A plain `UNIQUE(episode_id)` would
force deleting history.

**Why both?** Locks alone are only as good as every caller's discipline. The constraint alone makes
losers fail with an opaque integrity error after wasted work. Together: losers get a precise,
actionable `409 episodes_already_assigned` listing exactly which ids were taken, and nothing can ever
be double-assigned.

### State transitions and the delivery guard

The lifecycle is data (`domain/state_machine.py`), not scattered `if`s:

```
submitted ─▶ in_progress ─▶ delivered ─▶ accepted
                   ▲                    └──▶ rejected
                   └────────────────────────
```

Operators/admins drive the first two moves; **only the owning client** accepts/rejects. Two distinct
failure modes get distinct statuses: wrong _role_ for the destination → `403`; right role, wrong
_state_ → `409`. A client probing another tenant's request gets `404`, not `403`, so ids can't be used to
discover what exists.

`deliver` requires `assigned_episodes >= episodes_requested`. The count is read **while holding the
request row lock**, and `assign` takes the same lock first, so the count cannot change between the check
and the status update. (I additionally cap assignment at `episodes_requested`, so `>=` is in practice `==`;
the `>=` check is kept exactly as specified.)

### Evidence: the tests actually bite

A concurrency test that passes proves nothing unless it _fails_ when the protection is removed. So I
mutation-tested the lock tests:

| Mutation                                      | Result                                                                                                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Remove `FOR UPDATE` from episode locking      | **8 tests fail** (the lock-blocking test + 7 of 8 race rounds; round 0 survived by lucky interleaving, which is why each race is repeated) |
| Remove `FOR UPDATE` from the request-row lock | **5 tests fail** (concurrent starts, accept-vs-reject, export-armed-once, deliver serialisation, lock timeout)                             |

The suite tests the layers _separately_ so neither masks the other:
`test_row_lock_on_episodes_really_blocks_a_second_assigner` holds a row lock in one transaction and
asserts a second assigner genuinely waits, then proceeds. The `uq_assignments_active_episode` tests
bypass the services entirely and write rows directly.

### Background export: safe status tracking

`BackgroundTasks` runs after assignment completes the request; it simulates a 2–5 s export that fails
20% of the time, with up to 3 attempts and jittered exponential backoff. Status lives on the request
(`export_status`, `export_attempts`, `export_error`, `export_updated_at`):

- Every transition is a single `UPDATE … WHERE export_status = <expected> AND export_generation = <owner> RETURNING` (compare-and-set with fencing).
  Five workers racing for one export: **exactly one** runs it (tested).
- **No transaction is open during the "work"**: only short transactions between sleeps, so exports
  can't pin connections or row locks (tested via `pg_stat_activity`).
- `export_status` flips to `pending` **in the same transaction** as the final assignment, so the intent
  is durable even if the process dies before the background task is scheduled.
- A `running` export whose heartbeat is older than 120 s is presumed orphaned and can be reclaimed; a
  fresh heartbeat is respected (tested both ways). Each claim increments `export_generation`, so a
  stale worker that eventually wakes up cannot overwrite the replacement worker's result.
- The export is armed when the request becomes **fully assigned**, once. Exporting after every partial
  assignment would package incomplete datasets. A failed export does **not** block delivery.

---

## 2. Cursor pagination for 5M rows

`OFFSET n` makes PostgreSQL produce and discard `n` rows, so page _k_ costs O(k·pageSize). It is also
unstable under writes: a row inserted ahead of the window shifts every later page, producing duplicates
and gaps. Keyset ("seek") pagination instead says _"give me the rows after the last one I saw"_:

```sql
WHERE (recorded_at, episode_id) < (:last_recorded_at, :last_episode_id)
ORDER BY recorded_at DESC, episode_id DESC
LIMIT 51                                   -- limit + 1 → we know whether another page exists
```

Row-value comparison maps directly onto a B-tree range scan; cost is O(log n + pageSize) **independent of
depth**. `episode_id` is the tie-breaker, so identical timestamps neither skip nor repeat rows (tested with
wholesale timestamp ties: 105 rows → 11 pages, no gaps/duplicates; separately, page sizes 1/7/50/200 all return identical results).

### Measured at 1,000,000 episodes

Warm-cache medians of 4 consecutive `EXPLAIN (ANALYZE)` runs:

| Query                                                               | Keyset                                                    | `OFFSET` equivalent                                                 |
| ------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| task + quality, **first** page                                      | **0.19 ms**                                               | n/a                                                                 |
| task + quality, deep page (≈ row 80,000 of the filtered set)        | **0.27 ms**                                               | **~75–90 ms** (plan degrades to a bitmap scan + on-disk merge sort) |
| global feed, deep page (row 500,000)                                | **0.27 ms**                                               | **~250–300 ms** (≈ 1000× slower; grows linearly with depth)         |
| `min_quality` (`quality IN (good, usable)`) first page              | **0.1 ms**: 60 buffers, only 6 rows removed by the filter | n/a                                                                 |
| auto-assign claim (`NOT EXISTS … FOR UPDATE SKIP LOCKED`, LIMIT 50) | **0.3 ms**                                                | n/a                                                                 |

**Cache caveat (learned the hard way):** my first readings were wildly off (a 0.37 s `IN` query, a 2.1 s
`OFFSET`) because they were cold-cache first touches on this sandbox's slow virtual disk. I re-measured
with repeats rather than quote them. The point survives the noise: a cold keyset page touches ~60 pages,
a cold `OFFSET 80000` touches tens of thousands.

**Extrapolation (not measured):** I benchmarked 1M rows, not 5M. Keyset page cost is by construction
independent of table size (B-tree depth grows by at most a level), so I expect the same sub-millisecond
warm figures; `OFFSET` at depth would be roughly 5× worse than above.

### Indexes (and why each exists)

| Index                                           | Serves                                                                                      |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `(task_name, quality, recorded_at, episode_id)` | the spec'd composite: task = ?, quality = ?, newest-first keyset, no sort                   |
| `(task_name, recorded_at, episode_id)`          | task-only, and `quality IN (…)`, which the planner picks at scale (confirmed in the 1M run) |
| `(recorded_at, episode_id)`                     | unfiltered global feed / time-range                                                         |
| `(task_name, duration_seconds, quality)`        | **covering** index for the analytics breakdown                                              |
| `uq_assignments_active_episode` (partial)       | the invariant _and_ the `NOT EXISTS` availability probe                                     |

The covering index was added _because I measured a problem_: `percentile_cont` over all 1M rows took
~790 ms (it fed a `GroupAggregate` from heap fetches). A first attempt `(task_name, duration_seconds)`
**did not help**; the real query also counts per-quality, which needs `quality` in the index. The
3-column version gives an Index Only Scan with 0 heap fetches: **~790 ms → ~150 ms**, for **7 MB**
(B-tree deduplication collapses these low-cardinality triples). Other groupings (robot, quality,
operator) have no index and take 350–570 ms at 1M (roughly 2–3 s at 5M by extrapolation). For heavier
use I'd precompute rollups (§7). A test also proves the composite index _can_ serve the keyset query with no `Sort` node (the competing
indexes are dropped inside a rolled-back transaction, so the planner has no other choice).

At 1M rows: heap 86 MB, indexes 235 MB (before the covering index). Extrapolation to 5M: ≈ 0.4 GB heap,
≈ 1.2 GB indexes. Indexes are the dominant cost; `task_name` text repeated in three of them is the
obvious first thing to shrink (a `task_id smallint`, §7).

### Cursor format

`base64url(JSON([sort-key values]))`: opaque to clients, validated on decode (400 on anything malformed,
6 tamper cases tested). A cursor carries _position only_: the caller's scope filters (client → own
requests) are re-applied to every page, so a forged cursor can move a window but never widen access
(tested). Cursors are deliberately not signed because there is nothing to protect.

`GET /requests`, `/episodes`, `/requests/{id}/assignments` and `/candidates` are all keyset-paginated.
The UI uses "Load more" with the cursor as its only paging state.

### Import throughput at scale

Streaming, constant memory: **peak RSS 68 MB for 1M rows (72 MB for 200k)**: O(batch), not O(file).
1,000,000 rows imported in **50 s (≈ 20k rows/s)** on one core shared with PostgreSQL; re-importing the
200k file inserted exactly **0** rows. Cleaning is only ~10 µs/row; the rest is driver + index
maintenance. At that rate 5M rows ≈ 4 minutes, which is too long for one HTTP request in
production (§7).

---

## 3. Data cleaning decisions

Principle: **normalise what is unambiguous; quarantine, with a reason, what would require a guess.**
Nothing is silently dropped: every record is accounted for, and a test asserts the identity
`rows_read == inserted + duplicates + rejected`.

### Result on the provided `episodes.csv`

189 data records (+2 blank lines) → **172 inserted**, 4 duplicate groups (2 identical, 2 conflicting),
**13 rejected**. This matches my independent by-hand analysis of the file _before_ writing the importer.

| Rows                                                               | Decision                                                          | Why                                                                          |
| ------------------------------------------------------------------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Surrounding whitespace, inner double-spaces                        | trimmed / collapsed                                               | lossless                                                                     |
| `Pick Cup`, `PICK CUP`, `Good`, `USABLE`, `ARM-01`                 | lower-cased (robot, task, quality)                                | categorical codes; made the data groupable                                   |
| `ep-00003` vs `EP-00003`                                           | IDs matched **case-insensitively**, canonical form **upper-case** | see "IDs" below                                                              |
| `2026-08-14 09:12:00`, `…T09:20:00Z`, `+02:00`, `14/08/2026 09:15` | parsed to a **UTC instant**                                       | see "Dates"                                                                  |
| `45.0`                                                             | accepted as 45                                                    | whole-number float                                                           |
| blank `operator_name` (EP-90005)                                   | **kept**, stored `NULL`, counted as a warning                     | provenance only; not a filter/billing key                                    |
| `"pick cup, then place"` (quoted comma)                            | kept, as a distinct task                                          | proper CSV parser (`csv`), not `split(",")`; no task whitelist was specified |
| Blank lines                                                        | skipped, counted                                                  |                                                                              |

**Rejected (13), each with line number + reason in the report:**
`invalid_duration` ×5 (blank, `-5`, `N/A`, `45.5`, **`999999`**), `unknown_robot` ×2 (`arm-99`, blank),
`invalid_quality` ×2 (`excellent`, blank), `missing_episode_id` ×1, `invalid_recorded_at` ×1
(`not a date`), **`future_recorded_at` ×1 (`2031-01-01`)**, `malformed_row` ×1 (5 columns).

Two of those I **missed in my first manual profile**: the `999999 s` duration and the 2031 date. My
first scan only checked _format_ ("is it a digit?", "does it look like a date?") and both are perfectly
formed but implausible; the importer's own tests found them. Lesson recorded: profile _values_, not just shapes.

**Duplicates.** `EP-00030`, `EP-00074` are identical repeats → skipped. `EP-00011` (quality `bad` vs
`good`) and `EP-00003` (vs `ep-00003`, different robot _and_ task) **conflict**: first occurrence wins,
deterministically, and the conflict is reported with _which fields differ_. Nothing is merged or guessed.

### Judgement calls worth challenging

- **IDs are upper-cased, not lower-cased** (the brief says "lowercase"). The source system's identifiers
  are `EP-nnnnn`; rewriting every ID away from its system-of-record form would make cross-referencing
  against the recorder painful. Case-_insensitive matching_ is what actually matters for dedupe, and that's
  done. Human names (`operator_name`) are also not lower-cased.
- **Dates are day-first**, because the data proves it (`14/08/2026` can't be month-first). Month-first is
  _intentionally unsupported_: an ambiguous `03/04/2026` is rejected rather than silently mis-dated.
  Zone-less timestamps are assumed **UTC** (reported as a warning count, since it is an assumption).
- **`excellent` is rejected, not mapped to `good`.** Mapping invents data, and quality decides what a client
  is sold. Likewise a fractional duration is rejected, not rounded.
- **Future dates** are rejected beyond a configurable skew (default 24 h) relative to import time. This
  depends on the server clock; if the clock is badly wrong the report makes it obvious
  (`future_recorded_at`) and `IMPORT_MAX_FUTURE_SKEW_HOURS` overrides it.
- **Durations are capped at 24 h** (catches `999999`, or ms-instead-of-seconds mistakes).
- **Unknown robots** come from a configurable allow-list (`KNOWN_ROBOTS`; default = the 5 in the README).
  A `robots` table + FK would be the next step if the fleet changes often.
- **Quarantine, don't drop.** Re-importing a _corrected_ file adds only the fixed rows (tested).

### Idempotency

`INSERT … ON CONFLICT (episode_id) DO NOTHING RETURNING episode_id`. `RETURNING` tells us exactly which
rows were new, so the remainder can be classified as identical vs conflicting duplicates by comparing with
the stored row. Each batch commits independently: re-running after a crash resumes safely; **4 concurrent
imports of the same 3,000-row file produced exactly 3,000 rows**, with every row inserted by exactly one
importer. Results are independent of batch size (tested at 1, 7, 50, 4000, so duplicates straddling batch
boundaries behave the same).

---

## 4. Security

| Area                                      | What's done                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Passwords**                             | Argon2id (salted, memory-hard), verified off the event loop. Unknown email still burns one full verification against a dummy hash, and returns the _same_ message as a wrong password, so neither timing nor wording enumerates accounts (tested). Plain-text passwords from `users.json` are hashed at seed time, never stored.                           |
| **JWT**                                   | PyJWT (not the unmaintained `python-jose`). Algorithm **pinned** on decode (defeats `alg=none`/alg-swap; tested), `exp/iat/sub/iss/aud` all _required_ and verified (wrong audience, tampered, expired, garbage: all tested → 401).                                                                                                                        |
| **Role from the database, not the token** | The token identifies the user; the role is re-read on every request. Demoting or deactivating someone takes effect immediately rather than when their token expires (tested).                                                                                                                                                                              |
| **RBAC, two layers**                      | Route-level `require_roles` dependency at the edge, _and_ the same rules re-enforced in the service layer, so they hold for every caller (HTTP, background task, scripts). Verified with an explicit role × endpoint matrix.                                                                                                                               |
| **Object-level authorisation (IDOR)**     | Clients only ever see/act on their own requests; others return `404` not `403`. List queries apply the scope in the service, not the router. Export internals and unreleased episodes are hidden from clients at the API, not just the UI.                                                                                                                 |
| **Injection**                             | 100% parameterised SQLAlchemy. The only interpolated SQL fragments (`date_trunc` unit, group-by column) come from closed `Literal` whitelists; non-whitelisted values 422 before reaching SQL (injection strings tested).                                                                                                                                  |
| **Secrets**                               | All via env/`pydantic-settings`; `JWT_SECRET` has a 32-char minimum and the app **refuses to boot in `production`** with the default.                                                                                                                                                                                                                      |
| **Transport / browser**                   | CORS is an explicit allow-list (no wildcard), `allow_credentials=False`. nginx adds CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`. In Docker the SPA calls a same-origin `/api`, so no cross-origin surface. (I found and fixed an nginx bug while testing: `add_header` in a `location` silently dropped the server-level security headers.) |
| **Resource abuse**                        | Upload size cap (413), page `limit` bounded to 200 (422), explicit-assign list bounded, DB `lock_timeout`, no unbounded in-memory file reads (streamed).                                                                                                                                                                                                   |
| **Containers**                            | Backend runs as a non-root user. `docker-compose.yml` publishes Postgres on 5432 for local convenience; remove that port mapping for anything shared.                                                                                                                                                                                                      |
| **Consistent errors**                     | One envelope `{error:{code,message,details}}`; internal exceptions don't leak stack traces.                                                                                                                                                                                                                                                                |

**Honest gaps** (see §7): login throttling is process-local rather than shared across replicas; access
token only (no refresh/revocation list); the SPA keeps the token in `sessionStorage` (survives reload, dies with the tab) which is
XSS-readable. An `httpOnly` `SameSite` cookie + CSRF token is stronger and is what I'd ship.

---

## 5. Other design decisions

- **Clean Architecture, pragmatically.** `domain/` (enums, state machine, errors, SQLAlchemy entities) →
  `application/` (services, DTOs, ports as `Protocol`s) → `infrastructure/` (repositories, UoW, JWT,
  Argon2, export simulator) → `interfaces/api/` (FastAPI). Services depend on ports, not SQLAlchemy;
  `composition.py` is the only place that knows the concrete classes. _Deliberate deviation:_ the
  SQLAlchemy models double as domain entities (no separate mapping layer), the standard FastAPI
  trade-off; sessions/engines/queries stay out of the domain.
- **Async SQLAlchemy 2.0 + asyncpg.** Pinned to the 2.0 line (`pip` would otherwise resolve 2.1, which
  has behavioural changes). Unit of Work per operation; no transaction ever spans a `sleep`.
- **Assignment history**, not a nullable `episodes.request_id`: keeps audit trail, avoids hot-row updates
  on the 5M-row table, and makes the partial unique index possible.
- **Rejection releases episodes**; acceptance keeps them. Rejected requests can be returned to
  `in_progress` for rework by staff, while accepted requests are terminal.
- **Over-assignment is capped** at `episodes_requested` (giving away inventory for free is never wanted);
  the specified `assigned >= requested` delivery guard is retained.
- **Auto-assign + manual picking.** Both exist; manual validates that every episode matches the request's
  task/quality/date criteria.
- **Frontend:** feature-driven (`features/{auth,requests,episodes,exports,analytics,imports,inventory}`),
  each owning its `types/api/hooks/components`. Cross-feature imports go through barrels or leaf modules;
  there are no cycles. TanStack Query for server state; keyset "Load more" via `useInfiniteQuery`.
  Skeleton loaders match real table layouts. The **toast system** supports updating a toast by id, so the
  export watcher shows one _"Exporting…"_ toast that morphs into success/failure (with a Retry action)
  instead of stacking notifications; it polls only while something is in flight and re-attaches after a
  page reload.

---

## 6. What was verified, and what was not

**Verified (by running it):**

- The backend test suite passes against real PostgreSQL (RBAC matrix, 75-case state-machine table,
  concurrency, import, pagination, analytics, export, migration/model drift). Lint clean (`ruff`).
- **Mutation tests** of the locking (§1): the tests fail when the locks are removed.
- The Alembic migration applies, round-trips down/up, and has **zero drift** from the models.
- Pinned `requirements.txt` installs in a **fresh venv** and the app imports.
- Full lifecycle over **real HTTP** (curl), including the real 2–5 s background export.
- **Frontend:** strict TypeScript clean, production build OK (≈ 90 KB gzipped JS). The **real React app was
  mounted in jsdom and driven against the real backend**, client → operator → export → delivery → acceptance,
  in both export scenarios (success, and forced failure with Retry). That found one real product bug, now
  fixed (explicit sign-out left a `from` redirect, so the _next_ user to sign in was dropped onto the previous
  user's page), plus several test-environment issues (jsdom replacing `URLSearchParams`, a racy assertion).
- **nginx:** the shipped config was run under real nginx: SPA fallback, `/api` prefix stripping, multipart
  upload through the proxy, headers on every location.
- The compose pipeline's _steps_ (migrate → idempotent seed → healthcheck → proxy) were rehearsed by hand from a
  pristine database.
- **Benchmarks at 1M rows** (§2).

**Not verified, and you should know:**

- **Docker was run locally**: `docker compose up --build` built all images, applied migrations, seeded
  the database, passed the backend readiness check, and started nginx. A clean-clone run on the
  evaluator's machine remains the final environment check.
- **No real browser.** I could not look at the UI (browser binaries aren't reachable from my
  sandbox). Layout, animation and visual polish are _unseen by me_; behaviour is tested through jsdom, not
  pixels. Expect to tweak spacing.
- **5M rows was not run**: 1M was (extrapolations are labelled).
- Tested on Linux only.

---

## 7. Known limitations / what I'd do next

1. **Import at 5M+ rows**: move it off the request thread (job table + `202` + progress polling) and use
   `COPY` into an unlogged staging table + `INSERT … SELECT … ON CONFLICT DO NOTHING`. The cleaning logic and
   report would stay as they are.
2. **Durable background work.** Export intent is persisted atomically with final assignment and the
   application startup recovery loop reclaims pending and stale-running work. A real queue/outbox
   (ARQ/Celery) would still be the next production step for horizontal scaling and delivery guarantees.
3. **Analytics at scale**: pre-aggregate (materialised view refreshed after import, or rollup table) for the
   un-indexed groupings; the covering index only helps the by-task breakdown.
4. **Shrink the big table:** `task_name`/`robot_id` as `smallint` FKs; consider partitioning `episodes`
   by `recorded_at`. Revisit the three non-covering indexes' write cost against import speed.
5. **Auth hardening:** login throttling/lockout, refresh tokens + revocation, `httpOnly` cookie sessions, MFA for admins.
6. Observability: request IDs, structured logs, metrics (lock waits, export outcomes).
7. A `robots` reference table; month-first date support behind an explicit per-import option.
8. `HEAD` support on health routes; signed cursors if cursors ever carry anything more than position.
