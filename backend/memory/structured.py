"""
Compass — Structured Memory Operations (Projects & Tasks).

Provides CRUD operations and fuzzy project matching for PostgreSQL.
Used by the router skills and API endpoints.
"""

from datetime import date
from typing import Optional, Union, Any
import asyncpg
from asyncpg.pool import PoolConnectionProxy

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]

PRIORITY_MAP = {
    "urgent": "urgent", "critical": "urgent", "p0": "urgent", "asap": "urgent",
    "high": "high", "p1": "high", "important": "high",
    "medium": "medium", "normal": "medium", "p2": "medium", "moderate": "medium",
    "low": "low", "p3": "low", "minor": "low",
}

STATUS_MAP = {
    "open": "open", "todo": "open", "to_do": "open", "pending": "open", "not_started": "open",
    "in_progress": "in_progress", "in progress": "in_progress", "doing": "in_progress", "wip": "in_progress",
    "done": "done", "completed": "done", "finished": "done", "closed": "done",
    "overdue": "overdue",
}

VALID_DOMAINS = {"hackathon", "coursework", "code", "general"}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def get_or_create_project(
    conn: DbConn,
    name: str,
    domain: str,
    description: Optional[str] = None,
) -> dict:
    """Find an existing project by exact or fuzzy name, or create a new one.

    Fuzzy resolution:
      1. Exact case-insensitive match (e.g. 'compass' == 'Compass')
      2. Prefix/substring match with length >= 3 safeguard
      3. Word overlap match
    """
    clean_name = name.strip()

    # 1. Exact match (case-insensitive)
    row = await conn.fetchrow(
        "SELECT id, name, domain, description, created_at FROM projects WHERE LOWER(name) = LOWER($1)",
        clean_name
    )
    if row:
        return dict(row)

    # 2. Fuzzy match: project name starts with or contains candidate, or candidate contains project name
    # Guard: Require both names to be at least 3 characters long to prevent short names
    # (like 'AI' or 'Go') from spuriously matching arbitrary task descriptions.
    if len(clean_name) >= 3:
        row = await conn.fetchrow(
            """
            SELECT id, name, domain, description, created_at
            FROM projects
            WHERE LENGTH(name) >= 3
              AND (
                  LOWER(name) LIKE '%' || LOWER($1) || '%'
                  OR LOWER($1) LIKE '%' || LOWER(name) || '%'
              )
            ORDER BY LENGTH(name) ASC
            LIMIT 1
            """,
            clean_name
        )
        if row:
            return dict(row)

    # 3. Create new project if domain is valid
    target_domain = domain if domain in VALID_DOMAINS else "general"

    row = await conn.fetchrow(
        """
        INSERT INTO projects (name, domain, description)
        VALUES ($1, $2, $3)
        ON CONFLICT (name) DO UPDATE SET description = COALESCE(EXCLUDED.description, projects.description)
        RETURNING id, name, domain, description, created_at
        """,
        clean_name, target_domain, description
    )
    return dict(row) if row else {}


async def list_projects(
    conn: DbConn,
    domain: Optional[str] = None,
) -> list[dict]:
    """Retrieve all projects, optionally filtered by domain."""
    if domain:
        rows = await conn.fetch(
            "SELECT id, name, domain, description, created_at FROM projects WHERE domain = $1 ORDER BY name ASC",
            domain
        )
    else:
        rows = await conn.fetch(
            "SELECT id, name, domain, description, created_at FROM projects ORDER BY name ASC"
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

async def create_task(
    conn: DbConn,
    domain: str,
    title: str,
    project_id: Optional[int] = None,
    due_date: Optional[date] = None,
    status: str = "open",
    priority: str = "medium",
    notes: Optional[str] = None,
    duration_minutes: int = 60,
    scheduled_start: Optional[Any] = None,
    scheduled_end: Optional[Any] = None,
    is_fixed: bool = False,
    recurrence_rule: Optional[str] = None,
) -> dict:
    """Insert a new task into the structured tasks table with normalized inputs."""
    # Normalize domain, status, and priority to satisfy SQL CHECK constraints
    dom_clean = str(domain or "general").lower().strip()
    norm_domain = dom_clean if dom_clean in VALID_DOMAINS else "general"

    stat_clean = str(status or "open").lower().strip()
    norm_status = STATUS_MAP.get(stat_clean, "open")

    prio_clean = str(priority or "medium").lower().strip()
    norm_priority = PRIORITY_MAP.get(prio_clean, "medium")

    row = await conn.fetchrow(
        """
        INSERT INTO tasks (
            domain, project_id, title, due_date, status, priority, notes,
            duration_minutes, scheduled_start, scheduled_end, is_fixed, recurrence_rule
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING id, domain, project_id, title, due_date, status, priority, notes,
                  duration_minutes, scheduled_start, scheduled_end, is_fixed, recurrence_rule,
                  created_at, updated_at
        """,
        norm_domain, project_id, title.strip(), due_date, norm_status, norm_priority, notes,
        int(duration_minutes) if duration_minutes is not None else 60,
        scheduled_start, scheduled_end, bool(is_fixed), recurrence_rule
    )
    return dict(row) if row else {}


async def get_task(conn: DbConn, task_id: int) -> Optional[dict]:
    """Retrieve a task by ID including project details and scheduling metadata."""
    row = await conn.fetchrow(
        """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed, t.recurrence_rule,
               t.created_at, t.updated_at,
               p.id AS project_id, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.id = $1
        """,
        task_id
    )
    if not row:
        return None

    data = dict(row)
    if data["project_id"]:
        data["project"] = {"id": data["project_id"], "name": data["project_name"]}
    else:
        data["project"] = None
    return data


async def list_tasks(
    conn: DbConn,
    domain: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    due_before: Optional[date] = None,
    scheduled_only: bool = False,
    unscheduled_only: bool = False,
) -> list[dict]:
    """Query tasks with optional filters."""
    query = """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed, t.recurrence_rule,
               t.created_at, t.updated_at,
               p.id AS project_id, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE 1=1
    """
    params: list[Any] = []

    if domain:
        params.append(domain)
        query += f" AND t.domain = ${len(params)}"
    if project_id:
        params.append(project_id)
        query += f" AND t.project_id = ${len(params)}"
    if status:
        params.append(status)
        query += f" AND t.status = ${len(params)}"
    if due_before:
        params.append(due_before)
        query += f" AND t.due_date <= ${len(params)}"
    if scheduled_only:
        query += " AND t.scheduled_start IS NOT NULL"
    if unscheduled_only:
        query += " AND t.scheduled_start IS NULL"

    query += " ORDER BY t.scheduled_start ASC NULLS LAST, t.due_date ASC NULLS LAST, t.id ASC"

    rows = await conn.fetch(query, *params)
    results = []
    for r in rows:
        item = dict(r)
        if item["project_id"]:
            item["project"] = {"id": item["project_id"], "name": item["project_name"]}
        else:
            item["project"] = None
        results.append(item)
    return results


async def update_task(
    conn: DbConn,
    task_id: int,
    **kwargs: Any
) -> Optional[dict]:
    """Update task fields dynamically (e.g. status, priority, due_date, notes, scheduling fields) with normalization."""
    allowed_fields = {
        "domain", "project_id", "title", "due_date", "status", "priority", "notes",
        "duration_minutes", "scheduled_start", "scheduled_end", "is_fixed", "recurrence_rule"
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return await get_task(conn, task_id)

    # Normalize fields if provided
    if "domain" in updates and updates["domain"]:
        d_val = str(updates["domain"]).lower().strip()
        updates["domain"] = d_val if d_val in VALID_DOMAINS else "general"
    if "status" in updates and updates["status"]:
        s_val = str(updates["status"]).lower().strip()
        updates["status"] = STATUS_MAP.get(s_val, "open")
    if "priority" in updates and updates["priority"]:
        p_val = str(updates["priority"]).lower().strip()
        updates["priority"] = PRIORITY_MAP.get(p_val, "medium")
    if "duration_minutes" in updates and updates["duration_minutes"] is not None:
        try:
            updates["duration_minutes"] = int(updates["duration_minutes"])
        except (ValueError, TypeError):
            updates["duration_minutes"] = 60

    set_clauses = []
    params: list[Any] = [task_id]
    for k, v in updates.items():
        params.append(v)
        set_clauses.append(f"{k} = ${len(params)}")

    set_clause_str = ", ".join(set_clauses)
    query = f"""
        UPDATE tasks
        SET {set_clause_str}, updated_at = now()
        WHERE id = $1
        RETURNING id
    """
    row = await conn.fetchrow(query, *params)
    if not row:
        return None
    return await get_task(conn, task_id)


async def delete_task(conn: DbConn, task_id: int) -> bool:
    """Delete a task by ID."""
    result = await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
    return result == "DELETE 1"


# ---------------------------------------------------------------------------
# Scheduling Preferences & Calendar Connections
# ---------------------------------------------------------------------------

async def get_scheduling_preferences(conn: DbConn, user_id: str = "default_user") -> dict:
    """Get scheduling preferences for a user, or defaults if not configured."""
    row = await conn.fetchrow(
        """
        SELECT user_id, work_start_time, work_end_time, work_days, buffer_minutes, preferred_focus
        FROM scheduling_preferences
        WHERE user_id = $1
        """,
        user_id
    )
    if row:
        res = dict(row)
        if hasattr(res["work_start_time"], "strftime"):
            res["work_start_time"] = res["work_start_time"].strftime("%H:%M:%S")
        if hasattr(res["work_end_time"], "strftime"):
            res["work_end_time"] = res["work_end_time"].strftime("%H:%M:%S")
        return res

    return {
        "user_id": user_id,
        "work_start_time": "09:00:00",
        "work_end_time": "18:00:00",
        "work_days": [1, 2, 3, 4, 5],
        "buffer_minutes": 15,
        "preferred_focus": "morning"
    }


async def update_scheduling_preferences(
    conn: DbConn,
    user_id: str = "default_user",
    **kwargs: Any
) -> dict:
    """Update or insert scheduling preferences for a user."""
    allowed = {"work_start_time", "work_end_time", "work_days", "buffer_minutes", "preferred_focus"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    # Ensure row exists
    await conn.execute(
        """
        INSERT INTO scheduling_preferences (user_id, work_start_time, work_end_time, work_days, buffer_minutes, preferred_focus)
        VALUES ($1, '09:00:00', '18:00:00', '{1,2,3,4,5}', 15, 'morning')
        ON CONFLICT (user_id) DO NOTHING
        """,
        user_id
    )

    if not updates:
        return await get_scheduling_preferences(conn, user_id)

    set_clauses = []
    params: list[Any] = [user_id]
    for k, v in updates.items():
        params.append(v)
        set_clauses.append(f"{k} = ${len(params)}")

    query = f"UPDATE scheduling_preferences SET {', '.join(set_clauses)} WHERE user_id = $1"
    await conn.execute(query, *params)
    return await get_scheduling_preferences(conn, user_id)

