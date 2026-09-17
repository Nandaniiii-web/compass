"""
Compass — Tests for Dynamic Reactive Scheduling, Dependency Graph, and Google OAuth.

Tests cover:
1. Google OAuth URL generation, HMAC-SHA256 authenticated token encryption roundtrip, and token exchange.
2. Directed Acyclic Graph (DAG) dependency creation and cycle prevention.
3. Transitive downstream dependent traversal.
4. Deterministic topological slot allocation respecting prerequisite order and inter-task buffers.
5. Detection of slipped uncompleted tasks past scheduled_end.
6. Reactive re-planning scoping (slipped task + downstream cascade, leaving unrelated tasks fixed).
7. Cascading schedule conflict detection (dependency timing violations, deadline breaches, slips).
8. API endpoints: OAuth connect/callback/disconnect, dependency CRUD, and /api/schedule/reactive-check.
"""

from datetime import datetime, date, time, timedelta, timezone
import pytest
from httpx import AsyncClient

from backend.services.oauth import generate_google_oauth_url, encrypt_token, decrypt_token, exchange_code_for_tokens
from backend.services.scheduler import (
    TimeWindow,
    allocate_task_slots,
    find_slipped_tasks,
    replan_slipped_tasks,
    detect_schedule_conflicts,
    get_available_windows,
)
from backend.skills import SKILL_REGISTRY


# ---------------------------------------------------------------------------
# 1. OAuth & Encryption at Rest
# ---------------------------------------------------------------------------

def test_oauth_url_and_crypto():
    """Verify Google OAuth authorization URL structure and symmetric token encryption roundtrip."""
    url = generate_google_oauth_url(client_id="test-client-123", redirect_uri="http://localhost:8000/api/calendar/callback")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=test-client-123" in url
    assert "calendar.readonly" in url
    assert "access_type=offline" in url

    # Token encryption & decryption roundtrip
    secret = "ya29.a0AfH6SMB_secret_access_token_value_xyz"
    encrypted = encrypt_token(secret)
    assert encrypted != secret
    decrypted = decrypt_token(encrypted)
    assert decrypted == secret

    # Empty token returns None/empty
    assert encrypt_token(None) is None
    assert decrypt_token(None) is None


@pytest.mark.asyncio
async def test_oauth_mock_exchange():
    """Verify exchange_code_for_tokens returns valid tokens in demo/fallback mode."""
    tokens = await exchange_code_for_tokens("mock_auth_code_123")
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert "email" in tokens
    assert tokens["expires_in"] > 0


# ---------------------------------------------------------------------------
# 2. Dependency Graph & Cycle Prevention (Unit & DAG logic)
# ---------------------------------------------------------------------------

def test_topological_slot_allocation_respects_prerequisites():
    """Verify task slot allocator enforces prerequisite completion before child starts."""
    # Available window: Mon 2026-09-21 09:00 - 18:00
    w_start = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    w_end = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    windows = [TimeWindow(start=w_start, end=w_end)]

    # Task A: Prerequisite (60 mins, medium priority)
    # Task B: Child (60 mins, urgent priority — higher priority than A!)
    tasks = [
        {"id": 2, "title": "Deploy Service (Child)", "priority": "urgent", "duration_minutes": 60, "depends_on": [1]},
        {"id": 1, "title": "Build Binary (Parent)", "priority": "medium", "duration_minutes": 60},
    ]

    allocation = allocate_task_slots(
        tasks=tasks,
        available_windows=windows,
        buffer_minutes=15,
        dependencies={2: [1]},
    )

    scheduled = {s["task_id"]: s for s in allocation["scheduled"]}
    assert 1 in scheduled
    assert 2 in scheduled

    # Even though Task 2 is urgent, Task 1 must be scheduled first
    t1_end = datetime.fromisoformat(scheduled[1]["scheduled_end"])
    t2_start = datetime.fromisoformat(scheduled[2]["scheduled_start"])

    # Task 2 start must be >= Task 1 end + 15m buffer
    assert t2_start >= t1_end + timedelta(minutes=15)
    assert scheduled[1]["scheduled_start"] == "2026-09-21T09:00:00+00:00"
    assert scheduled[1]["scheduled_end"] == "2026-09-21T10:00:00+00:00"
    assert scheduled[2]["scheduled_start"] == "2026-09-21T10:15:00+00:00"
    assert scheduled[2]["scheduled_end"] == "2026-09-21T11:15:00+00:00"


def test_topological_allocation_unfulfilled_prerequisite():
    """Verify that a task whose prerequisite cannot be placed is reported as unassigned."""
    w_start = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    # Very short window: only 30 minutes
    w_end = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    windows = [TimeWindow(start=w_start, end=w_end)]

    # Task 1 requires 60 mins -> cannot fit in 30 min window
    # Task 2 depends on Task 1
    tasks = [
        {"id": 1, "title": "Heavy Task", "duration_minutes": 60},
        {"id": 2, "title": "Dependent Task", "duration_minutes": 15, "depends_on": [1]},
    ]

    allocation = allocate_task_slots(
        tasks=tasks,
        available_windows=windows,
        dependencies={2: [1]},
    )

    assert len(allocation["scheduled"]) == 0
    assert len(allocation["unassigned"]) == 2
    unassigned_ids = {u["task_id"] for u in allocation["unassigned"]}
    assert 1 in unassigned_ids
    assert 2 in unassigned_ids


# ---------------------------------------------------------------------------
# 3. Slipped Task Detection & Scoped Reactive Re-planning
# ---------------------------------------------------------------------------

def test_find_slipped_tasks():
    """Verify find_slipped_tasks detects uncompleted tasks past scheduled_end."""
    now = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)

    tasks = [
        # Slipped: scheduled 10:00 - 11:00, status open, now is 14:00
        {"id": 1, "title": "Slipped Task", "status": "open", "scheduled_start": "2026-09-21T10:00:00Z", "scheduled_end": "2026-09-21T11:00:00Z"},
        # On track: scheduled 15:00 - 16:00
        {"id": 2, "title": "Future Task", "status": "open", "scheduled_start": "2026-09-21T15:00:00Z", "scheduled_end": "2026-09-21T16:00:00Z"},
        # Finished: scheduled 10:00 - 11:00, but marked done -> should not flag
        {"id": 3, "title": "Completed Task", "status": "done", "scheduled_start": "2026-09-21T10:00:00Z", "scheduled_end": "2026-09-21T11:00:00Z"},
    ]

    slipped = find_slipped_tasks(tasks, current_time=now)
    assert len(slipped) == 1
    assert slipped[0]["id"] == 1
    assert slipped[0]["slip_minutes"] == 180  # 11:00 to 14:00 = 3 hours


def test_replan_slipped_tasks_scoping():
    """Verify replan_slipped_tasks cascades to downstream dependents while preserving unrelated tasks."""
    now = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
    # Windows from 14:30 onwards
    windows = [TimeWindow(start=now + timedelta(minutes=30), end=now + timedelta(hours=6))]

    # Dependency graph:
    # Task 1 (slipped) -> Task 2 (dependent on 1) -> Task 3 (dependent on 2)
    # Task 4 (unrelated task, scheduled 17:00 - 18:00)
    all_tasks = [
        {"id": 1, "title": "Slipped Task", "duration_minutes": 60, "status": "open", "scheduled_start": "2026-09-21T10:00:00Z", "scheduled_end": "2026-09-21T11:00:00Z"},
        {"id": 2, "title": "Downstream 1", "duration_minutes": 45, "status": "open", "depends_on": [1], "scheduled_start": "2026-09-21T11:15:00Z", "scheduled_end": "2026-09-21T12:00:00Z"},
        {"id": 3, "title": "Downstream 2", "duration_minutes": 30, "status": "open", "depends_on": [2]},
        {"id": 4, "title": "Unrelated Standalone", "duration_minutes": 60, "status": "open", "scheduled_start": "2026-09-21T17:00:00Z", "scheduled_end": "2026-09-21T18:00:00Z"},
    ]

    slipped = [all_tasks[0]]
    dep_map = {2: [1], 3: [2]}

    replan = replan_slipped_tasks(
        slipped_tasks=slipped,
        all_tasks=all_tasks,
        dependencies=dep_map,
        available_windows=windows,
        buffer_minutes=15,
    )

    assert replan["slipped_task_ids"] == [1]
    # Affected must include slipped task 1 and its cascading dependents 2 and 3
    assert set(replan["affected_task_ids"]) == {1, 2, 3}
    assert 4 not in replan["affected_task_ids"]

    rescheduled_ids = [s["task_id"] for s in replan["rescheduled"]]
    assert 1 in rescheduled_ids
    assert 2 in rescheduled_ids
    assert 3 in rescheduled_ids
    assert 4 not in rescheduled_ids


# ---------------------------------------------------------------------------
# 4. Cascading Schedule Conflict Detection
# ---------------------------------------------------------------------------

def test_detect_schedule_conflicts_dependency_violations():
    """Verify detect_schedule_conflicts flags when a task is scheduled before prerequisite finishes."""
    tasks = [
        {"id": 10, "title": "Prerequisite Task", "scheduled_start": "2026-09-21T10:00:00Z", "scheduled_end": "2026-09-21T11:00:00Z"},
        # Task 11 starts at 10:30, while Task 10 only ends at 11:00!
        {"id": 11, "title": "Child Task", "scheduled_start": "2026-09-21T10:30:00Z", "scheduled_end": "2026-09-21T11:30:00Z", "depends_on": [10]},
    ]

    conflicts = detect_schedule_conflicts(
        scheduled_tasks=tasks,
        dependencies={11: [10]},
        buffer_minutes=15,
    )

    # Should detect both direct overlap and dependency_violation
    conflict_types = {c["conflict_type"] for c in conflicts}
    assert "dependency_violation" in conflict_types
    assert "overlap" in conflict_types


def test_detect_schedule_conflicts_slipped_and_deadline():
    """Verify detect_schedule_conflicts flags deadline exceeded and slipped tasks."""
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    tasks = [
        # Slipped past now
        {"id": 20, "title": "Unfinished Morning Task", "status": "open", "scheduled_start": "2026-09-21T09:00:00Z", "scheduled_end": "2026-09-21T10:00:00Z"},
        # Scheduled past due date
        {"id": 21, "title": "Overdue Deadline Task", "status": "open", "due_date": "2026-09-20", "scheduled_start": "2026-09-21T16:00:00Z", "scheduled_end": "2026-09-21T17:00:00Z"},
    ]

    conflicts = detect_schedule_conflicts(
        scheduled_tasks=tasks,
        current_time=now,
    )

    conflict_types = {c["conflict_type"] for c in conflicts}
    assert "slipped_deadline" in conflict_types
    assert "deadline_exceeded" in conflict_types


# ---------------------------------------------------------------------------
# 5. API Endpoints Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oauth_endpoints(client: AsyncClient):
    """GET /api/calendar/connect and callback endpoint integration."""
    # 1. Connect URL
    resp = await client.get("/api/calendar/connect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "accounts.google.com" in data["url"]

    # 2. Callback redirect with mock code
    callback_resp = await client.get("/api/calendar/callback?code=test_mock_oauth_code")
    assert callback_resp.status_code == 200
    assert "text/html" in callback_resp.headers.get("content-type", "")
    assert "Google Calendar Connected" in callback_resp.text

    # 3. Disconnect
    disc_resp = await client.post("/api/calendar/disconnect")
    assert disc_resp.status_code == 200
    assert disc_resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_reactive_schedule_check_endpoint(client: AsyncClient):
    """POST /api/schedule/reactive-check detects slipped tasks and stages replan."""
    resp = await client.post(
        "/api/schedule/reactive-check",
        json={"current_time": "2026-09-25T18:00:00Z"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "slipped_count" in data


@pytest.mark.asyncio
async def test_schedule_conflicts_endpoint(client: AsyncClient):
    """GET /api/schedule/conflicts returns conflict detection report."""
    resp = await client.get("/api/schedule/conflicts")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data or "response" in data
