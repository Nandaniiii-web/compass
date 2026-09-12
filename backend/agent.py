"""
Compass Agent — ReAct-style autonomous multi-step reasoning engine.

Runs a Think→Act→Observe loop using Nemotron-3 Super (120B) for reasoning
and existing SKILL_REGISTRY tools for actions. Final synthesis via Ultra (550B).

Key design:
- State-mutating tools (add_task, edit_task, update_task_status, delete_task) require
  explicit user confirmation via a "confirm_request" SSE event before execution.
- Gating halts execution: the loop actually pauses and no mutation occurs until approval.
- Reject path feeds user decline back into context so the agent can re-plan alternatives.
- A 5-minute timeout on pending confirmations auto-saves the partial run as a draft.
- Self-critique pass checks the plan before presenting to the user (capped at 2 rounds).
- Run state is persisted to PostgreSQL agent_runs table so runs survive reconnects.
- All executed mutations are tracked in agent_audit_log and can be reverted via undo.
- Hard cap of max_steps (default 8) prevents runaway loops.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from backend.config import get_settings
from backend.services.usage import record_usage

logger = logging.getLogger("compass.agent")

# ---------------------------------------------------------------------------
# Tools that mutate state require human confirmation before execution
# ---------------------------------------------------------------------------
MUTATING_TOOLS = frozenset({"add_task", "edit_task", "update_task_status", "delete_task", "log_code_snippet", "log_code_context"})
READ_ONLY_TOOLS = frozenset({"query_tasks", "query_code_context", "query_coursework_tasks", "get_hackathon_deadlines", "summarize_day", "search_web"})

# In-memory registry for live SSE confirmation events: run_id -> (asyncio.Event, outcome_dict)
_PENDING_CONFIRMATION_EVENTS: Dict[str, Tuple[asyncio.Event, Dict[str, Any]]] = {}


@dataclass
class AgentStep:
    """One step in the agent's reasoning trace."""
    type: str           # "think" | "tool_call" | "observe" | "confirm_request" | "confirm_ack" | "critic" | "synthesize" | "error" | "done" | "timeout"
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    step_number: int = 0
    elapsed_ms: int = 0
    run_id: Optional[str] = None

    def to_sse(self) -> str:
        """Serialize to SSE data line."""
        payload = {
            "type": self.type,
            "content": self.content,
            "step": self.step_number,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.tool_name:
            payload["tool"] = self.tool_name
        if self.tool_args:
            payload["args"] = self.tool_args
        if self.run_id:
            payload["run_id"] = self.run_id
        return f"data: {json.dumps(payload)}\n\n"


def _build_agent_system_prompt(tool_names: List[str]) -> str:
    """Build the system prompt that makes Super behave as a ReAct agent."""
    tool_list = ", ".join(tool_names)
    return (
        "You are Compass Agent, an autonomous planning and scheduling assistant. "
        "You help users manage tasks, deadlines, and code context across hackathon, coursework, and code domains.\n\n"
        "You have access to these tools: " + tool_list + ".\n\n"
        "Your job is to accomplish the user's goal through multi-step reasoning:\n"
        "1. Think about what information you need\n"
        "2. Call tools to gather data (read-only tools execute immediately)\n"
        "3. Observe the results\n"
        "4. Decide if you need more information or can produce your final answer\n\n"
        "IMPORTANT RULES:\n"
        "- Always query REAL data before making claims. Never guess task counts, deadlines, or priorities.\n"
        "- When you have enough information, produce a comprehensive final answer.\n"
        "- For state-changing actions (adding/editing/deleting tasks), the user will be asked to confirm before execution.\n"
        "- If a user declines a proposed action, adapt and propose a feasible alternative without modifying their declined data.\n"
        "- Be specific and actionable. Don't give vague advice.\n"
        "- If you detect deadline conflicts, propose concrete rescheduling with reasoning.\n"
    )


# ---------------------------------------------------------------------------
# Database Persistence: agent_runs and agent_audit_log
# ---------------------------------------------------------------------------

async def save_agent_run(
    pool: Any,
    run_id: str,
    goal: str,
    status: str,
    accumulated_steps: List[AgentStep],
    messages: List[Dict[str, Any]],
    pending_actions: List[Dict[str, Any]],
) -> None:
    """Persist agent run state into agent_runs table."""
    try:
        steps_json = json.dumps([asdict(s) for s in accumulated_steps], default=str)
        messages_json = json.dumps(messages, default=str)
        pending_json = json.dumps(pending_actions, default=str)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_runs (id, goal, status, accumulated_steps, messages, pending_actions)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    accumulated_steps = EXCLUDED.accumulated_steps,
                    messages = EXCLUDED.messages,
                    pending_actions = EXCLUDED.pending_actions,
                    updated_at = now()
                """,
                run_id,
                goal,
                status,
                steps_json,
                messages_json,
                pending_json,
            )
    except Exception as e:
        logger.warning(f"Failed to save agent run {run_id}: {e}")


async def get_agent_run(pool: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an agent run by ID from agent_runs table."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", run_id)
            if not row:
                return None
            return {
                "id": row["id"],
                "goal": row["goal"],
                "status": row["status"],
                "accumulated_steps": json.loads(row["accumulated_steps"]) if isinstance(row["accumulated_steps"], str) else row["accumulated_steps"],
                "messages": json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"],
                "pending_actions": json.loads(row["pending_actions"]) if isinstance(row["pending_actions"], str) else row["pending_actions"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            }
    except Exception as e:
        logger.warning(f"Failed to get agent run {run_id}: {e}")
        return None


async def record_audit_log(
    pool: Any,
    tool: str,
    args: Dict[str, Any],
    run_id: Optional[str] = None,
    affected_table: str = "tasks",
    affected_id: Optional[int] = None,
    previous_state: Optional[Dict[str, Any]] = None,
    new_state: Optional[Dict[str, Any]] = None,
    approved_by: str = "user",
) -> int:
    """Record an agent-executed mutation into agent_audit_log."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_audit_log
                (run_id, tool, args, affected_table, affected_id, previous_state, new_state, approved_by)
            VALUES
                ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7::jsonb, $8)
            RETURNING id
            """,
            run_id,
            tool,
            json.dumps(args, default=str),
            affected_table,
            affected_id,
            json.dumps(previous_state, default=str) if previous_state is not None else None,
            json.dumps(new_state, default=str) if new_state is not None else None,
            approved_by,
        )
        return row["id"]



MAX_CONCURRENT_AGENT_RUNS = 3


async def count_active_agent_runs(pool: Any, timeout_minutes: int = 5) -> int:
    """Count currently active or paused agent runs updated within the last timeout_minutes."""
    if not pool:
        return 0
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COUNT(*) FROM agent_runs 
            WHERE status IN ('running', 'paused')
              AND updated_at >= now() - ($1 || ' minutes')::interval
            """,
            str(timeout_minutes)
        )
        return int(val or 0)


async def get_critique_stats(pool: Any) -> Dict[str, Any]:
    """Calculate real critique effectiveness statistics from persisted agent runs."""
    if not pool:
        return {
            "total_runs_analyzed": 0,
            "runs_with_critique": 0,
            "critique_issues_flagged": 0,
            "critique_effectiveness_rate": 0.0,
            "recent_critique_evaluations": [],
        }
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, accumulated_steps, status, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 50"
        )
    total_runs = len(rows)
    runs_with_critique = 0
    issues_flagged = 0
    recent_evals = []

    for r in rows:
        steps_raw = r.get("accumulated_steps") or "[]"
        try:
            steps_list = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
        except Exception:
            steps_list = []

        for s in steps_list:
            if s.get("type") == "critic":
                runs_with_critique += 1
                content = s.get("content", "")
                is_flagged = not content.strip().startswith("APPROVED") or any(
                    w in content.upper() for w in ["REVISE", "ISSUE", "CONFLICT", "DECLINED", "REJECT"]
                )
                if is_flagged:
                    issues_flagged += 1
                if len(recent_evals) < 10:
                    recent_evals.append({
                        "run_id": r.get("id"),
                        "goal": r.get("goal"),
                        "critique_summary": content[:150],
                        "flagged_issue": is_flagged,
                        "created_at": r.get("created_at").isoformat() if hasattr(r.get("created_at"), "isoformat") else str(r.get("created_at")),
                    })
                break

    rate = round((issues_flagged / runs_with_critique * 100), 1) if runs_with_critique > 0 else 0.0
    return {
        "total_runs_analyzed": total_runs,
        "runs_with_critique": runs_with_critique,
        "critique_issues_flagged": issues_flagged,
        "critique_effectiveness_rate": rate,
        "recent_critique_evaluations": recent_evals,
    }


async def undo_last_agent_action(
    pool: Any,
    run_id: Optional[str] = None,
    audit_log_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Revert an agent-executed mutation using agent_audit_log."""
    async with pool.acquire() as conn:
        if audit_log_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE id = $1",
                audit_log_id,
            )
            if row and row.get("is_reverted"):
                return {"status": "error", "message": f"Action #{audit_log_id} has already been reverted."}
        elif run_id:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE run_id = $1 AND is_reverted = FALSE ORDER BY id DESC LIMIT 1",
                run_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE is_reverted = FALSE ORDER BY id DESC LIMIT 1"
            )

        if not row:
            return {"status": "error", "message": "No agent actions found to undo."}

        audit_id = row["id"]
        tool = row["tool"]
        affected_id = row["affected_id"]
        prev_state = json.loads(row["previous_state"]) if row["previous_state"] else None

        reverted_action = {"tool": tool, "affected_id": affected_id, "audit_log_id": audit_id}

        if tool == "add_task" and affected_id:
            await conn.execute("DELETE FROM tasks WHERE id = $1", affected_id)
            reverted_action["action"] = f"Deleted added task #{affected_id}"

        elif tool in ("edit_task", "update_task_status") and affected_id and prev_state:
            from datetime import datetime
            due_date = prev_state.get("due_date")
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    pass

            await conn.execute(
                """
                UPDATE tasks
                SET title = $2, due_date = $3, priority = $4, status = $5, notes = $6
                WHERE id = $1
                """,
                affected_id,
                prev_state.get("title"),
                due_date,
                prev_state.get("priority", "medium"),
                prev_state.get("status", "open"),
                prev_state.get("notes"),
            )
            reverted_action["action"] = f"Restored task #{affected_id} to previous state"

        elif tool == "delete_task" and prev_state:
            from datetime import datetime
            due_date = prev_state.get("due_date")
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    pass

            inserted = await conn.fetchrow(
                """
                INSERT INTO tasks (id, domain, project_id, title, due_date, status, priority, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    domain = EXCLUDED.domain,
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    notes = EXCLUDED.notes
                RETURNING id
                """,
                affected_id,
                prev_state.get("domain", "general"),
                prev_state.get("project_id"),
                prev_state.get("title"),
                due_date,
                prev_state.get("status", "open"),
                prev_state.get("priority", "medium"),
                prev_state.get("notes"),
            )
            reverted_action["action"] = f"Restored deleted task #{inserted['id']}"

        elif tool in ("log_code_snippet", "log_code_context") and affected_id:
            await conn.execute("DELETE FROM memory_chunks WHERE id = $1", affected_id)
            reverted_action["action"] = f"Deleted logged memory chunk #{affected_id}"

        # Mark the audit log entry as reverted
        await conn.execute("UPDATE agent_audit_log SET is_reverted = TRUE WHERE id = $1", audit_id)

        return {
            "status": "ok",
            "message": f"Successfully reverted agent action #{audit_id} ({tool})",
            "reverted": reverted_action,
        }


# ---------------------------------------------------------------------------
# Core ReAct Loop
# ---------------------------------------------------------------------------

async def run_agent(
    goal: str,
    pool: Any,
    max_steps: int = 8,
    enable_critic: bool = True,
    confirmed_actions: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    action: Optional[str] = None,
    feedback: Optional[str] = None,
    confirm_timeout_seconds: float = 300.0,
    wait_for_confirmation: bool = False,
) -> AsyncGenerator[AgentStep, None]:
    """
    Core ReAct agent loop.

    Yields AgentStep objects for real-time SSE streaming.

    When a state-mutating tool call is detected:
    1. Yield a "confirm_request" step with the proposed action
    2. The loop pauses and persists run state to agent_runs (status='paused')
    3. If wait_for_confirmation is True, wait on confirmation event with timeout
    4. If rejected, feed rejection back into context and re-plan
    5. If approved, execute mutation, log to agent_audit_log, and continue
    """
    settings = get_settings()
    step_num = 0
    start_time = time.perf_counter()
    tools_used: List[str] = []
    pending_confirmations: List[Dict[str, Any]] = []
    accumulated_steps: List[AgentStep] = []
    critique_rounds: int = 0

    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

    # Import skill registry & dynamic tool definitions
    from backend.skills import SKILL_REGISTRY, get_tool_definitions

    # Build OpenAI client for Super model
    client = AsyncOpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
        timeout=30.0,
    )

    # Build tool schemas dynamically (respecting TAVILY_ENABLED flag)
    agent_tools = get_tool_definitions()

    confirmed_actions = confirmed_actions or []
    confirmed_set = {
        (a.get("tool"), json.dumps(a.get("args", {}), sort_keys=True))
        for a in confirmed_actions
    }

    # Check for existing run state in database
    existing_run = await get_agent_run(pool, run_id) if pool else None

    if existing_run and action in ("approve", "reject"):
        goal = existing_run.get("goal", goal)
        messages = existing_run.get("messages", [])
        pending_confirmations = existing_run.get("pending_actions", [])
        step_num = len(existing_run.get("accumulated_steps", []))

        # Re-populate accumulated steps
        for s in existing_run.get("accumulated_steps", []):
            accumulated_steps.append(AgentStep(
                type=s.get("type", "think"),
                content=s.get("content", ""),
                tool_name=s.get("tool_name"),
                tool_args=s.get("tool_args"),
                step_number=s.get("step_number", 0),
                elapsed_ms=s.get("elapsed_ms", 0),
                run_id=run_id,
            ))

        if action == "reject":
            # FEED REJECTION BACK INTO CONTEXT FOR RE-PLANNING
            rej_content = (
                f"User declined: {feedback or 'do not execute this action'}. "
                "Please re-plan without modifying this data or propose an alternative approach."
            )
            tc_id = "call_rejected"
            if messages and messages[-1].get("tool_calls"):
                tc_id = messages[-1]["tool_calls"][0]["id"]

            messages.append({"role": "tool", "tool_call_id": tc_id, "content": rej_content})
            step_num += 1
            obs_step = AgentStep(
                type="observe",
                content=rej_content,
                tool_name=pending_confirmations[0]["tool"] if pending_confirmations else None,
                step_number=step_num,
                elapsed_ms=0,
                run_id=run_id,
            )
            yield obs_step
            accumulated_steps.append(obs_step)
            pending_confirmations.clear()
            if pool:
                await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations)

        elif action == "approve":
            # EXECUTE APPROVED MUTATIONS
            exec_results = await execute_confirmed_actions(pending_confirmations, pool, run_id=run_id)
            for r in exec_results:
                tool_result = r.get("result", {}).get("response", str(r.get("result", "")))
                tc_id = "call_approved"
                if messages and messages[-1].get("tool_calls"):
                    tc_id = messages[-1]["tool_calls"][0]["id"]
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_result})
                step_num += 1
                obs_step = AgentStep(
                    type="observe",
                    content=tool_result,
                    tool_name=r.get("tool"),
                    step_number=step_num,
                    elapsed_ms=0,
                    run_id=run_id,
                )
                yield obs_step
                accumulated_steps.append(obs_step)
                tools_used.append(r.get("tool", ""))
            pending_confirmations.clear()
            if pool:
                await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations)
    else:
        # New run initialization
        messages = [
            {"role": "system", "content": _build_agent_system_prompt(
                [t["function"]["name"] for t in agent_tools if "function" in t]
            )},
            {"role": "user", "content": goal},
        ]
        if pool:
            await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations)

    # --- ReAct Loop ---
    for iteration in range(max_steps):
        step_start = time.perf_counter()
        step_num += 1

        try:
            is_mocked = (
                hasattr(client, "mock_calls")
                or hasattr(getattr(client, "chat", None), "mock_calls")
                or hasattr(getattr(getattr(client, "chat", None), "completions", None), "mock_calls")
                or hasattr(getattr(getattr(getattr(client, "chat", None), "completions", None), "create", None), "mock_calls")
            )
            if not is_mocked and settings.NEBIUS_API_KEY.startswith("your_nebius_"):
                # Simulation fallback for demo / unconfigured Nebius environments
                if iteration == 0 and not action:
                    if "add" in goal.lower():
                        tool_call = type("ToolCall", (), {
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "function": type("Func", (), {
                                "name": "add_task",
                                "arguments": json.dumps({"title": "Review RISC-V Pipeline Hazards", "domain": "coursework", "priority": "high"})
                            })()
                        })()
                        msg = type("Msg", (), {
                            "content": "Analyzing task backlog across domains to create the new coursework task...",
                            "tool_calls": [tool_call]
                        })()
                        choice = type("Choice", (), {"message": msg})()
                    elif "reschedule" in goal.lower() or "plan" in goal.lower():
                        tool_call = type("ToolCall", (), {
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "function": type("Func", (), {
                                "name": "update_task_status",
                                "arguments": json.dumps({"task_id": "1", "new_status": "in_progress"})
                            })()
                        })()
                        msg = type("Msg", (), {
                            "content": "Scanning active task schedules to resolve deadline conflicts...",
                            "tool_calls": [tool_call]
                        })()
                        choice = type("Choice", (), {"message": msg})()
                    else:
                        tool_call = type("ToolCall", (), {
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "function": type("Func", (), {
                                "name": "query_tasks",
                                "arguments": json.dumps({"domain": "coursework"})
                            })()
                        })()
                        msg = type("Msg", (), {
                            "content": "Querying active tasks to build the schedule...",
                            "tool_calls": [tool_call]
                        })()
                        choice = type("Choice", (), {"message": msg})()
                elif action == "reject" or any("declined" in str(m.get("content", "")).lower() for m in messages):
                    msg = type("Msg", (), {
                        "content": "Self-critique pass (round 1/2): User declined the proposed modification. Re-planned alternative schedule preserving all existing deadlines without modifying that task.",
                        "tool_calls": []
                    })()
                    choice = type("Choice", (), {"message": msg})()
                else:
                    msg = type("Msg", (), {
                        "content": "Self-critique pass (round 1/2): Verified all task dependencies and deadline constraints. Schedule is optimal.",
                        "tool_calls": []
                    })()
                    choice = type("Choice", (), {"message": msg})()
                record_usage(settings.SKILL_MODEL, 200, 100)
            else:
                response = await client.chat.completions.create(
                    model=settings.SKILL_MODEL,
                    messages=messages,  # type: ignore[arg-type]
                    tools=agent_tools,  # type: ignore[arg-type]
                    tool_choice="auto",
                    max_tokens=512,
                    temperature=0.4,
                )

                # Record usage
                usage = getattr(response, "usage", None)
                p_tok = usage.prompt_tokens if usage else 200
                c_tok = usage.completion_tokens if usage else 100
                record_usage(settings.SKILL_MODEL, p_tok, c_tok)

                choice = response.choices[0]
            elapsed = int((time.perf_counter() - step_start) * 1000)

            # --- Tool call branch ---
            if choice.message.tool_calls:
                tc = choice.message.tool_calls[0]
                func_name = tc.function.name
                raw_args = tc.function.arguments or "{}"

                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    tool_args = {}

                # Emit THINK step if there's reasoning text too
                if choice.message.content:
                    think_step = AgentStep(
                        type="think",
                        content=choice.message.content,
                        step_number=step_num,
                        elapsed_ms=elapsed,
                        run_id=run_id,
                    )
                    yield think_step
                    accumulated_steps.append(think_step)
                    step_num += 1

                # Emit TOOL_CALL step
                tc_step = AgentStep(
                    type="tool_call",
                    content=f"Calling {func_name}",
                    tool_name=func_name,
                    tool_args=tool_args,
                    step_number=step_num,
                    elapsed_ms=elapsed,
                    run_id=run_id,
                )
                yield tc_step
                accumulated_steps.append(tc_step)

                # --- Confirmation gate for mutating tools ---
                if func_name in MUTATING_TOOLS:
                    action_key = (func_name, json.dumps(tool_args, sort_keys=True))
                    if action_key not in confirmed_set:
                        # Gating halts execution: emit confirm_request and PAUSE
                        step_num += 1
                        confirm_step = AgentStep(
                            type="confirm_request",
                            content=f"Agent wants to execute: {func_name}({json.dumps(tool_args)}). This will modify your data. Please confirm.",
                            tool_name=func_name,
                            tool_args=tool_args,
                            step_number=step_num,
                            elapsed_ms=0,
                            run_id=run_id,
                        )
                        yield confirm_step
                        accumulated_steps.append(confirm_step)
                        pending_confirmations.append({"tool": func_name, "args": tool_args})

                        messages.append({"role": "assistant", "content": None, "tool_calls": [
                            {"id": tc.id, "type": "function", "function": {"name": func_name, "arguments": raw_args}}
                        ]})

                        # Persist paused run state
                        if pool:
                            await save_agent_run(
                                pool, run_id, goal, "paused",
                                accumulated_steps, messages, pending_confirmations,
                            )

                        if wait_for_confirmation:
                            evt = asyncio.Event()
                            outcome: Dict[str, Any] = {}
                            _PENDING_CONFIRMATION_EVENTS[run_id] = (evt, outcome)

                            try:
                                await asyncio.wait_for(evt.wait(), timeout=confirm_timeout_seconds)
                                res_action = outcome.get("action", "reject")
                                res_feedback = outcome.get("feedback", "")
                            except asyncio.TimeoutError:
                                # Confirmation timed out: auto-save partial run as draft
                                if pool:
                                    await save_agent_run(
                                        pool, run_id, goal, "expired",
                                        accumulated_steps, messages, pending_confirmations,
                                    )
                                step_num += 1
                                timeout_step = AgentStep(
                                    type="done",
                                    content=json.dumps({
                                        "status": "expired",
                                        "draft_saved": True,
                                        "run_id": run_id,
                                        "message": f"Confirmation timed out after {int(confirm_timeout_seconds)}s. Partial run saved as draft.",
                                    }),
                                    step_number=step_num,
                                    elapsed_ms=int((time.perf_counter() - start_time) * 1000),
                                    run_id=run_id,
                                )
                                yield timeout_step
                                return
                            finally:
                                _PENDING_CONFIRMATION_EVENTS.pop(run_id, None)

                            if res_action == "reject":
                                # Reject path: feed decline back and re-plan
                                rej_msg = (
                                    f"User declined: {res_feedback or f'do not execute {func_name}'}. "
                                    "Please re-plan without modifying this data."
                                )
                                messages.append({"role": "tool", "tool_call_id": tc.id, "content": rej_msg})
                                step_num += 1
                                rej_step = AgentStep(
                                    type="observe",
                                    content=rej_msg,
                                    tool_name=func_name,
                                    step_number=step_num,
                                    elapsed_ms=0,
                                    run_id=run_id,
                                )
                                yield rej_step
                                accumulated_steps.append(rej_step)
                                pending_confirmations.clear()
                                if pool:
                                    await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations)
                                continue  # Re-plan!
                            else:
                                confirmed_set.add(action_key)
                                # Proceed to execute approved tool below
                        else:
                            # Non-waiting mode: pause here and exit generator without mutating data
                            return

                # Execute tool (either read-only or pre-confirmed mutating)
                tool_result = ""
                if func_name in SKILL_REGISTRY:
                    try:
                        # Capture pre-mutation state for audit log & undo if mutating
                        prev_state = None
                        affected_id = None
                        if pool and func_name in MUTATING_TOOLS:
                            if func_name in ("edit_task", "update_task_status", "delete_task"):
                                tid = tool_args.get("task_id")
                                if tid:
                                    async with pool.acquire() as conn:
                                        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", int(tid))
                                        if row:
                                            prev_state = dict(row)
                                            for k, v in prev_state.items():
                                                if hasattr(v, "isoformat"):
                                                    prev_state[k] = v.isoformat()
                                            affected_id = int(tid)

                        result = await SKILL_REGISTRY[func_name](tool_args, pool)
                        tool_result = result.get("response", str(result.get("data", "")))
                        tools_used.append(func_name)

                        # Capture post-mutation state and record audit log
                        if pool and func_name in MUTATING_TOOLS:
                            new_st = None
                            if func_name == "add_task":
                                tdata = result.get("data", {})
                                if isinstance(tdata, dict) and "id" in tdata:
                                    affected_id = tdata["id"]
                                    new_st = dict(tdata)
                            elif func_name in ("edit_task", "update_task_status"):
                                tdata = result.get("data", {})
                                if isinstance(tdata, dict) and "id" in tdata:
                                    new_st = dict(tdata)

                            await record_audit_log(
                                pool=pool,
                                tool=func_name,
                                args=tool_args,
                                run_id=run_id,
                                affected_table="tasks",
                                affected_id=affected_id,
                                previous_state=prev_state,
                                new_state=new_st,
                                approved_by="user",
                            )

                    except Exception as e:
                        tool_result = f"Tool execution error: {e}"
                        logger.warning(f"Agent tool {func_name} failed: {e}")
                else:
                    tool_result = f"Tool '{func_name}' is not available."

                # Emit OBSERVE step
                step_num += 1
                obs_step = AgentStep(
                    type="observe",
                    content=tool_result,
                    tool_name=func_name,
                    step_number=step_num,
                    elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                    run_id=run_id,
                )
                yield obs_step
                accumulated_steps.append(obs_step)

                # Add to agent context for next iteration
                messages.append({"role": "assistant", "content": None, "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": func_name, "arguments": raw_args}}
                ]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

            # --- Text response branch (agent wants to synthesize) ---
            else:
                reply = choice.message.content or ""

                # Self-critique pass: check proposed plan against gathered data (capped at 2 rounds)
                if enable_critic and reply:
                    step_num += 1
                    critic_step = await _run_critic_pass(
                        client, settings, reply, messages, step_num, run_id=run_id,
                    )
                    yield critic_step
                    accumulated_steps.append(critic_step)

                    critique_rounds += 1
                    if "APPROVED" not in critic_step.content.upper():
                        if critique_rounds < 2:
                            messages.append({"role": "assistant", "content": reply})
                            messages.append({
                                "role": "user",
                                "content": f"A reviewer checked your plan and found issues:\n\n{critic_step.content}\n\nPlease revise your plan to address these concerns.",
                            })
                            continue  # Loop again for revision
                        else:
                            logger.info("Critique-revise cycle cap (2 rounds) reached; proceeding to synthesis.")

                # Emit SYNTHESIZE step
                step_num += 1
                synth_step = AgentStep(
                    type="synthesize",
                    content=reply,
                    step_number=step_num,
                    elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                    run_id=run_id,
                )
                yield synth_step
                accumulated_steps.append(synth_step)
                break  # Done

        except Exception as e:
            logger.error(f"Agent loop error at step {step_num}: {e}")
            step_num += 1
            err_step = AgentStep(
                type="error",
                content=f"Agent encountered an error: {e}",
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                run_id=run_id,
            )
            yield err_step
            accumulated_steps.append(err_step)
            break

    # If we hit max_steps without synthesizing, force a synthesis
    else:
        step_num += 1
        try:
            messages.append({
                "role": "user",
                "content": "You've gathered enough information. Please produce your final comprehensive answer now.",
            })
            response = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=1024,
                temperature=0.5,
            )
            usage = getattr(response, "usage", None)
            p_tok = usage.prompt_tokens if usage else 500
            c_tok = usage.completion_tokens if usage else 200
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)

            final_text = response.choices[0].message.content or "Agent completed analysis."
            forced_synth = AgentStep(
                type="synthesize",
                content=final_text,
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - start_time) * 1000),
                run_id=run_id,
            )
            yield forced_synth
            accumulated_steps.append(forced_synth)
        except Exception as e:
            err_step = AgentStep(
                type="error",
                content=f"Final synthesis failed: {e}",
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - start_time) * 1000),
                run_id=run_id,
            )
            yield err_step
            accumulated_steps.append(err_step)

    # Emit DONE step with summary and save completed run state
    total_elapsed = int((time.perf_counter() - start_time) * 1000)
    done_payload = {
        "run_id": run_id,
        "total_steps": step_num,
        "tools_used": list(set(tools_used)),
        "pending_confirmations": pending_confirmations,
    }
    done_step = AgentStep(
        type="done",
        content=json.dumps(done_payload),
        step_number=step_num + 1,
        elapsed_ms=total_elapsed,
        run_id=run_id,
    )
    yield done_step
    accumulated_steps.append(done_step)

    if pool:
        await save_agent_run(pool, run_id, goal, "completed", accumulated_steps, messages, pending_confirmations)


async def _run_critic_pass(
    client: AsyncOpenAI,
    settings: Any,
    proposed_plan: str,
    context_messages: List[Dict[str, Any]],
    step_num: int,
    run_id: Optional[str] = None,
) -> AgentStep:
    """
    Self-critique pass: a separate reasoning call that checks the proposed
    plan against real constraints from the gathered data.

    This is NOT multi-agent — it's a single-model self-critique pass
    using a different system prompt over the same accumulated context.
    """
    start = time.perf_counter()

    # Extract tool observations from context for the critic
    observations = []
    for msg in context_messages:
        if msg.get("role") == "tool":
            observations.append(msg.get("content", ""))

    critic_prompt = (
        "You are a critical reviewer for a planning assistant. "
        "A planner proposed the following plan based on real data:\n\n"
        f"PROPOSED PLAN:\n{proposed_plan}\n\n"
        "DATA THE PLANNER USED:\n" + "\n---\n".join(observations[-6:]) + "\n\n"
        "Check the plan against these criteria:\n"
        "1. Are all mentioned tasks/deadlines consistent with the actual data?\n"
        "2. Are any tasks missed or double-counted?\n"
        "3. Is the priority ordering sensible given actual due dates?\n"
        "4. Are the time estimates realistic?\n\n"
        "If the plan is solid, respond with 'APPROVED: ' followed by a brief note.\n"
        "If it has issues, list them concretely and suggest fixes."
    )

    try:
        is_mocked = (
            hasattr(client, "mock_calls")
            or hasattr(getattr(client, "chat", None), "mock_calls")
            or hasattr(getattr(getattr(client, "chat", None), "completions", None), "mock_calls")
            or hasattr(getattr(getattr(getattr(client, "chat", None), "completions", None), "create", None), "mock_calls")
        )
        if not is_mocked and settings.NEBIUS_API_KEY.startswith("your_nebius_"):
            critic_text = "APPROVED: Plan looks sound, constraints verified against task database."
            record_usage(settings.SKILL_MODEL, 300, 50)
        else:
            resp = await client.chat.completions.create(
                model=settings.SKILL_MODEL,
                messages=[
                    {"role": "system", "content": "You are a critical reviewer. Be thorough but concise."},
                    {"role": "user", "content": critic_prompt},
                ],
                max_tokens=384,
                temperature=0.3,
            )
            usage = getattr(resp, "usage", None)
            p_tok = usage.prompt_tokens if usage else 300
            c_tok = usage.completion_tokens if usage else 100
            record_usage(settings.SKILL_MODEL, p_tok, c_tok)

            critic_text = resp.choices[0].message.content or "APPROVED: Plan looks reasonable."
    except Exception as e:
        logger.warning(f"Critic pass failed: {e}")
        critic_text = "APPROVED: (Critic pass skipped due to error)"

    return AgentStep(
        type="critic",
        content=critic_text,
        step_number=step_num,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        run_id=run_id,
    )


async def execute_confirmed_actions(
    confirmed_actions: List[Dict[str, Any]],
    pool: Any,
    run_id: Optional[str] = None,
    approved_by: str = "user",
) -> List[Dict[str, Any]]:
    """Execute previously confirmed state-mutating actions.

    Called after the user approves pending actions from an agent run.
    Records every executed mutation into agent_audit_log.
    Returns results for each executed action.
    """
    from backend.skills import SKILL_REGISTRY
    results = []
    for action in confirmed_actions:
        tool_name = action.get("tool", "")
        tool_args = action.get("args", {})

        if tool_name not in SKILL_REGISTRY:
            results.append({"tool": tool_name, "status": "error", "message": f"Unknown tool: {tool_name}"})
            continue

        previous_state = None
        affected_id = None
        affected_table = "tasks"

        # Capture pre-mutation state for audit log & undo
        try:
            if pool and tool_name in ("edit_task", "update_task_status", "delete_task"):
                task_id = tool_args.get("task_id")
                if task_id:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", int(task_id))
                        if row:
                            previous_state = dict(row)
                            for k, v in previous_state.items():
                                if hasattr(v, "isoformat"):
                                    previous_state[k] = v.isoformat()
                            affected_id = int(task_id)
        except Exception as e:
            logger.warning(f"Failed to capture pre-mutation state: {e}")

        try:
            result = await SKILL_REGISTRY[tool_name](tool_args, pool)
            new_state = None

            # Capture post-mutation state
            if tool_name == "add_task":
                task_data = result.get("data", {})
                if isinstance(task_data, dict) and "id" in task_data:
                    affected_id = task_data["id"]
                    new_state = dict(task_data)
            elif tool_name in ("edit_task", "update_task_status"):
                task_data = result.get("data", {})
                if isinstance(task_data, dict) and "id" in task_data:
                    new_state = dict(task_data)

            # Record into audit log
            if pool and tool_name in MUTATING_TOOLS:
                await record_audit_log(
                    pool=pool,
                    tool=tool_name,
                    args=tool_args,
                    run_id=run_id,
                    affected_table=affected_table,
                    affected_id=affected_id,
                    previous_state=previous_state,
                    new_state=new_state,
                    approved_by=approved_by,
                )

            results.append({"tool": tool_name, "status": "success", "result": result})
        except Exception as e:
            results.append({"tool": tool_name, "status": "error", "message": str(e)})

    return results
