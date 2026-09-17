"""
Compass — Async database connection pool.

Uses asyncpg with pgvector codec registration.
The pool registers the vector type on every new connection via the `init` callback,
so all connections in the pool can read/write VECTOR columns.
"""
from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector


_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Called for every new connection in the pool.
    Registers the pgvector type codec so asyncpg can handle VECTOR columns."""
    await register_vector(conn)


async def _ensure_tables(pool: asyncpg.Pool) -> None:
    """Create agent_runs and agent_audit_log tables if they don't already exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id                 TEXT          PRIMARY KEY,
            goal               TEXT          NOT NULL,
            status             TEXT          NOT NULL,
            accumulated_steps  JSONB         NOT NULL DEFAULT '[]'::jsonb,
            messages           JSONB         NOT NULL DEFAULT '[]'::jsonb,
            pending_actions    JSONB         NOT NULL DEFAULT '[]'::jsonb,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS conversation_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status          ON agent_runs(status);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at      ON agent_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id ON agent_runs(conversation_id);

        CREATE TABLE IF NOT EXISTS agent_audit_log (
            id                 SERIAL        PRIMARY KEY,
            run_id             TEXT,
            tool               TEXT          NOT NULL,
            args               JSONB         NOT NULL DEFAULT '{}'::jsonb,
            affected_table     TEXT          NOT NULL DEFAULT 'tasks',
            affected_id        INTEGER,
            previous_state     JSONB,
            new_state          JSONB,
            approved_by        TEXT          NOT NULL DEFAULT 'user',
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        ALTER TABLE agent_audit_log DROP CONSTRAINT IF EXISTS agent_audit_log_run_id_fkey;
        ALTER TABLE agent_audit_log ADD COLUMN IF NOT EXISTS is_reverted BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_agent_audit_log_run_id     ON agent_audit_log(run_id);
        CREATE INDEX IF NOT EXISTS idx_agent_audit_log_created_at ON agent_audit_log(created_at);

        -- Dynamic Scheduling & Calendar Extensions
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 60;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_end TIMESTAMPTZ;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_fixed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_rule TEXT;
        CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_start ON tasks(scheduled_start);

        CREATE TABLE IF NOT EXISTS calendar_connections (
            id                 SERIAL        PRIMARY KEY,
            user_id            TEXT          NOT NULL DEFAULT 'default_user',
            provider           TEXT          NOT NULL DEFAULT 'google',
            account_email      TEXT,
            refresh_token      TEXT,
            access_token       TEXT,
            token_expiry       TIMESTAMPTZ,
            scopes             TEXT[]        DEFAULT '{}',
            connected_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
            last_synced_at     TIMESTAMPTZ,
            sync_token         TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_conn_user_provider ON calendar_connections(user_id, provider);

        CREATE TABLE IF NOT EXISTS calendar_event_links (
            id                 SERIAL        PRIMARY KEY,
            task_id            INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            google_event_id    TEXT          NOT NULL,
            calendar_id        TEXT          NOT NULL DEFAULT 'primary',
            sync_status        TEXT          NOT NULL DEFAULT 'synced',
            last_synced_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(task_id, google_event_id)
        );

        CREATE TABLE IF NOT EXISTS scheduling_preferences (
            id                 SERIAL        PRIMARY KEY,
            user_id            TEXT          NOT NULL DEFAULT 'default_user' UNIQUE,
            work_start_time    TIME          NOT NULL DEFAULT '09:00:00',
            work_end_time      TIME          NOT NULL DEFAULT '18:00:00',
            work_days          INTEGER[]     NOT NULL DEFAULT '{1,2,3,4,5}',
            buffer_minutes     INTEGER       NOT NULL DEFAULT 15,
            preferred_focus    TEXT          NOT NULL DEFAULT 'morning'
        );

        CREATE TABLE IF NOT EXISTS task_dependencies (
            id                 SERIAL        PRIMARY KEY,
            task_id            INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            depends_on_task_id INTEGER       NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE(task_id, depends_on_task_id),
            CHECK(task_id != depends_on_task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_dep_task_id ON task_dependencies(task_id);
        CREATE INDEX IF NOT EXISTS idx_task_dep_depends_on ON task_dependencies(depends_on_task_id);
        """)


async def init_pool(dsn: str | None = None) -> asyncpg.Pool:
    """Create the connection pool. Safe to call multiple times (idempotent).

    Args:
        dsn: PostgreSQL connection string. If None, reads from settings.
    """
    global _pool
    import asyncio

    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    if _pool is not None:
        pool_loop = getattr(_pool, "_loop", None)
        if pool_loop is not None and not pool_loop.is_closed() and (cur_loop is None or pool_loop is cur_loop):
            return _pool
        _pool = None

    if dsn is None:
        from backend.config import get_settings
        dsn = get_settings().DATABASE_URL

    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        init=_init_connection,  # register pgvector on every connection
    )
    try:
        await _ensure_tables(_pool)
    except Exception as e:
        import logging
        logging.getLogger("compass.db").warning(f"Could not auto-create tables: {e}")
    return _pool  # type: ignore[return-value]


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool or initialize if not yet created or loop is closed."""
    global _pool
    import asyncio

    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    if _pool is not None:
        pool_loop = getattr(_pool, "_loop", None)
        if pool_loop is None or pool_loop.is_closed() or (cur_loop and pool_loop is not cur_loop):
            _pool = None

    if _pool is None:
        return await init_pool()
    return _pool



async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
