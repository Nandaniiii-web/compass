# PRD — Compass Dynamic Scheduling & Google Calendar Integration

## Project Context (read this before picking up any task below)

Compass is an existing personal AI copilot (FastAPI/Python 3.12 backend on
Render, React/Vite frontend on Vercel, Neon Postgres + pgvector, three-tier
NVIDIA Nemotron models via Nebius Token Factory) that tracks tasks across
three domains: hackathon deadlines, code context, and coursework. It already
has a working agentic subsystem: a ReAct (Think → Act → Observe) loop, a
skill registry (`BASE_TOOL_DEFINITIONS` + `SKILL_REGISTRY`, OpenAI-style
function calling), a confirm-gate that pauses before any state-mutating tool
call and waits for explicit human approval via a `confirm_request` SSE
event, a reject/re-plan path, an audit log, and undo.

**The feature this PRD covers:** evolving Compass's task system into a
**dynamic scheduling system** that can place tasks into real time slots and
optionally sync with Google Calendar. "Dynamic" specifically means: the
schedule reacts on its own when something changes (a task is missed, a
deadline moves) — it is not a one-time generate-and-forget schedule.

**Current state — a first version already exists and is committed.** A pure
deterministic (non-LLM) slot allocator, calendar-related schema, a
`commit_schedule` mutating skill wired into the existing confirm-gate, a
`.ics` export, and a Calendar UI tab are already built (Phase 0 below, marked
done). What's missing, and what most of this PRD covers: (1) the calendar
connection is currently **simulated**, not real Google OAuth, and (2)
there's no reactive layer yet — nothing happens when a scheduled task is
missed. Fixing those two things is the actual point of this PRD.

**Important scoping decision — read before touching auth:** Compass is a
deliberately **single-user** application (one shared `AUTH_TOKEN`, no
multi-tenant accounts, and that's out of scope for this project). Do **not**
build multi-user authentication as part of this feature. The Google Calendar
connection only needs to support **one** connected account per deployment —
`calendar_connections` should behave as a singleton table (one row), not a
per-user table. This significantly simplifies the OAuth work below.

Work through the phases in order — each phase depends on the one before it.
Within a phase, tasks can generally be done in any order unless noted.

---

## Phase 0 — Already Completed (context only — do not redo)

- [x] Add `duration_minutes`, `scheduled_start`, `scheduled_end`, `is_fixed`, `recurrence_rule` columns to `tasks`, with index `idx_tasks_scheduled_start`
- [x] Create `calendar_connections`, `calendar_event_links`, `scheduling_preferences` tables with auto-migration
- [x] Build `backend/services/scheduler.py` — deterministic pure-Python slot allocator honoring working hours (09:00–18:00 UTC, Mon–Fri) and a 15-minute inter-task buffer
- [x] Build `backend/services/calendar.py` — free/busy aggregation (currently simulated) and RFC 5545 `.ics` feed generation
- [x] Register `get_calendar_availability`, `propose_schedule`, `commit_schedule` in `BASE_TOOL_DEFINITIONS` / `SKILL_REGISTRY`
- [x] Add `commit_schedule` to `MUTATING_TOOLS` so it pauses via `confirm_request` before writing
- [x] Extend `undo_last_agent_action` to revert committed schedule slots and calendar links
- [x] Add `GET /api/calendar/status`, `GET /api/calendar/availability`, `POST /api/schedule/propose`, `POST /api/schedule/commit`, `GET /api/calendar/export.ics`, `GET`/`PUT /api/calendar/preferences`
- [x] Build `CalendarView.jsx` — 08:00–20:00 visual time grid, domain color-coding, "Auto-Schedule Unplaced Tasks" button, `.ics` export button
- [x] Add the "Schedule & Calendar" tab to `Sidebar.jsx` and `App.jsx`
- [x] Write `tests/test_scheduling.py` (13 tests: allocator, conflicts, `.ics` generation, endpoints)

---

## Phase 1 — Foundation (Setup)

- [ ] Add a `task_dependencies` table (`task_id`, `depends_on_task_id`, both FK to `tasks`) with an auto-migration matching the existing pattern in `backend/memory/db.py`
- [ ] Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` to `backend/config.py` and `.env.example`
- [ ] Add `google-auth`, `google-auth-oauthlib`, `google-api-python-client` to `backend/requirements.txt`
- [ ] Create `backend/services/crypto.py` with a symmetric encrypt/decrypt helper (e.g. `cryptography.fernet`, key sourced from a new `TOKEN_ENCRYPTION_KEY` env var) for storing refresh tokens at rest
- [ ] Enforce singleton semantics on `calendar_connections` — add a unique constraint or fixed `id = 1` upsert pattern, since this deployment supports exactly one connected account

## Phase 2 — Real Google OAuth Connect Flow (Core)

- [ ] Create `GET /api/calendar/connect` that redirects to Google's OAuth consent screen requesting the `calendar.readonly` scope
- [ ] Create `GET /api/calendar/callback` that exchanges the returned authorization code for access + refresh tokens and upserts the single `calendar_connections` row (encrypted refresh token via Phase 1's crypto helper, account email, granted scopes, `connected_at`)
- [ ] Create `POST /api/calendar/disconnect` that revokes the token via Google's revocation endpoint and deletes the `calendar_connections` row
- [ ] Update `GET /api/calendar/status` to report real connection state (`connected: true/false`, account email, last sync time) instead of always returning simulated status
- [ ] Add a token-refresh helper that proactively refreshes the access token before expiry, and marks the connection as needing reconnection on a 401 / `invalid_grant` response rather than failing silently

## Phase 3 — Swap Simulated Data for Real Reads (Core)

- [ ] Modify `backend/services/calendar.py`'s free/busy fetch function to call Google's `freebusy.query` endpoint when a real connection exists, falling back to the existing simulated data when it doesn't
- [ ] Add a helper to normalize Google's returned event times to UTC for internal comparison against `scheduled_start`/`scheduled_end`
- [ ] Update the `get_calendar_availability` skill handler to use the real-or-simulated source transparently, with no change to its tool-call interface
- [ ] Add an explicit `source: "connected" | "simulated"` field to `GET /api/calendar/status`'s response, and surface it as a visible badge in `CalendarView.jsx`

## Phase 4 — Reactive Rescheduling (Core — this is the actual "dynamic" part)

- [ ] Add `find_missed_scheduled_tasks()` to `backend/services/scheduler.py` — queries `tasks` where `scheduled_end < now()` and `status != 'done'`
- [ ] Add a check in `backend/jobs/consolidate.py`'s nightly run that calls `find_missed_scheduled_tasks()` and, for each result, triggers a targeted agent re-plan through the existing agent loop (reuse `run_agent_loop`, don't build a second path)
- [ ] Ensure the re-plan for a missed task reuses the existing `confirm_request` gate before committing a new time slot — no silent auto-reschedule
- [ ] Add `POST /api/schedule/trigger-reactive-check` for on-demand testing/demo, mirroring the existing `/api/agent/trigger-nightly` pattern
- [ ] Add a dependency-graph walk helper — given a `task_id`, return all tasks that depend on it (directly or transitively) via `task_dependencies`
- [ ] Scope the reactive re-plan to the missed task plus its dependents only, not a full schedule recompute

## Phase 5 — Conflict Detection Skill (Core)

- [ ] Register a new `detect_schedule_conflicts` tool in `BASE_TOOL_DEFINITIONS` with a handler that checks: internal task-to-task overlaps, external calendar collisions (when connected), and deadlines that are now unreachable given current slot assignments
- [ ] Wire `detect_schedule_conflicts` to run automatically as part of the Phase 4 reactive check, surfacing results as a new `agent_runs` entry the user can review in the Agent Activity feed

## Phase 6 — Task Dependency UI (Polish)

- [ ] Add a "depends on" picker to the existing task creation/edit UI, writing to `task_dependencies`
- [ ] Show a small dependency indicator/badge on task cards in `CalendarView.jsx` when a task has one or more dependents

## Phase 7 — Honest Labeling & Docs (Polish — do this regardless of how much of Phases 2–3 is finished)

- [ ] Add a "Simulated" / "Live" badge next to the Calendar tab header in `CalendarView.jsx`, driven by Phase 3's `source` field
- [ ] Update `README.md`'s calendar section to state plainly whether the connection is live OAuth or simulated demo data — no unqualified "integration" language while it's still simulated
- [ ] Update `CHANGES.md` and any submission-facing docs to match

## Phase 8 — Verification (Polish)

- [ ] Write `tests/test_calendar_oauth.py` covering connect / callback / disconnect (mock Google's token endpoint — do not call the real Google API in tests)
- [ ] Write `tests/test_reactive_scheduling.py` covering `find_missed_scheduled_tasks`, dependency-scoped re-plan, and confirmation that the `confirm_request` gate actually fires
- [ ] Run the full combined `pytest tests/ -v` (the whole directory, not just the new files) and record the real total in `progress.txt`
- [ ] Live-browser-verify: create a task with `scheduled_end` in the past, trigger the reactive check, confirm a `confirm_request` actually appears in `AgentPanel`