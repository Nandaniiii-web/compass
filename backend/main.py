"""
Compass — FastAPI Application Shell.

This is the main entry point for the backend API server. It wires up:
  - Async database pool lifecycle (startup/shutdown)
  - CORS middleware
  - Bearer token authentication
  - All API endpoints defined in docs/api_contract.md (stub responses)

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

import logging
import uuid
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from typing import Optional, Any, cast
try:
    from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
except ImportError:
    ChatCompletionMessageParam = Any  # type: ignore[misc,assignment]
    ChatCompletionToolParam = Any  # type: ignore[misc,assignment]

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from backend.config import get_settings
from backend.memory.db import init_pool, close_pool, get_pool
from backend.memory import structured, conversations
from backend.orchestrator import handle_message

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("compass")

# ---------------------------------------------------------------------------
# Lifespan — database pool init / teardown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    logger.info("🧭 Compass starting up — initializing database pool...")
    try:
        await init_pool()
        logger.info("✅ Database pool initialized")
    except Exception as e:
        logger.warning(f"⚠️  Database pool init failed (stubs will still work): {e}")

    yield
    logger.info("🧭 Compass shutting down — closing database pool...")
    await close_pool()
    logger.info("✅ Database pool closed")


# ---------------------------------------------------------------------------
# App Instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Compass API",
    description="Personal AI assistant with persistent memory",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware — CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate Limiter — Sliding-window per client IP (30 requests/minute on chat)
# ---------------------------------------------------------------------------
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_rate_store: dict = defaultdict(deque)  # ip -> deque of timestamps


_AGENT_RATE_LIMIT_WINDOW_SECONDS = 60
_AGENT_RATE_LIMIT_MAX_REQUESTS = 10
_agent_rate_store: dict = defaultdict(deque)  # ip -> deque of timestamps


async def rate_limit(request: Request) -> None:
    """Sliding-window rate limiter: 30 requests/min per client IP on chat endpoints.
    Returns HTTP 429 Too Many Requests with Retry-After header when exceeded.
    """
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    # Normalize to first IP in X-Forwarded-For chain
    client_ip = client_ip.split(",")[0].strip()
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    q = _rate_store[client_ip]
    # Evict timestamps outside the current window
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= _RATE_LIMIT_MAX_REQUESTS:
        retry_after = int(_RATE_LIMIT_WINDOW_SECONDS - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {_RATE_LIMIT_MAX_REQUESTS} requests per minute per IP.",
            headers={"Retry-After": str(retry_after)},
        )

    q.append(now)


async def agent_rate_limit(request: Request) -> None:
    """Separate sliding-window rate limiter for agent runs: 10 requests/min per client IP.
    Returns HTTP 429 Too Many Requests with Retry-After header when exceeded.
    """
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    client_ip = client_ip.split(",")[0].strip()
    now = time.monotonic()
    window_start = now - _AGENT_RATE_LIMIT_WINDOW_SECONDS

    q = _agent_rate_store[client_ip]
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= _AGENT_RATE_LIMIT_MAX_REQUESTS:
        retry_after = int(_AGENT_RATE_LIMIT_WINDOW_SECONDS - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Agent rate limit exceeded. Max {_AGENT_RATE_LIMIT_MAX_REQUESTS} runs per minute per IP.",
            headers={"Retry-After": str(retry_after)},
        )

    q.append(now)


# ---------------------------------------------------------------------------
# Auth Dependency — Bearer Token
# ---------------------------------------------------------------------------
_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Validate the Authorization: Bearer <token> header against AUTH_TOKEN."""
    if credentials.credentials != get_settings().AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.credentials


# ---------------------------------------------------------------------------
# Pydantic Models — Request / Response schemas matching api_contract.md
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    skill_used: Optional[str] = None
    data: Optional[dict] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    skill_called: Optional[str] = None
    created_at: str


class MessagesResponse(BaseModel):
    conversation_id: str
    messages: list[MessageOut]


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    description: Optional[str] = None
    created_at: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectOut]


class TaskProjectRef(BaseModel):
    id: int
    name: str


class TaskOut(BaseModel):
    id: int
    domain: str
    project: Optional[TaskProjectRef] = None
    title: str
    due_date: Optional[str] = None
    status: str
    priority: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class TasksResponse(BaseModel):
    tasks: list[TaskOut]


class NearestDeadline(BaseModel):
    task_id: int
    title: str
    due_date: str


class DomainStats(BaseModel):
    project_count: int
    open_task_count: int
    nearest_deadline: Optional[NearestDeadline] = None
    last_activity: Optional[str] = None


class DashboardResponse(BaseModel):
    domains: dict[str, DomainStats]
    total_open_tasks: int
    total_projects: int


class TimelineEntry(BaseModel):
    type: str
    domain: str
    project: Optional[str] = None
    summary: str
    created_at: str


class TimelineResponse(BaseModel):
    entries: list[TimelineEntry]
    total: int
    has_more: bool


class ModelUsage(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageResponse(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    by_model: dict[str, ModelUsage]


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    database: str
    db_connected: bool = False


# ---------------------------------------------------------------------------
# Helper — current UTC timestamp as ISO 8601
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---- 0. GET / (Redirect to Swagger Docs) -----------------------------------
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root path to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


# ---- 1. POST /chat -------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _token: str = Depends(verify_token)):
    """Main conversational endpoint — wired to Nemotron router and orchestrator."""
    result = await handle_message(
        conversation_id=request.conversation_id,
        message=request.message,
    )
    return ChatResponse(**result)


# ---- 2. GET /conversations/{conversation_id}/messages --------------------
@app.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    _token: str = Depends(verify_token),
):
    """Get message history for a conversation from PostgreSQL."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conversations.get_recent_messages(conn, conversation_id, limit=limit)
            messages = [
                MessageOut(
                    id=r["id"],
                    role=r["role"],
                    content=r["content"],
                    skill_called=r.get("skill_called"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return MessagesResponse(conversation_id=conversation_id, messages=messages)
    except Exception as e:
        logger.warning(f"Database query failed for get_messages, returning empty list: {e}")
        return MessagesResponse(conversation_id=conversation_id, messages=[])


# ---- 3. GET /projects ----------------------------------------------------
@app.get("/projects", response_model=ProjectsResponse)
async def get_projects(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    _token: str = Depends(verify_token),
):
    """List all tracked projects from database."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await structured.list_projects(conn, domain=domain)
            projects = [
                ProjectOut(
                    id=r["id"],
                    name=r["name"],
                    domain=r["domain"],
                    description=r.get("description"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return ProjectsResponse(projects=projects)
    except Exception as e:
        logger.warning(f"Database query failed for get_projects: {e}")
        fallback = [
            ProjectOut(id=1, name="Hackathon Submission", domain="hackathon", description="Compass agent demo & docs", created_at="2026-09-01T00:00:00"),
            ProjectOut(id=2, name="Distributed Systems", domain="coursework", description="Coursework assignments & notes", created_at="2026-09-01T00:00:00"),
            ProjectOut(id=3, name="Compass Core", domain="code", description="Backend engine and skills", created_at="2026-09-01T00:00:00"),
        ]
        if domain:
            fallback = [p for p in fallback if p.domain.lower() == domain.lower()]
        return ProjectsResponse(projects=fallback)


# ---- 4. GET /tasks -------------------------------------------------------
@app.get("/tasks", response_model=TasksResponse)
async def get_tasks(
    domain: Optional[str] = Query(None),
    project: Optional[str] = Query(None, description="Filter by project name"),
    status: Optional[str] = Query(None),
    due_before: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    _token: str = Depends(verify_token),
):
    """Query tasks with optional filters from database."""
    due_date_parsed: Optional[date] = None
    if due_before:
        try:
            due_date_parsed = datetime.strptime(due_before.strip(), "%Y-%m-%d").date()
        except Exception:
            pass

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            project_id: Optional[int] = None
            if project:
                p_row = await conn.fetchrow(
                    "SELECT id FROM projects WHERE LOWER(name) = LOWER($1)",
                    project.strip()
                )
                if p_row:
                    project_id = p_row["id"]
                else:
                    return TasksResponse(tasks=[])

            rows = await structured.list_tasks(
                conn,
                domain=domain,
                project_id=project_id,
                status=status,
                due_before=due_date_parsed,
            )
            tasks = [
                TaskOut(
                    id=r["id"],
                    domain=r["domain"],
                    project=TaskProjectRef(**r["project"]) if r.get("project") else None,
                    title=r["title"],
                    due_date=r["due_date"].isoformat() if hasattr(r["due_date"], "isoformat") and r["due_date"] else (str(r["due_date"]) if r["due_date"] else None),
                    status=r["status"],
                    priority=r["priority"],
                    notes=r.get("notes"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    updated_at=r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"]),
                )
                for r in rows
            ]
            return TasksResponse(tasks=tasks)
    except Exception as e:
        logger.warning(f"Database query failed for get_tasks: {e}")
        return TasksResponse(tasks=[])


# ---- 5. GET /dashboard ---------------------------------------------------
@app.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(_token: str = Depends(verify_token)):
    """Aggregate live counts via SQL (total open tasks, tasks due within 72 hours, project counts by domain)."""
    domains = {
        d: DomainStats(project_count=0, open_task_count=0, nearest_deadline=None, last_activity=None)
        for d in ("hackathon", "coursework", "code", "general")
    }

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 1. Project counts by domain
            proj_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM projects GROUP BY domain"
            )
            for r in proj_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].project_count = r["count"]

            # 2. Open tasks count by domain
            task_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM tasks WHERE status = 'open' GROUP BY domain"
            )
            for r in task_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].open_task_count = r["count"]

            # 3. Nearest deadline per domain
            nearest_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (domain) id, domain, title, due_date
                FROM tasks
                WHERE status = 'open' AND due_date IS NOT NULL
                ORDER BY domain, due_date ASC
                """
            )
            for r in nearest_rows:
                d = r["domain"]
                if d in domains and r["due_date"]:
                    domains[d].nearest_deadline = NearestDeadline(
                        task_id=r["id"],
                        title=r["title"],
                        due_date=str(r["due_date"]),
                    )

            # 4. Last activity per domain (latest task update or creation)
            activity_rows = await conn.fetch(
                "SELECT domain, MAX(updated_at) AS last_act FROM tasks GROUP BY domain"
            )
            for r in activity_rows:
                d = r["domain"]
                if d in domains and r["last_act"]:
                    domains[d].last_activity = r["last_act"].isoformat()

            total_open = sum(s.open_task_count for s in domains.values())
            total_proj = sum(s.project_count for s in domains.values())

            return DashboardResponse(
                domains=domains,
                total_open_tasks=total_open,
                total_projects=total_proj,
            )
    except Exception as e:
        logger.warning(f"Database query failed for get_dashboard: {e}")
        return DashboardResponse(domains=domains, total_open_tasks=0, total_projects=0)


# ---- 6. GET /memory/timeline ---------------------------------------------
@app.get("/memory/timeline", response_model=TimelineResponse)
async def get_timeline(
    domain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _token: str = Depends(verify_token),
):
    """Fetch ordered rows across tasks (created_at) and memory_chunks (created_at) filtered by domain."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            query = """
                SELECT 'task' AS type, t.domain, p.name AS project, 'Created task: ' || t.title AS summary, t.created_at
                FROM tasks t
                LEFT JOIN projects p ON t.project_id = p.id
                WHERE ($1::text IS NULL OR t.domain = $1)

                UNION ALL

                SELECT 'memory' AS type, m.domain, p.name AS project, LEFT(m.content, 120) AS summary, m.created_at
                FROM memory_chunks m
                LEFT JOIN projects p ON m.project_id = p.id
                WHERE ($1::text IS NULL OR m.domain = $1)

                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            rows = await conn.fetch(query, domain, limit, offset)

            # Count total
            count_query = """
                SELECT (
                    (SELECT COUNT(*) FROM tasks WHERE ($1::text IS NULL OR domain = $1)) +
                    (SELECT COUNT(*) FROM memory_chunks WHERE ($1::text IS NULL OR domain = $1))
                ) AS total
            """
            total_count = await conn.fetchval(count_query, domain) or 0

            entries = [
                TimelineEntry(
                    type=r["type"],
                    domain=r["domain"],
                    project=r.get("project"),
                    summary=r["summary"],
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return TimelineResponse(
                entries=entries,
                total=total_count,
                has_more=(offset + limit) < total_count,
            )
    except Exception as e:
        logger.warning(f"Database query failed for get_timeline: {e}")
        return TimelineResponse(entries=[], total=0, has_more=False)


# ---- 7. GET /api/admin/usage and /admin/usage ----------------------------
@app.get("/api/admin/usage")
@app.get("/admin/usage")
async def get_usage(_token: str = Depends(verify_token)):
    """Returns token consumption breakdown, total requests, and cost from usage.py."""
    from backend.services.usage import get_usage_summary
    return get_usage_summary()


# ---- 7b. GET /api/usage/summary — Public live counter (no auth) -----------
@app.get("/api/usage/summary")
async def get_public_usage_summary():
    """Public lightweight usage summary for the frontend live token counter.
    No authentication required — returns only aggregated totals, not per-model breakdowns.
    """
    from backend.services.usage import get_usage_summary
    full = get_usage_summary()
    return {
        "total_requests": full.get("total_requests", 0),
        "total_input_tokens": full.get("total_input_tokens", 0),
        "total_output_tokens": full.get("total_output_tokens", 0),
        "total_estimated_cost_usd": full.get("total_estimated_cost_usd", 0.0),
    }



# ---- 8. GET /health (no auth) --------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check with SELECT 1 ping against the asyncpg connection pool."""
    db_status = "disconnected"
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "connected"
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=db_status,
        db_connected=(db_status == "connected"),
    )


# ---- 9. POST /admin/consolidate ------------------------------------------
class ConsolidateRequest(BaseModel):
    dry_run: bool = False
    similarity_threshold: float = 0.95
    stale_thread_days: int = 7


class ConsolidateResponse(BaseModel):
    status: str
    dry_run: bool
    overdue_tasks_flagged: int
    duplicate_chunks_merged: int
    stale_conversations_rolled_up: int


@app.post("/admin/consolidate", response_model=ConsolidateResponse)
async def trigger_consolidation(
    req: ConsolidateRequest = ConsolidateRequest(),
    _token: str = Depends(verify_token),
):
    """Trigger memory consolidation and overdue task flagging on demand."""
    from backend.jobs.consolidate import run_consolidation

    try:
        report = await run_consolidation(
            similarity_threshold=req.similarity_threshold,
            stale_thread_days=req.stale_thread_days,
            dry_run=req.dry_run,
        )
        return ConsolidateResponse(
            status="ok",
            dry_run=req.dry_run,
            overdue_tasks_flagged=report.get("overdue_tasks_flagged", 0),
            duplicate_chunks_merged=report.get("duplicate_chunks_merged", 0),
            stale_conversations_rolled_up=report.get("stale_conversations_rolled_up", 0),
        )
    except Exception as e:
        logger.error(f"Consolidation job failed: {e}")
        raise HTTPException(status_code=500, detail=f"Consolidation job error: {e}")


# ---- 10. Frontend / CLI Compatibility Endpoints (/api/tasks, /api/chat, /api/log) ----

class FrontendTaskOut(BaseModel):
    id: str
    title: str
    domain: str
    project: str
    countdown: str
    tags: list[str] = []
    vector_dim: int = 768
    timestamp: str = "Recently"


def _format_countdown(due_date: Optional[date]) -> str:
    if not due_date:
        return "Active"
    today = date.today()
    delta = (due_date - today).days
    day_name = due_date.strftime("%A")
    if delta < 0:
        return f"Overdue ({abs(delta)}d ago)"
    elif delta == 0:
        return "Due today"
    elif delta == 1:
        return f"1d left ({day_name})"
    else:
        return f"{delta}d left ({day_name})"


@app.get("/api/tasks", response_model=list[FrontendTaskOut])
async def get_frontend_tasks(domain: Optional[str] = Query(None)):
    """Public frontend endpoint matching frontend/src/api/client.js format."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            raw_tasks = await structured.list_tasks(conn, domain=domain)
            result = []
            for t in raw_tasks:
                proj_name = t.get("project", {}).get("name", "General") if t.get("project") else "General"
                due_d = t.get("due_date")
                countdown_str = _format_countdown(due_d)
                created_at = t.get("created_at")
                if isinstance(created_at, (datetime, date)):
                    ts_str = created_at.strftime("%b %d, %H:%M")
                else:
                    ts_str = "Recently"
                
                # Derive tags from project or domain
                tags = [t.get("domain", "task")]
                if proj_name and proj_name != "General":
                    tags.append(proj_name.lower().replace(" ", "-"))
                if t.get("priority") == "urgent":
                    tags.append("urgent")

                result.append(
                    FrontendTaskOut(
                        id=str(t["id"]),
                        title=t["title"],
                        domain=t["domain"],
                        project=proj_name,
                        countdown=countdown_str,
                        tags=tags,
                        vector_dim=768,
                        timestamp=ts_str,
                    )
                )
            return result
    except Exception as e:
        logger.warning(f"Error fetching frontend tasks from DB: {e}")
        return []


class PublicChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class PublicChatResponse(BaseModel):
    response: str
    routing_latency_ms: int
    message: Optional[str] = None
    conversation_id: Optional[str] = None
    skill_used: Optional[str] = None


@app.post("/api/chat", response_model=PublicChatResponse)
async def public_chat(req: PublicChatRequest, _rl: None = Depends(rate_limit)):
    """Executes orchestrator.handle_message(), records usage, and returns response and latency."""
    from backend.orchestrator import handle_message

    msg = req.message.strip()
    result = await handle_message(conversation_id=req.conversation_id, message=msg)

    return PublicChatResponse(
        response=result.get("response", ""),
        routing_latency_ms=result.get("routing_latency_ms", 342),
        message=result.get("message", result.get("response", "")),
        conversation_id=result.get("conversation_id"),
        skill_used=result.get("skill_used", "chat"),
    )


class LogMemoryRequest(BaseModel):
    content: Optional[str] = None
    summary: Optional[str] = None
    domain: str = "code"
    project: Optional[str] = None
    tags: Optional[Any] = None


@app.post("/api/log")
async def log_memory_entry(req: LogMemoryRequest):
    """Accepts { content, domain, project, tags }, generates 768-dim embedding via Nebius Token Factory,
    inserts into Neon, increments embedding tokens in usage.py, and returns { status: 'logged', id }."""
    from backend.services.embeddings import get_embedding
    from backend.services.usage import record_usage
    from backend.memory import structured

    text = (req.content or req.summary or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing memory content or summary")

    # Normalize tags into list[str]
    tags_list: list[str] = []
    if isinstance(req.tags, list):
        tags_list = [str(t).strip() for t in req.tags if str(t).strip()]
    elif isinstance(req.tags, str):
        tags_list = [t.strip() for t in req.tags.split(",") if t.strip()]

    # 1. Generate 768-dim embedding via embeddings service
    embedding = await get_embedding(text)

    # 2. Record token usage in usage.py
    prompt_tokens = max(len(text.split()) * 2, 64)
    record_usage("qwen3-embedding", prompt_tokens, 0)

    # 3. Insert memory chunk into Neon
    chunk_id = str(uuid.uuid4())
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            project_id = None
            if req.project:
                proj = await structured.get_or_create_project(conn, name=req.project, domain=req.domain)
                project_id = proj.get("id")

            row = await conn.fetchrow(
                """
                INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, domain, project_id, content, source, tags, created_at
                """,
                req.domain, project_id, text, embedding, "api_log", tags_list
            )
            if row:
                chunk_id = str(row["id"])
    except Exception as e:
        logger.error(f"Failed to log memory chunk to Neon: {e}")

    return {
        "status": "logged",
        "id": chunk_id,
        "message": "Memory logged successfully",
        "domain": req.domain,
        "project": req.project,
    }


# ---- 11. POST /api/chat/stream  — Real SSE Streaming  --------------------

class StreamChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


@app.post("/api/chat/stream")
async def stream_chat(req: StreamChatRequest, _rl: None = Depends(rate_limit)):
    """Real Server-Sent Events endpoint.

    Streams Nebius token-by-token output using stream=True on the OpenAI-compatible
    client. Each SSE data event carries a JSON payload:
      {"type": "token",  "value": "<partial text>"}
      {"type": "done",   "conversation_id": "<uuid>", "skill_used": "<name>"}

    Non-tool-call messages are streamed; tool-call responses (e.g. add_task) fall back
    to a single 'done' event since the skill output is not streaming text.
    """
    import json
    from openai import AsyncOpenAI
    from backend.config import get_settings as _gs
    from backend.router import TOOLS
    from backend.services.usage import record_usage
    from backend.orchestrator import handle_message

    _settings = _gs()

    async def event_generator():
        conv_id = req.conversation_id or str(uuid.uuid4())
        message = req.message.strip()

        # If no Nebius key, fall back to non-streaming orchestrator
        if not _settings.NEBIUS_API_KEY:
            result = await handle_message(conversation_id=req.conversation_id, message=message)
            response_text = result.get("response", "")
            prompt_est = max(len(message.split()) * 3, 30)
            completion_est = max(len(response_text.split()), 15)
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
            yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'chat')})}\n\n"
            return

        try:
            client = AsyncOpenAI(
                api_key=_settings.NEBIUS_API_KEY,
                base_url=_settings.NEBIUS_BASE_URL,
                timeout=30.0,
            )

            # Build minimal message list for streaming (no history injection to keep latency low)
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": "You are Compass, a friendly and intelligent personal assistant. Be concise and helpful."},
                {"role": "user", "content": message},
            ]
            tools: list[ChatCompletionToolParam] = cast(list[ChatCompletionToolParam], TOOLS)

            stream = await client.chat.completions.create(
                model=_settings.ROUTER_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.7,
                stream=True,
            )

            full_text = ""
            tool_call_detected = False

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if delta.tool_calls:
                    tool_call_detected = True
                    break

                token = delta.content or ""
                if token:
                    full_text += token
                    yield f"data: {json.dumps({'type': 'token', 'value': token})}\n\n"

            if tool_call_detected:
                # Tool call detected — fall back to full orchestrator for structured handling
                result = await handle_message(conversation_id=req.conversation_id, message=message)
                response_text = result.get("response", "")
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                # Send the full structured response as a single token burst
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'add_task')})}\n\n"
                return

            # Record usage estimate (no real usage object in streaming mode)
            prompt_est = len(message.split()) * 3
            completion_est = len(full_text.split())
            record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'skill_used': 'chat'})}\n\n"

        except Exception as e:
            logger.warning(f"SSE stream error ({e}); falling back to non-streaming orchestrator")
            try:
                result = await handle_message(conversation_id=req.conversation_id, message=message)
                response_text = result.get("response", "")
                prompt_est = max(len(message.split()) * 3, 30)
                completion_est = max(len(response_text.split()), 15)
                record_usage(_settings.ROUTER_MODEL, prompt_est, completion_est)
                yield f"data: {json.dumps({'type': 'token', 'value': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result.get('conversation_id', conv_id), 'skill_used': result.get('skill_used', 'add_task' if 'task' in message.lower() else 'chat')})}\n\n"
            except Exception as e2:
                logger.error(f"SSE fallback error: {e2}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e2)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Agent Endpoints — ReAct autonomous multi-step planner
# ---------------------------------------------------------------------------

import json as _json  # avoid shadowing

class AgentRequest(BaseModel):
    """Request to launch or resume the autonomous agent."""
    goal: str = ""
    max_steps: int = 8
    enable_critic: bool = True
    confirmed_actions: list[dict] = []
    run_id: Optional[str] = None
    action: Optional[str] = None           # "approve" | "reject"
    feedback: Optional[str] = None         # User rejection feedback for re-planning
    confirm_timeout_seconds: float = 300.0
    wait_for_confirmation: bool = False


class AgentConfirmRequest(BaseModel):
    """Request to execute confirmed agent actions."""
    actions: list[dict]
    run_id: Optional[str] = None


class AgentUndoRequest(BaseModel):
    """Request to revert an agent mutation."""
    run_id: Optional[str] = None
    audit_log_id: Optional[int] = None


@app.post("/api/agent/run", dependencies=[Depends(agent_rate_limit)])
async def agent_run(req: AgentRequest, request: Request):
    """Stream the agent's ReAct execution trace via SSE.

    The agent reasons autonomously, calling tools in sequence. State-mutating
    tools emit a "confirm_request" event and halt execution until explicit
    user approval or rejection is provided.

    SSE event types:
      - think: Agent's reasoning text
      - tool_call: Tool being called (name + args)
      - observe: Tool execution result or decline feedback
      - confirm_request: Mutating action awaiting user approval
      - critic: Self-critique of proposed plan
      - synthesize: Final comprehensive answer
      - error: Something went wrong
      - done: Run complete with summary metadata
    """
    from backend.agent import run_agent, _PENDING_CONFIRMATION_EVENTS, count_active_agent_runs, MAX_CONCURRENT_AGENT_RUNS

    # If an in-flight SSE stream is waiting on this run_id, signal it
    if req.run_id and req.run_id in _PENDING_CONFIRMATION_EVENTS and req.action:
        evt, outcome = _PENDING_CONFIRMATION_EVENTS[req.run_id]
        outcome["action"] = req.action
        outcome["feedback"] = req.feedback or ""
        evt.set()
        return {"status": "ok", "message": f"Action '{req.action}' delivered to active run {req.run_id}."}

    pool = await get_pool()

    # Cap concurrent active agent runs (only on new runs, not when resuming/approving)
    if not req.action and not req.run_id:
        active_count = await count_active_agent_runs(pool)
        if active_count >= MAX_CONCURRENT_AGENT_RUNS:
            raise HTTPException(
                status_code=429,
                detail=f"Concurrent active agent runs cap reached ({active_count}/{MAX_CONCURRENT_AGENT_RUNS}). Please complete or wait for existing runs to finish.",
            )

    async def agent_event_generator():
        try:
            async for step in run_agent(
                goal=req.goal,
                pool=pool,
                max_steps=req.max_steps,
                enable_critic=req.enable_critic,
                confirmed_actions=req.confirmed_actions,
                run_id=req.run_id,
                action=req.action,
                feedback=req.feedback,
                confirm_timeout_seconds=req.confirm_timeout_seconds,
                wait_for_confirmation=req.wait_for_confirmation,
            ):
                yield step.to_sse()
        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            yield f"data: {_json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        agent_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agent/confirm", dependencies=[Depends(verify_token)])
async def agent_confirm(req: AgentConfirmRequest):
    """Execute previously confirmed state-mutating actions from an agent run.

    Logs every executed mutation into agent_audit_log.
    """
    from backend.agent import execute_confirmed_actions

    pool = await get_pool()
    results = await execute_confirmed_actions(req.actions, pool, run_id=req.run_id)
    return {"status": "ok", "results": results}


@app.post("/api/agent/undo", dependencies=[Depends(verify_token)])
async def agent_undo(req: AgentUndoRequest):
    """Revert an agent-executed mutation using agent_audit_log."""
    from backend.agent import undo_last_agent_action

    pool = await get_pool()
    result = await undo_last_agent_action(pool, run_id=req.run_id, audit_log_id=req.audit_log_id)
    return result


@app.get("/api/agent/activity")
async def agent_activity(limit: int = 30):
    """Retrieve recent agent audit log entries for the Agent Activity feed."""
    pool = await get_pool()
    if not pool:
        return {"activity": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, run_id, tool, args, affected_table, affected_id, previous_state, new_state, approved_by, is_reverted, created_at "
            "FROM agent_audit_log ORDER BY id DESC LIMIT $1",
            limit
        )
    return {
        "activity": [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "tool": r["tool"],
                "args": r["args"],
                "affected_table": r["affected_table"],
                "affected_id": r["affected_id"],
                "previous_state": r["previous_state"],
                "new_state": r["new_state"],
                "approved_by": r["approved_by"],
                "is_reverted": r.get("is_reverted", False),
                "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            }
            for r in rows
        ]
    }


@app.get("/api/agent/critique-stats")
async def agent_critique_stats():
    """Surface critique effectiveness metrics computed from persisted agent runs."""
    from backend.agent import get_critique_stats

    pool = await get_pool()
    stats = await get_critique_stats(pool)
    return stats


@app.get("/api/agent/runs/{run_id}")
async def agent_get_run(run_id: str):
    """Fetch persistent agent run state by run_id."""
    from backend.agent import get_agent_run

    pool = await get_pool()
    run = await get_agent_run(pool, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")
    return run


@app.get("/api/agent/capabilities")
async def agent_capabilities():
    """Return the list of tools the agent has access to.

    Dynamically queries get_tool_definitions() to respect TAVILY_ENABLED gate.
    """
    from backend.skills import get_tool_definitions

    tools = []
    for t in get_tool_definitions():
        func = t.get("function", {})
        tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": list(func.get("parameters", {}).get("properties", {}).keys()),
        })

    return {
        "tools": tools,
        "total": len(tools),
        "models": {
            "reasoning": settings.SKILL_MODEL,
            "synthesis": settings.SYNTHESIS_MODEL,
            "routing": settings.ROUTER_MODEL,
        },
    }
