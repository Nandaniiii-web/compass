"""
Compass — Integration Test Suite for Structured Memory Operations.

Validates:
  - Project CRUD and fuzzy project matching (get_or_create_project).
  - Task CRUD lifecycle: create, read, list with filters, update, and delete.
  - Foreign key relationships between tasks and projects.

Runs with:
    pytest tests/test_structured_memory.py -v
"""

import sys
import uuid
import pytest
import pytest_asyncio
import asyncpg
from datetime import date, timedelta
from pathlib import Path

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from backend.config import get_settings
from backend.memory.structured import (
    get_or_create_project,
    list_projects,
    create_task,
    get_task,
    list_tasks,
    update_task,
    delete_task,
)

settings = get_settings()


@pytest_asyncio.fixture(scope="function")
async def db_conn():
    """Fixture providing an isolated PostgreSQL connection wrapped in a transaction that rolls back."""
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, timeout=15.0)
    except Exception as e:
        pytest.skip(f"PostgreSQL database not reachable at {settings.DATABASE_URL}: {e}")

    # Use a transaction so each test rolls back its modifications
    tr = conn.transaction()
    await tr.start()

    try:
        yield conn
    finally:
        await tr.rollback()
        await conn.close()


# ---------------------------------------------------------------------------
# Project Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_fuzzy_match_project(db_conn):
    """Verify that get_or_create_project creates projects and resolves fuzzy aliases."""
    unique_suffix = str(uuid.uuid4())[:8]
    base_name = f"Alpha Project {unique_suffix}"

    # 1. Create project
    proj1 = await get_or_create_project(
        db_conn,
        name=base_name,
        domain="hackathon",
        description="Test project description",
    )
    assert proj1["id"] is not None
    assert proj1["name"] == base_name
    assert proj1["domain"] == "hackathon"

    # 2. Exact match (case-insensitive) should return the exact same project
    proj_exact = await get_or_create_project(
        db_conn,
        name=base_name.lower(),
        domain="hackathon",
    )
    assert proj_exact["id"] == proj1["id"]

    # 3. Fuzzy match: Substring / Prefix match
    # Querying "Alpha Project" should resolve to "Alpha Project <suffix>"
    proj_fuzzy = await get_or_create_project(
        db_conn,
        name=f"Alpha Project {unique_suffix}",
        domain="hackathon",
    )
    assert proj_fuzzy["id"] == proj1["id"]


@pytest.mark.asyncio
async def test_list_projects(db_conn):
    """Verify listing and filtering projects by domain."""
    unique_id = str(uuid.uuid4())[:6]
    await get_or_create_project(db_conn, f"Coursework Proj {unique_id}", "coursework")
    await get_or_create_project(db_conn, f"Code Proj {unique_id}", "code")

    coursework_projs = await list_projects(db_conn, domain="coursework")
    assert any(p["name"] == f"Coursework Proj {unique_id}" for p in coursework_projs)
    assert all(p["domain"] == "coursework" for p in coursework_projs)


# ---------------------------------------------------------------------------
# Task Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_crud_lifecycle(db_conn):
    """Verify full CRUD lifecycle of tasks: create, read, update, list, delete."""
    # 1. Setup project
    proj = await get_or_create_project(
        db_conn,
        name=f"Task Test Project {uuid.uuid4().hex[:6]}",
        domain="code",
    )
    proj_id = proj["id"]

    # 2. Create Task
    today = date.today()
    due = today + timedelta(days=3)
    task = await create_task(
        db_conn,
        domain="code",
        title="Implement vector search",
        project_id=proj_id,
        due_date=due,
        status="open",
        priority="high",
        notes="Wire up pgvector cosine search",
    )
    assert task["id"] is not None
    assert task["title"] == "Implement vector search"
    assert task["domain"] == "code"
    assert task["status"] == "open"
    assert task["priority"] == "high"
    assert task["due_date"] == due

    task_id = task["id"]

    # 3. Read Task (with joined project details)
    fetched = await get_task(db_conn, task_id)
    assert fetched is not None
    assert fetched["id"] == task_id
    assert fetched["project"] is not None
    assert fetched["project"]["id"] == proj_id

    # 4. List Tasks with filter
    code_tasks = await list_tasks(db_conn, domain="code", status="open")
    assert any(t["id"] == task_id for t in code_tasks)

    # 5. Update Task
    updated = await update_task(
        db_conn,
        task_id=task_id,
        status="in_progress",
        priority="urgent",
        notes="In progress by Rhythm",
    )
    assert updated is not None
    assert updated["status"] == "in_progress"
    assert updated["priority"] == "urgent"
    assert updated["notes"] == "In progress by Rhythm"

    # 6. Delete Task
    deleted = await delete_task(db_conn, task_id)
    assert deleted is True

    # Confirm deletion
    post_delete = await get_task(db_conn, task_id)
    assert post_delete is None
