"""
Compass — Gap Closures Test Suite.

Automated verification tests for all gap closures:
1. P0.1: Server-side task query filtering via ?domain= parameter.
2. P0.2: Public /api/usage/summary endpoint returning dynamic telemetry.
3. P1.4: Per-IP sliding-window rate limiting returning HTTP 429 after 30 req/min.
4. P2.7: SSE streaming endpoint and CLI live streaming parser.
5. P2.8: Tavily search_web skill tool definition and execution fallback.
"""

import json
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_server_side_task_domain_filter(client: AsyncClient, auth_headers: dict):
    """P0.1: Verify /tasks and /api/tasks accept domain query parameter."""
    # Test unauthenticated public /api/tasks
    resp = await client.get("/api/tasks?domain=hackathon")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for task in data:
        assert task.get("domain") in ("hackathon", "general")

    # Test authenticated /tasks?domain=coursework
    resp_auth = await client.get("/tasks?domain=coursework", headers=auth_headers)
    assert resp_auth.status_code == 200
    tasks_data = resp_auth.json().get("tasks", [])
    for task in tasks_data:
        assert task.get("domain") == "coursework"


@pytest.mark.asyncio
async def test_public_usage_summary_endpoint(client: AsyncClient):
    """P0.2: Verify GET /api/usage/summary is public and returns aggregated metrics."""
    resp = await client.get("/api/usage/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert "total_requests" in summary
    assert "total_input_tokens" in summary
    assert "total_output_tokens" in summary
    assert "total_estimated_cost_usd" in summary
    assert isinstance(summary["total_requests"], int)
    assert isinstance(summary["total_estimated_cost_usd"], (int, float))


@pytest.mark.asyncio
async def test_per_ip_rate_limiting_exceeded(client: AsyncClient, monkeypatch):
    """P1.4: Verify sliding-window rate limiter returns 429 after 30 rapid requests."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "backend.orchestrator.handle_message",
        AsyncMock(return_value={"response": "pong", "conversation_id": "mock-conv", "skill_used": "chat"}),
    )

    test_ip = "198.51.100.42"
    headers = {"X-Forwarded-For": test_ip}

    # First 30 requests should succeed (HTTP 200)
    for _ in range(30):
        resp = await client.post(
            "/api/chat",
            json={"message": "ping"},
            headers=headers,
        )
        assert resp.status_code == 200

    # The 31st request from the same IP MUST trigger HTTP 429 Too Many Requests
    resp_blocked = await client.post(
        "/api/chat",
        json={"message": "burst ping"},
        headers=headers,
    )
    assert resp_blocked.status_code == 429
    assert "Rate limit exceeded" in resp_blocked.text
    assert "Retry-After" in resp_blocked.headers


@pytest.mark.asyncio
async def test_search_web_skill_registered_and_dispatchable(monkeypatch):
    """P2.8: Verify search_web feature-flag gating and handler execution."""
    from backend.skills import TOOL_DEFINITIONS, SKILL_REGISTRY, dispatch_skill, get_tool_definitions, SEARCH_WEB_TOOL
    from backend.config import get_settings

    # By default, search_web is gated OFF and not in TOOL_DEFINITIONS
    tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS if "function" in t]
    assert "search_web" not in tool_names

    # When TAVILY_ENABLED is True, get_tool_definitions includes search_web
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ENABLED", True)
    active_tools = get_tool_definitions()
    assert any(t["function"]["name"] == "search_web" for t in active_tools if "function" in t)

    # Verify skill handler is registered in SKILL_REGISTRY
    assert "search_web" in SKILL_REGISTRY

    # Dispatch with empty query
    res = await dispatch_skill("search_web", {"query": ""}, None)
    assert "Please provide a search query" in res["response"]

    # Dispatch with TAVILY_ENABLED=True to exercise execution path directly
    res_enabled = await dispatch_skill("search_web", {"query": "latest AI news"}, None)
    assert "response" in res_enabled
    assert "data" in res_enabled

    # Dispatch with TAVILY_ENABLED=False to verify clean disabled response
    monkeypatch.setattr(settings, "TAVILY_ENABLED", False)
    res_disabled = await dispatch_skill("search_web", {"query": "latest AI news"}, None)
    assert "currently disabled" in res_disabled["response"]


def test_cli_streaming_helper_fallback():
    """P2.7: Verify CLI _stream_chat gracefully handles synchronous fallback."""
    from cli.assistant_cli import _stream_chat

    # Call with a simple query against running server
    text, conv_id, skill = _stream_chat({"message": "Hello Compass!"})
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_usage_summary_cost_delta_changes_across_turns(client: AsyncClient):
    """Item 15: Verify total_estimated_cost_usd actively increments with token volume.
    
    Proves the cost counter is live and not frozen by asserting a measurable cost delta
    between a small turn and a heavy multi-domain synthesis turn.
    """
    from backend.services.usage import get_usage_summary, record_usage
    from backend.config import get_settings

    settings = get_settings()

    # Step 1: Initial cost reading from /api/usage/summary
    resp1 = await client.get("/api/usage/summary")
    assert resp1.status_code == 200
    cost_initial = resp1.json()["total_estimated_cost_usd"]

    # Step 2: Turn 1 (short greeting on Router Nano: 20 in, 10 out)
    record_usage(settings.ROUTER_MODEL, 20, 10)
    resp2 = await client.get("/api/usage/summary")
    cost_after_turn1 = resp2.json()["total_estimated_cost_usd"]
    assert cost_after_turn1 > cost_initial

    # Step 3: Turn 2 (heavy synthesis on Ultra: 1500 prompt, 800 completion tokens)
    record_usage(settings.SYNTHESIS_MODEL, 1500, 800)
    resp3 = await client.get("/api/usage/summary")
    cost_after_turn2 = resp3.json()["total_estimated_cost_usd"]

    # Assert cost meaningfully changed and delta reflects Ultra pricing
    cost_delta = cost_after_turn2 - cost_after_turn1
    assert cost_delta > 0.001, f"Expected noticeable cost delta on heavy synthesis turn, got {cost_delta}"
    assert cost_after_turn2 > cost_after_turn1 > cost_initial


@pytest.mark.asyncio
async def test_query_coursework_notes_sets_coursework_domain(monkeypatch):
    """Gap 3 Fix: Verify query_coursework_notes specifically queries domain='coursework'."""
    from backend.skills import dispatch_skill
    from backend.memory.db import get_pool
    from unittest.mock import AsyncMock

    pool = await get_pool()
    captured_args = {}

    async def mock_search_chunks(conn, query, domain=None, limit=5):
        captured_args["query"] = query
        captured_args["domain"] = domain
        return []

    monkeypatch.setattr("backend.memory.vector.search_chunks", mock_search_chunks)

    result = await dispatch_skill("query_coursework_notes", {"course": "CS 61C", "notes": "RISC-V"}, pool)
    assert captured_args.get("domain") == "coursework"
    assert captured_args.get("query") in ("CS 61C", "RISC-V")
    assert "response" in result


@pytest.mark.asyncio
async def test_summarize_across_domains_aggregates_multidomain_data():
    """Gap 4 Fix: Verify summarize_across_domains pre-aggregates tasks, code chunks, and coursework."""
    from backend.skills import dispatch_skill
    from backend.memory.db import get_pool

    pool = await get_pool()
    result = await dispatch_skill("summarize_across_domains", {}, pool)
    assert "response" in result
    assert "data" in result
    data = result["data"]
    assert "open_tasks_by_domain" in data
    assert "code_chunks_count" in data
    assert "coursework_chunks_count" in data
    assert "projects_count" in data


@pytest.mark.asyncio
async def test_agent_confirm_and_undo_public_access(client: AsyncClient):
    """Gap 5 & 7 Fix: Verify /api/agent/confirm and /api/agent/undo can be accessed without auth headers."""
    # Confirm endpoint without token should not return 401 Unauthorized
    resp_confirm = await client.post(
        "/api/agent/confirm",
        json={"actions": [], "run_id": "test_public_confirm"},
    )
    assert resp_confirm.status_code == 200

    # Undo endpoint without token should not return 401 Unauthorized
    resp_undo = await client.post(
        "/api/agent/undo",
        json={"run_id": "nonexistent_run_id"},
    )
    assert resp_undo.status_code == 200
    assert resp_undo.json().get("status") in ("ok", "noop", "error")


def test_config_pricing_matches_usage_pricing():
    """Gap 5 Fix: Verify config.py pricing matches usage.py pricing catalog."""
    from backend.config import get_settings
    from backend.services.usage import PRICING_PER_1M

    settings = get_settings()
    for model_id, in_cost in settings.COST_PER_1M_INPUT.items():
        if model_id in PRICING_PER_1M:
            assert PRICING_PER_1M[model_id]["prompt"] == in_cost
    for model_id, out_cost in settings.COST_PER_1M_OUTPUT.items():
        if model_id in PRICING_PER_1M:
            assert PRICING_PER_1M[model_id]["completion"] == out_cost


@pytest.mark.asyncio
async def test_detect_deadline_conflicts_skill():
    """Enhancement 8: Verify detect_deadline_conflicts skill scans tasks and returns structured conflicts."""
    from backend.skills import dispatch_skill
    from backend.memory.db import get_pool
    from backend.memory import structured
    from datetime import date, timedelta
    import uuid

    pool = await get_pool()
    tomorrow_date = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow_date.isoformat()
    t1_title = f"Test Hackathon Deadline {uuid.uuid4().hex[:6]}"
    t2_title = f"Test Coursework Exam {uuid.uuid4().hex[:6]}"

    async with pool.acquire() as conn:
        t1 = await structured.create_task(conn, domain="hackathon", title=t1_title, due_date=tomorrow_date, priority="urgent")
        t2 = await structured.create_task(conn, domain="coursework", title=t2_title, due_date=tomorrow_date, priority="high")
        id1 = t1["id"]
        id2 = t2["id"]

    try:
        result = await dispatch_skill("detect_deadline_conflicts", {"days_ahead": 3}, pool)
        assert "response" in result
        assert "data" in result
        data = result["data"]
        assert "conflicts" in data
        assert data["conflicts_count"] >= 1
        # Check that tomorrow's conflict was detected
        matching_conflicts = [c for c in data["conflicts"] if c["date"] == tomorrow_str]
        assert len(matching_conflicts) >= 1
        assert matching_conflicts[0]["severity"] in ("critical", "moderate")
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE id = ANY($1)", [id1, id2])


@pytest.mark.asyncio
async def test_agent_runs_list_endpoint(client: AsyncClient):
    """Enhancement 5: Verify GET /api/agent/runs lists recent runs for the Run History panel."""
    resp = await client.get("/api/agent/runs?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "total" in data
    assert isinstance(data["runs"], list)
    if data["runs"]:
        r = data["runs"][0]
        assert "id" in r
        assert "goal" in r
        assert "status" in r
        assert "steps_count" in r


@pytest.mark.asyncio
async def test_agent_conversation_memory_injection(monkeypatch):
    """Enhancement 6: Verify run_agent injects recent conversation messages when conversation_id is provided."""
    from backend.agent import run_agent
    from backend.memory.db import get_pool
    from unittest.mock import MagicMock, AsyncMock
    import uuid

    pool = await get_pool()
    conv_id = str(uuid.uuid4())

    # Seed conversation messages
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations (id) VALUES ($1) ON CONFLICT (id) DO NOTHING
            """,
            conv_id
        )
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content)
            VALUES ($1, 'user', 'I need to prepare for my CS 61C midterm tomorrow')
            """,
            conv_id
        )

    try:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="Planning schedule with midterm context", tool_calls=[]))],
            usage=MagicMock(prompt_tokens=10, completion_tokens=10),
        ))

        steps = []
        async for s in run_agent(
            goal="Help me prioritize my week",
            pool=pool,
            client=mock_client,
            conversation_id=conv_id,
            max_steps=2,
            enable_critic=False,
            wait_for_confirmation=False,
        ):
            steps.append(s)

        # Verify the OpenAI client received prompt containing recent conversation context
        assert mock_client.chat.completions.create.called
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        msgs = call_kwargs.get("messages", [])
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        assert "CS 61C midterm" in user_msgs[0]["content"]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM messages WHERE conversation_id = $1", conv_id)
            await conn.execute("DELETE FROM conversations WHERE id = $1", conv_id)


@pytest.mark.asyncio
async def test_agent_runs_conversation_id_filtering(client: AsyncClient):
    """Verify GET /api/agent/runs accurately persists and filters by conversation_id."""
    from backend.agent import save_agent_run
    from backend.memory.db import get_pool
    import uuid

    pool = await get_pool()
    test_conv_id = str(uuid.uuid4())
    test_run_id = f"test_run_conv_{uuid.uuid4().hex[:8]}"

    await save_agent_run(
        pool=pool,
        run_id=test_run_id,
        goal="Test run linked to conversation",
        status="completed",
        accumulated_steps=[],
        messages=[],
        pending_actions=[],
        conversation_id=test_conv_id,
    )

    try:
        # 1. Fetch filtered by conversation_id
        resp = await client.get(f"/api/agent/runs?conversation_id={test_conv_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        matched = [r for r in data["runs"] if r["id"] == test_run_id]
        assert len(matched) == 1
        assert matched[0]["conversation_id"] == test_conv_id

        # 2. Fetch with non-matching conversation_id
        resp_empty = await client.get("/api/agent/runs?conversation_id=nonexistent_conv_id_123")
        assert resp_empty.status_code == 200
        assert resp_empty.json()["total"] == 0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_runs WHERE id = $1", test_run_id)


def test_cli_agent_runs_and_briefing_commands():
    """Verify CLI commands `agent-runs` and `agent-briefing` execute cleanly."""
    from typer.testing import CliRunner
    from cli.assistant_cli import app

    runner = CliRunner()

    # Test agent-runs command
    res_runs = runner.invoke(app, ["agent-runs", "-n", "5"])
    assert res_runs.exit_code == 0
    assert "Compass Agent Runs History" in res_runs.stdout or "No agent runs found" in res_runs.stdout

    # Test agent-briefing command
    res_briefing = runner.invoke(app, ["agent-briefing"])
    assert res_briefing.exit_code == 0
    assert "Morning Executive Briefing" in res_briefing.stdout or "No proactive briefing available" in res_briefing.stdout



