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
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status     ON agent_runs(status);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs(created_at);

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
