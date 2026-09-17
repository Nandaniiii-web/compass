"""
Compass — Nightly Memory & State Consolidation Worker.

Executed nightly via Nebius Serverless Job (deploy/serverless_job.yaml) or standalone.
Responsibilities:
  1. Overdue Task Flagger: Finds open tasks past their due_date and marks them 'overdue'.
  2. Vector Deduplication: Finds memory chunks with cosine similarity > threshold and prunes duplicates.
  3. Thread Archival: Condenses conversations inactive for > 7 days into summarized memory_chunks using Nemotron.

Usage:
    python -m backend.jobs.consolidate [--similarity-threshold 0.95] [--stale-thread-days 7] [--dry-run]
"""

import sys
import os
import math
import logging
import argparse
import asyncio
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

import asyncpg
from pgvector.asyncpg import register_vector
from backend.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("compass.consolidate")
settings = get_settings()


# ---------------------------------------------------------------------------
# Helper: Embeddings & LLM Summarization
from backend.services.embeddings import get_embedding


async def summarize_messages(client, messages: list[dict]) -> str:
    """Condense conversation messages using Nemotron Ultra (synthesis model) or fallback."""
    formatted = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
    if client and settings.NEBIUS_API_KEY:
        try:
            prompt = (
                "You are an archival intelligence assistant. Summarize the following "
                "conversation into 2-3 concise sentences focusing strictly on key decisions, "
                "tasks created or completed, and relevant technical context.\n\n"
                f"{formatted}"
            )
            resp = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You produce concise, factual conversation summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=256,
            )
            content = resp.choices[0].message.content
            if content:
                return content.strip()
        except Exception as e:
            logger.warning(f"Nemotron conversation summarization failed ({e}); using extractive summary")

    # Extractive fallback
    first = messages[0]["content"] if messages else "No content"
    last = messages[-1]["content"] if len(messages) > 1 else ""
    return f"Archived conversation summary. Began with: '{first[:100]}...'. Concluded with: '{last[:100]}...'."


# ---------------------------------------------------------------------------
# Task 1: Overdue Task Flagger
# ---------------------------------------------------------------------------

async def flag_overdue_tasks(conn: asyncpg.Connection, dry_run: bool = False) -> int:
    """Find open/in_progress tasks past due_date and update them to 'overdue'."""
    today = date.today()
    overdue_tasks = await conn.fetch(
        """
        SELECT id, title, domain, due_date, status, priority
        FROM tasks
        WHERE status IN ('open', 'in_progress')
          AND due_date IS NOT NULL
          AND due_date < $1
        ORDER BY due_date ASC
        """,
        today
    )

    count = len(overdue_tasks)
    if not overdue_tasks:
        logger.info("  [1/3] Overdue tasks check: 0 tasks overdue.")
        return 0

    logger.info(f"  [1/3] Found {count} overdue task(s):")
    for t in overdue_tasks:
        days_late = (today - t["due_date"]).days
        logger.info(f"    ⚠️  [#{t['id']}] '{t['title']}' ({t['domain']}) was due {t['due_date']} ({days_late}d ago)")

    if not dry_run:
        task_ids = [t["id"] for t in overdue_tasks]
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'overdue', updated_at = now()
            WHERE id = ANY($1::int[])
            """,
            task_ids
        )
        logger.info(f"    ✅ Marked {count} task(s) as 'overdue'.")
    else:
        logger.info(f"    [DRY-RUN] Would mark {count} task(s) as 'overdue'.")

    return count


# ---------------------------------------------------------------------------
# Task 2: Vector Deduplication
# ---------------------------------------------------------------------------

async def deduplicate_vectors(
    conn: asyncpg.Connection,
    threshold: float = 0.95,
    dry_run: bool = False
) -> int:
    """Find memory_chunks with cosine similarity > threshold and remove older duplicates."""
    # Query pairs with cosine similarity > threshold
    # Note: in pgvector, embedding <=> embedding is cosine distance (0 = identical, 2 = opposite).
    # Cosine similarity = 1 - (embedding <=> embedding).
    # Similarity > threshold <=> distance < (1 - threshold).
    max_distance = 1.0 - threshold

    # Optimized LATERAL join using pgvector HNSW index rather than quadratic Cartesian product.
    # Note: Nightly job bounds candidate chunks to the last 30 days to keep runtimes predictable;
    # older chunks should be handled via a separate, less frequent reconciliation pass.
    duplicates = await conn.fetch(
        """
        SELECT
            a.id AS keep_id,
            b.id AS remove_id,
            a.source AS keep_source,
            b.source AS remove_source,
            1.0 - (a.embedding <=> b.embedding) AS similarity
        FROM memory_chunks a
        CROSS JOIN LATERAL (
            SELECT id, source, embedding
            FROM memory_chunks b
            WHERE b.id > a.id
              AND (a.embedding <=> b.embedding) < $1
            ORDER BY b.embedding <=> a.embedding ASC
            LIMIT 1
        ) b
        WHERE a.created_at > now() - interval '30 days'
        ORDER BY similarity DESC
        """,
        max_distance
    )

    if not duplicates:
        logger.info(f"  [2/3] Vector deduplication (similarity > {threshold}): No duplicates found.")
        return 0

    to_remove = set()
    logger.info(f"  [2/3] Found {len(duplicates)} duplicate vector pair(s):")
    for d in duplicates:
        to_remove.add(d["remove_id"])
        sim_pct = round(d["similarity"] * 100, 2)
        logger.info(f"    🔄 Chunk #{d['remove_id']} is {sim_pct}% similar to #{d['keep_id']} (pruning #{d['remove_id']})")

    if not dry_run and to_remove:
        await conn.execute(
            "DELETE FROM memory_chunks WHERE id = ANY($1::int[])",
            list(to_remove)
        )
        logger.info(f"    ✅ Pruned {len(to_remove)} duplicate memory chunk(s).")
    elif dry_run:
        logger.info(f"    [DRY-RUN] Would prune {len(to_remove)} duplicate chunk(s).")

    return len(to_remove)


# ---------------------------------------------------------------------------
# Task 3: Thread Archival & Summarization
# ---------------------------------------------------------------------------

async def archive_stale_threads(
    conn: asyncpg.Connection,
    client,
    stale_days: int = 7,
    dry_run: bool = False
) -> int:
    """Condense conversations inactive for > stale_days into summarized memory chunks."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

    stale_convs = await conn.fetch(
        """
        SELECT c.id, c.started_at, c.last_active_at, COUNT(m.id) AS msg_count
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.last_active_at < $1
        GROUP BY c.id
        HAVING COUNT(m.id) > 0
        ORDER BY c.last_active_at ASC
        """,
        cutoff
    )

    if not stale_convs:
        logger.info(f"  [3/3] Thread archival (> {stale_days}d inactive): No stale conversations found.")
        return 0

    logger.info(f"  [3/3] Found {len(stale_convs)} stale conversation(s) to archive:")
    archived_count = 0

    for c in stale_convs:
        cid = c["id"]
        rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC",
            cid
        )
        messages = [{"role": r["role"], "content": r["content"]} for r in rows]

        # Check if already archived to avoid duplicate memory chunks
        archive_source = f"archive/conversation/{cid}"
        existing = await conn.fetchval(
            "SELECT id FROM memory_chunks WHERE source = $1",
            archive_source
        )
        if existing:
            logger.info(f"    - Conversation {cid} already archived as chunk #{existing}.")
            continue

        summary = await summarize_messages(client, messages)
        emb = await get_embedding(summary)

        logger.info(f"    📦 Archiving conv {cid} ({len(messages)} msgs, last active {c['last_active_at'].date()}):")
        logger.info(f"       Summary: {summary[:120]}...")

        if not dry_run:
            await conn.execute(
                """
                INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                "general",
                None,
                summary,
                emb,
                archive_source,
                ["archived", "conversation_summary", f"conv_{cid}"]
            )
            archived_count += 1
            logger.info(f"       ✅ Created consolidated memory chunk for {cid}.")
        else:
            archived_count += 1
            logger.info(f"       [DRY-RUN] Would create memory chunk for {cid}.")

    return archived_count


# ---------------------------------------------------------------------------
# Task 4: Autonomous Initiation (Proactive Nightly Briefing)
# ---------------------------------------------------------------------------

PROACTIVE_NIGHTLY_GOAL = (
    "Nightly Proactive Consolidation: Audit cross-domain deadlines using detect_deadline_conflicts, "
    "check for deadline conflicts between hackathon and coursework, and synthesize tomorrow's executive briefing."
)


async def trigger_proactive_nightly_run(
    conn: Optional[asyncpg.Connection] = None,
    client: Any = None,
    dry_run: bool = False,
    pool: Any = None,
) -> Optional[dict]:
    """
    Task 4: Autonomous Initiation.
    Trigger a proactive agent run that audits cross-domain deadlines,
    flags upcoming conflicts, and persists the completed run into agent_runs
    so the user sees a ready-to-read executive briefing upon opening Compass.
    """
    if dry_run:
        logger.info("  [4/4] Proactive Nightly Briefing: [DRY-RUN] Would execute autonomous agent run.")
        return {"status": "dry_run", "goal": PROACTIVE_NIGHTLY_GOAL}

    from backend.agent import run_agent

    run_id = f"proactive_nightly_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"  [4/4] Triggering Proactive Nightly Briefing (Run ID: {run_id})...")

    created_pool = False
    if pool is None:
        try:
            pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=2)
            created_pool = True
        except Exception as e:
            logger.warning(f"Failed to create pool for proactive run: {e}")
            return None

    try:
        if client is None and settings.NEBIUS_API_KEY:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=30.0)

        steps = []
        async for step in run_agent(
            goal=PROACTIVE_NIGHTLY_GOAL,
            client=client,
            settings=settings,
            pool=pool,
            run_id=run_id,
            max_steps=6,
            wait_for_confirmation=False,
            enable_critic=False,
        ):
            steps.append(step)

        logger.info(f"  [4/4] ✅ Completed Proactive Nightly Briefing ({len(steps)} steps). Persisted as {run_id}.")
        return {
            "run_id": run_id,
            "status": "completed",
            "steps_count": len(steps),
            "goal": PROACTIVE_NIGHTLY_GOAL,
        }
    except Exception as e:
        logger.error(f"Proactive nightly run failed: {e}")
        return {"run_id": run_id, "status": "failed", "error": str(e)}
    finally:
        if created_pool and pool:
            await pool.close()


# ---------------------------------------------------------------------------
# Task 5: Reactive Slipped Schedule Check
# ---------------------------------------------------------------------------

async def check_slipped_schedules(conn: asyncpg.Connection, pool: Any = None, dry_run: bool = False) -> dict:
    """Find scheduled tasks that passed uncompleted, detect slipped downstream tasks, and log or stage re-plan."""
    from backend.memory.structured import list_tasks, get_all_dependencies_map
    from backend.services.scheduler import find_slipped_tasks, replan_slipped_tasks, get_available_windows
    from backend.services.calendar import get_calendar_freebusy

    tasks = await list_tasks(conn)
    slipped = find_slipped_tasks(tasks)
    if not slipped:
        logger.info("  [5/5] Slipped schedule check: 0 tasks slipped past end time.")
        return {"slipped_count": 0, "affected_count": 0, "rescheduled_count": 0}

    logger.info(f"  [5/5] Found {len(slipped)} slipped task(s) past scheduled_end!")
    dep_map = await get_all_dependencies_map(conn)
    now = datetime.now(timezone.utc)
    busy = await get_calendar_freebusy(now, now + timedelta(days=7), pool=pool)
    windows = get_available_windows(busy, now, now + timedelta(days=7))
    replan = replan_slipped_tasks(slipped, tasks, dependencies=dep_map, available_windows=windows)
    logger.info(f"    ⚡ Reactive re-plan computed: {replan['summary']}")
    return {
        "slipped_count": len(slipped),
        "slipped_task_ids": replan["slipped_task_ids"],
        "affected_count": len(replan["affected_task_ids"]),
        "rescheduled_count": len(replan["rescheduled"]),
    }


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

async def run_consolidation(
    similarity_threshold: float = 0.95,
    stale_thread_days: int = 7,
    dry_run: bool = False,
    pool: Any = None,
) -> dict:
    logger.info("=" * 60)
    logger.info("🧭 Compass — Starting Nightly Memory Consolidation Job")
    logger.info(f"   Similarity Threshold : {similarity_threshold}")
    logger.info(f"   Stale Thread Days    : {stale_thread_days}")
    logger.info(f"   Dry-Run Mode         : {dry_run}")
    logger.info("=" * 60)

    # Initialize OpenAI client if credentials exist
    client = None
    if settings.NEBIUS_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=30.0)
        except Exception as e:
            logger.warning(f"Could not load OpenAI client: {e}")

    conn = await asyncpg.connect(settings.DATABASE_URL)
    await register_vector(conn)

    try:
        overdue_count = await flag_overdue_tasks(conn, dry_run=dry_run)
        pruned_count = await deduplicate_vectors(conn, threshold=similarity_threshold, dry_run=dry_run)
        archived_count = await archive_stale_threads(conn, client, stale_days=stale_thread_days, dry_run=dry_run)
        proactive_res = await trigger_proactive_nightly_run(conn, client, dry_run=dry_run, pool=pool)
        slipped_res = await check_slipped_schedules(conn, pool=pool, dry_run=dry_run)

        logger.info("=" * 60)
        logger.info("SUMMARY OF CONSOLIDATION:")
        logger.info(f"  • Overdue tasks flagged  : {overdue_count}")
        logger.info(f"  • Duplicate chunks pruned: {pruned_count}")
        logger.info(f"  • Stale threads archived : {archived_count}")
        if proactive_res:
            logger.info(f"  • Proactive agent run    : {proactive_res.get('status')} ({proactive_res.get('run_id')})")
        logger.info(f"  • Slipped tasks detected : {slipped_res.get('slipped_count')}")
        logger.info("=" * 60)

        return {
            "overdue_tasks_flagged": overdue_count,
            "duplicate_chunks_merged": pruned_count,
            "stale_conversations_rolled_up": archived_count,
            "proactive_nightly_run": proactive_res,
            "slipped_schedules": slipped_res,
            # Backwards compatibility aliases
            "overdue_tasks": overdue_count,
            "pruned_chunks": pruned_count,
            "archived_threads": archived_count,
        }
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Compass Nightly Consolidation Worker")
    parser.add_argument("--similarity-threshold", type=float, default=0.95, help="Cosine similarity threshold for deduplication (default: 0.95)")
    parser.add_argument("--stale-thread-days", type=int, default=7, help="Inactivity days before archiving a conversation (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without modifying the database")
    args = parser.parse_args()

    asyncio.run(run_consolidation(
        similarity_threshold=args.similarity_threshold,
        stale_thread_days=args.stale_thread_days,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
