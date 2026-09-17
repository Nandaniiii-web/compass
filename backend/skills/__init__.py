"""
Compass — Skills Registry & Tool Definitions.

Central registry for all skills supported by Compass. Provides a standardized
pattern for registering tools for the router and dispatching execution in orchestrator.
"""

from typing import Any, Callable, Coroutine, Dict, List
import logging

logger = logging.getLogger("compass.skills")

# ---------------------------------------------------------------------------
# Tool Definitions (OpenAI-compatible function schemas for Nemotron-3 Nano)
# ---------------------------------------------------------------------------

ADD_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_task",
        "description": "Add a new task or action item to the user's structured task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title or action item description of the task",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Domain category",
                },
                "project": {
                    "type": "string",
                    "description": "Optional name of the project this task belongs to",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format (if specified or inferred)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Priority level of the task",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or details for the task",
                },
            },
            "required": ["title"],
        },
    },
}

QUERY_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_tasks",
        "description": "Query or list existing tasks and deadlines by domain, project, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Filter by domain",
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project name",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done", "overdue"],
                    "description": "Filter by status",
                },
            },
        },
    },
}

QUERY_CODE_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_code_context",
        "description": "Semantic search over code snippets, architecture notes, and technical memory chunks.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or technical question",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (typically 'code' or 'hackathon')",
                },
            },
            "required": ["query"],
        },
    },
}

SUMMARIZE_DAY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "summarize_day",
        "description": "Generate a daily summary or standup report across all projects and open tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to summarize in YYYY-MM-DD format, defaults to today",
                },
            },
        },
    },
}

QUERY_COURSEWORK_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_coursework_tasks",
        "description": "Query academic coursework tasks, lab submissions, and reports (e.g. CS 61C RISC-V).",
        "parameters": {
            "type": "object",
            "properties": {
                "course": {"type": "string", "description": "Optional course name or code (e.g. CS 61C)"},
                "status": {"type": "string", "enum": ["open", "overdue", "done"], "description": "Filter by status"}
            }
        }
    }
}

GET_HACKATHON_DEADLINES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_hackathon_deadlines",
        "description": "Retrieve active hackathon project deliverables, deadlines, and benchmark submissions.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Hackathon project name"}
            }
        }
    }
}

LOG_CODE_SNIPPET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "log_code_snippet",
        "description": "Store technical architecture notes, code snippets, or configuration in vector memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The code snippet or technical summary"},
                "project": {"type": "string", "description": "Target project"},
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["content"]
        }
    }
}

LOG_CODE_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "log_code_context",
        "description": "Store technical architecture notes, code snippets, or configuration in vector memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The code snippet or technical summary"},
                "project": {"type": "string", "description": "Target project"},
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["content"]
        }
    }
}

SEARCH_WEB_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for current information, news, documentation, or any query requiring up-to-date external data using Tavily Search.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or question to look up on the web",
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "Search depth: 'basic' for quick results, 'advanced' for comprehensive research",
                },
            },
            "required": ["query"],
        },
    },
}

UPDATE_TASK_STATUS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_task_status",
        "description": "Update the status of an existing task (open, in_progress, done).",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to update",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done"],
                    "description": "The new status for the task",
                },
            },
            "required": ["task_id", "status"],
        },
    },
}

EDIT_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_task",
        "description": "Edit an existing task's title, due date, priority, or notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to edit",
                },
                "title": {
                    "type": "string",
                    "description": "New title for the task",
                },
                "due_date": {
                    "type": "string",
                    "description": "New due date in YYYY-MM-DD format",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "New priority level",
                },
                "notes": {
                    "type": "string",
                    "description": "Updated notes or context",
                },
            },
            "required": ["task_id"],
        },
    },
}

DELETE_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_task",
        "description": "Permanently delete a task by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to delete",
                },
            },
            "required": ["task_id"],
        },
    },
}

LIST_PROJECTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": "List all tracked projects partitioned across domains.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Optional domain to filter projects",
                },
            },
            "required": [],
        },
    },
}

QUERY_COURSEWORK_NOTES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_coursework_notes",
        "description": "Searches and retrieves academic coursework notes and syllabus items.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search topic or course concept (e.g. RISC-V, hazards, calculus)",
                },
            },
            "required": ["query"],
        },
    },
}

SUMMARIZE_ACROSS_DOMAINS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "summarize_across_domains",
        "description": "Escalates to Nemotron-3 Ultra (550B) over pre-aggregated context for roadmap synthesis and cross-domain conflict analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to summarize in YYYY-MM-DD format, defaults to today",
                },
            },
            "required": [],
        },
    },
}

CHAT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "chat",
        "description": "General conversational fallback for greetings, questions, and non-actionable queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The user message or conversation input",
                },
            },
            "required": ["message"],
        },
    },
}

DETECT_DEADLINE_CONFLICTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "detect_deadline_conflicts",
        "description": "Analyze all scheduled tasks and deadlines across hackathon, coursework, and code domains to detect overlapping commitments, resource contention, and deadline clustering within the next 7 days.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to scan for conflicts (default: 7)",
                },
            },
        },
    },
}

GET_CALENDAR_AVAILABILITY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_calendar_availability",
        "description": "Query free/busy windows and existing schedule blocks from Google Calendar and Compass tasks across a date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (defaults to today)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (defaults to 7 days from start_date)",
                },
            },
        },
    },
}

PROPOSE_SCHEDULE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_schedule",
        "description": "Analyze unscheduled or pending tasks and use deterministic slot allocation to propose optimal, non-overlapping calendar time slots respecting working hours, buffers, and deadlines.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Target date or start date for scheduling in YYYY-MM-DD format",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Optional domain filter for tasks to schedule",
                },
                "task_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific task IDs to schedule (if omitted, schedules all open unscheduled tasks)",
                },
            },
        },
    },
}

COMMIT_SCHEDULE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "commit_schedule",
        "description": "Commit approved time slots to tasks in PostgreSQL, synchronize with Google Calendar, and record to audit log. MUTATING ACTION requiring user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "integer"},
                            "scheduled_start": {"type": "string", "description": "ISO 8601 UTC start datetime"},
                            "scheduled_end": {"type": "string", "description": "ISO 8601 UTC end datetime"},
                        },
                        "required": ["task_id", "scheduled_start", "scheduled_end"],
                    },
                    "description": "List of task slot assignments to commit",
                },
                "rationale": {
                    "type": "string",
                    "description": "Summary rationale of the schedule plan",
                },
            },
            "required": ["assignments"],
        },
    },
}

DETECT_SCHEDULE_CONFLICTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "detect_schedule_conflicts",
        "description": "Analyze scheduled tasks, calendar events, and task dependency prerequisites to detect time overlaps, dependency timing violations, overdue/slipped tasks, and deadline breaches.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Optional start date filter (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "Optional end date filter (YYYY-MM-DD)"},
            },
        },
    },
}

# Registered tools exposed to the Nemotron router
BASE_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    ADD_TASK_TOOL,
    QUERY_TASKS_TOOL,
    QUERY_COURSEWORK_TASKS_TOOL,
    QUERY_COURSEWORK_NOTES_TOOL,
    GET_HACKATHON_DEADLINES_TOOL,
    LOG_CODE_SNIPPET_TOOL,
    LOG_CODE_CONTEXT_TOOL,
    QUERY_CODE_CONTEXT_TOOL,
    SUMMARIZE_DAY_TOOL,
    SUMMARIZE_ACROSS_DOMAINS_TOOL,
    UPDATE_TASK_STATUS_TOOL,
    EDIT_TASK_TOOL,
    DELETE_TASK_TOOL,
    LIST_PROJECTS_TOOL,
    CHAT_TOOL,
    DETECT_DEADLINE_CONFLICTS_TOOL,
    GET_CALENDAR_AVAILABILITY_TOOL,
    PROPOSE_SCHEDULE_TOOL,
    COMMIT_SCHEDULE_TOOL,
    DETECT_SCHEDULE_CONFLICTS_TOOL,
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Return active tool definitions for the Nemotron router.
    search_web is feature-flagged behind TAVILY_ENABLED (default: False).
    """
    try:
        from backend.config import get_settings
        if getattr(get_settings(), "TAVILY_ENABLED", False):
            return BASE_TOOL_DEFINITIONS + [SEARCH_WEB_TOOL]
    except Exception:
        pass
    return list(BASE_TOOL_DEFINITIONS)


TOOL_DEFINITIONS: List[Dict[str, Any]] = get_tool_definitions()


# ---------------------------------------------------------------------------
# Skill Registry Map (skill_name -> handler function)
# ---------------------------------------------------------------------------
SkillHandler = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
SKILL_REGISTRY: Dict[str, SkillHandler] = {}


def register_skill(name: str):
    """Decorator to register a skill handler function into SKILL_REGISTRY."""
    def decorator(fn: SkillHandler):
        SKILL_REGISTRY[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Default Skill Implementations (Bridging while Rhythm completes skills)
# ---------------------------------------------------------------------------

@register_skill("query_tasks")
async def handle_query_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query tasks table via structured.list_tasks and format summary."""
    from backend.memory import structured
    domain = args.get("domain")
    status = args.get("status")

    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain=domain, status=status)

    count = len(tasks)
    d_str = f" in {domain.upper()}" if domain else ""
    s_str = f" with status '{status}'" if status else ""
    if tasks:
        task_details = [
            f"'{t['title']}' (due: {t.get('due_date') or 'no due date'}, status: {t.get('status', 'open')})"
            for t in tasks[:5]
        ]
        summary = f"Found {count} task(s){d_str}{s_str}: {'; '.join(task_details)}."
    else:
        summary = f"Found {count} task(s){d_str}{s_str}."
    return {
        "response": summary,
        "data": {"tasks": tasks, "count": count},
    }


@register_skill("query_code_context")
async def handle_query_code_context(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query memory_chunks using vector.search_chunks and synthesize response via SKILL_MODEL."""
    from backend.memory import vector
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    query = args.get("query", "")
    domain = args.get("domain", "code")

    try:
        async with pool.acquire() as conn:
            chunks = await vector.search_chunks(conn, query=query, domain=domain, limit=3)
        count = len(chunks)

        # Synthesize technical response using SKILL_MODEL (nvidia/nemotron-3-super-120b-a12b)
        if chunks and settings.NEBIUS_API_KEY:
            try:
                context_text = "\n\n".join(f"[Snippet #{c['id']}]:\n{c['content']}" for c in chunks)
                client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
                prompt = (
                    f"Answer the user's question using the retrieved code context below.\n\n"
                    f"Context:\n{context_text}\n\n"
                    f"Question: {query}"
                )
                resp = await client.chat.completions.create(
                    model=settings.SKILL_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a senior technical coding assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=384,
                )
                p_tok = resp.usage.prompt_tokens if resp.usage else len(prompt.split()) * 2
                c_tok = resp.usage.completion_tokens if resp.usage else 100
                record_usage(settings.SKILL_MODEL, p_tok, c_tok)
                raw_content = resp.choices[0].message.content
                if raw_content is not None and raw_content.strip():
                    summary = raw_content.strip()
                else:
                    summary = f"Retrieved {count} relevant memory chunk(s) for query: '{query}'."
                return {
                    "response": summary,
                    "data": {"chunks": chunks, "count": count, "model": settings.SKILL_MODEL},
                }
            except Exception as llm_err:
                logger.warning(f"SKILL_MODEL synthesis failed: {llm_err}")

        summary = f"Retrieved {count} relevant memory chunk(s) for query: '{query}'."
        return {
            "response": summary,
            "data": {"chunks": chunks, "count": count},
        }
    except Exception as e:
        return {
            "response": f"Code context search encountered: {e}",
            "data": {"chunks": [], "error": str(e)},
        }


@register_skill("log_code_context")
async def handle_log_code_context(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Store code snippet/context in memory_chunks via vector.store_chunk."""
    from backend.memory import vector
    content = args.get("content", "")
    domain = args.get("domain", "code")
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    try:
        async with pool.acquire() as conn:
            chunk = await vector.store_chunk(conn, content=content, domain=domain, tags=tags)
        return {
            "response": f"Logged code memory to {domain.upper()} domain with 768-dim vector.",
            "data": chunk,
        }
    except Exception as e:
        return {
            "response": f"Could not log code memory: {e}",
            "data": {"error": str(e)},
        }


@register_skill("summarize_day")
async def handle_summarize_day(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Return executive daily standup summary using SYNTHESIS_MODEL across domains."""
    from backend.memory import structured
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")

    by_domain: Dict[str, int] = {}
    for t in tasks:
        d = t.get("domain", "general")
        by_domain[d] = by_domain.get(d, 0) + 1

    # Synthesize daily briefing using SYNTHESIS_MODEL (nvidia/Nemotron-3-Ultra-550b-a55b)
    if tasks and settings.NEBIUS_API_KEY:
        try:
            task_list_str = "\n".join(
                f"- [{t['domain'].upper()}] {t['title']} (Due: {t.get('due_date') or 'No date'}, Priority: {t.get('priority', 'medium')})"
                for t in tasks[:15]
            )
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
            prompt = (
                "Synthesize the following active tasks into a concise, high-impact 2-3 sentence daily briefing. "
                "Highlight the nearest deadlines across hackathon, coursework, and code:\n\n"
                f"{task_list_str}"
            )
            resp = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You provide prioritized, executive daily standup summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=256,
            )
            p_tok = resp.usage.prompt_tokens if resp.usage else len(prompt.split()) * 2
            c_tok = resp.usage.completion_tokens if resp.usage else 80
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
            raw_content = resp.choices[0].message.content
            if raw_content is not None and raw_content.strip():
                summary = raw_content.strip()
            else:
                summary = f"Daily summary: {len(tasks)} total open task(s)."
            return {
                "response": summary,
                "data": {"open_tasks_by_domain": by_domain, "total": len(tasks), "model": settings.SYNTHESIS_MODEL},
            }
        except Exception as llm_err:
            logger.warning(f"SYNTHESIS_MODEL daily summary failed: {llm_err}")

    parts = [f"{d.upper()}: {c}" for d, c in by_domain.items()]
    summary = f"Daily summary: {len(tasks)} total open task(s) ({', '.join(parts) if parts else 'None'})."
    return {
        "response": summary,
        "data": {"open_tasks_by_domain": by_domain, "total": len(tasks)},
    }


@register_skill("query_coursework_tasks")
async def handle_query_coursework_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query coursework tasks such as CS 61C labs, reports, and homework."""
    from backend.memory import structured
    status = args.get("status")
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="coursework", status=status)
    count = len(tasks)
    summary = f"📚 Coursework: Found {count} task(s) including RISC-V reports and Logisim labs."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("get_hackathon_deadlines")
async def handle_get_hackathon_deadlines(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Retrieve urgent hackathon deliverables and demo benchmark deadlines."""
    from backend.memory import structured
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="hackathon")
    count = len(tasks)
    summary = f"🚀 Hackathon: {count} active deliverables for Nebius Token Factory benchmark."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("log_code_snippet")
async def handle_log_code_snippet(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Log code snippets and technical context into pgvector with 768-dim embeddings."""
    from backend.memory import vector, structured
    content = args.get("content", "")
    project_name = args.get("project")
    tags = args.get("tags", "")
    tag_list = [t.strip() for t in tags.split(",")] if isinstance(tags, str) and tags else []
    
    async with pool.acquire() as conn:
        project_id = None
        if project_name:
            proj = await structured.get_or_create_project(conn, project_name, "code")
            project_id = proj.get("id")
        chunk = await vector.store_chunk(conn, content=content, domain="code", project_id=project_id, tags=tag_list)
    return {"response": "💻 Logged code context with 768-dim embedding in Neon HNSW index.", "data": chunk}


@register_skill("add_task")
async def handle_add_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Add a new task via structured.create_task."""
    from backend.memory import structured
    from datetime import datetime

    title = args.get("title", "Untitled Task")
    domain = args.get("domain", "general")
    if domain not in {"hackathon", "coursework", "code", "general"}:
        domain = "general"

    project_name = args.get("project")
    due_str = args.get("due_date")
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(str(due_str)[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    priority = args.get("priority", "medium")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"

    status = args.get("status", "open")
    if status not in {"open", "in_progress", "done", "overdue"}:
        status = "open"

    notes = args.get("notes")

    try:
        async with pool.acquire() as conn:
            project_id = None
            if project_name:
                proj = await structured.get_or_create_project(conn, name=project_name, domain=domain)
                project_id = proj.get("id")

            task_record = await structured.create_task(
                conn,
                domain=domain,
                title=title,
                project_id=project_id,
                due_date=due_date,
                status=status,
                priority=priority,
                notes=notes,
            )
        return {
            "response": f"Added task #{task_record.get('id')}: '{title}' in {domain}.",
            "data": task_record,
        }
    except Exception as e:
        logger.warning(f"Failed to add task: {e}")
        return {"response": f"Failed to add task: {e}", "data": {"error": str(e)}}


@register_skill("update_task_status")
async def handle_update_task_status(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Update the status of an existing task."""
    from backend.memory import structured
    task_id = args.get("task_id")
    status = args.get("status", "open")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(conn, int(task_id), status=status)
        if updated:
            return {
                "response": f"Updated task #{task_id} status to '{status}'.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to update task status: {e}", "data": {"error": str(e)}}


@register_skill("edit_task")
async def handle_edit_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Edit an existing task's title, due date, priority, or notes."""
    from backend.memory import structured
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    # Build kwargs from provided fields
    update_fields: Dict[str, Any] = {}
    if "title" in args:
        update_fields["title"] = args["title"]
    if "due_date" in args:
        from datetime import datetime
        try:
            update_fields["due_date"] = datetime.strptime(args["due_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {"response": f"Invalid date format: {args['due_date']}. Use YYYY-MM-DD.", "data": {}}
    if "priority" in args:
        update_fields["priority"] = args["priority"]
    if "notes" in args:
        update_fields["notes"] = args["notes"]

    if not update_fields:
        return {"response": "No fields to update. Provide title, due_date, priority, or notes.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(conn, int(task_id), **update_fields)
        if updated:
            fields_str = ", ".join(f"{k}={v}" for k, v in update_fields.items())
            return {
                "response": f"Updated task #{task_id}: {fields_str}.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to edit task: {e}", "data": {"error": str(e)}}


@register_skill("delete_task")
async def handle_delete_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Delete a task by ID."""
    from backend.memory import structured
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            deleted = await structured.delete_task(conn, int(task_id))
        if deleted:
            return {"response": f"Deleted task #{task_id}.", "data": {"deleted": True}}
        return {"response": f"Task #{task_id} not found.", "data": {"deleted": False}}
    except Exception as e:
        return {"response": f"Failed to delete task: {e}", "data": {"error": str(e)}}


@register_skill("list_projects")
async def handle_list_projects(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """List all tracked projects via structured.list_projects."""
    from backend.memory import structured
    domain = args.get("domain")
    async with pool.acquire() as conn:
        projects = await structured.list_projects(conn)
    if domain:
        projects = [p for p in projects if p.get("domain") == domain]
    p_names = [f"'{p['name']}' ({p.get('domain', 'general')})" for p in projects]
    summary = f"Found {len(projects)} tracked project(s): {', '.join(p_names)}." if projects else "No tracked projects found."
    return {
        "response": summary,
        "data": {"projects": projects, "count": len(projects)},
    }


@register_skill("query_coursework_notes")
async def handle_query_coursework_notes(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Search coursework notes using vector memory search specifically filtered to domain='coursework'."""
    cw_args = dict(args)
    cw_args["domain"] = "coursework"
    if not cw_args.get("query"):
        for alt_key in ("course", "topic", "notes", "subject"):
            if cw_args.get(alt_key):
                cw_args["query"] = str(cw_args[alt_key])
                break
    return await handle_query_code_context(cw_args, pool)


@register_skill("summarize_across_domains")
async def handle_summarize_across_domains(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Escalates to Nemotron-3 Ultra (550B) over pre-aggregated multi-domain context for roadmap synthesis.

    Aggregates:
    1. Active tasks across hackathon, coursework, and code
    2. Recent code context chunks from vector memory
    3. Recent coursework note chunks from vector memory
    4. Tracked projects
    """
    from backend.memory import structured
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")
        projects = await structured.list_projects(conn)
        try:
            code_chunks = await conn.fetch(
                "SELECT id, content, tags FROM memory_chunks WHERE domain = 'code' ORDER BY id DESC LIMIT 5"
            )
        except Exception:
            code_chunks = []
        try:
            cw_chunks = await conn.fetch(
                "SELECT id, content, tags FROM memory_chunks WHERE domain = 'coursework' ORDER BY id DESC LIMIT 5"
            )
        except Exception:
            cw_chunks = []

    by_domain: Dict[str, int] = {}
    for t in tasks:
        d = t.get("domain", "general")
        by_domain[d] = by_domain.get(d, 0) + 1

    tasks_context = "\n".join(
        f"- [{t['domain'].upper()}] {t['title']} (Due: {t.get('due_date') or 'No date'}, Priority: {t.get('priority', 'medium')})"
        for t in tasks[:15]
    ) or "No active tasks."

    code_context = "\n".join(
        f"- [Snippet #{c['id']}]: {c['content'][:150]}..."
        for c in code_chunks
    ) or "No recent code snippets."

    cw_context = "\n".join(
        f"- [Note #{c['id']}]: {c['content'][:150]}..."
        for c in cw_chunks
    ) or "No recent coursework notes."

    p_names = ", ".join(f"{p['name']} ({p.get('domain', 'general')})" for p in projects[:10]) or "None"

    combined_context = (
        f"### 1. Tracked Projects\n{p_names}\n\n"
        f"### 2. Active Tasks by Domain\n{tasks_context}\n\n"
        f"### 3. Technical Code Context\n{code_context}\n\n"
        f"### 4. Coursework Notes\n{cw_context}"
    )

    if settings.NEBIUS_API_KEY:
        try:
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
            prompt = (
                "You are an executive multi-domain roadmap planner powered by Nemotron-3 Ultra (550B). "
                "Synthesize the following cross-domain state into an integrated executive roadmap. "
                "Explicitly call out dependencies between hackathon deadlines, coursework exams/labs, and code implementation.\n\n"
                f"{combined_context}"
            )
            resp = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You provide comprehensive, multi-domain executive roadmap briefings."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=384,
            )
            p_tok = resp.usage.prompt_tokens if resp.usage else len(prompt.split()) * 2
            c_tok = resp.usage.completion_tokens if resp.usage else 120
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
            raw_content = resp.choices[0].message.content
            if raw_content is not None and raw_content.strip():
                summary = raw_content.strip()
            else:
                summary = f"Multi-domain roadmap: {len(tasks)} tasks across {len(by_domain)} domains, {len(code_chunks)} code chunks, {len(cw_chunks)} coursework notes."
            return {
                "response": summary,
                "data": {
                    "open_tasks_by_domain": by_domain,
                    "total_tasks": len(tasks),
                    "code_chunks_count": len(code_chunks),
                    "coursework_chunks_count": len(cw_chunks),
                    "projects_count": len(projects),
                    "model": settings.SYNTHESIS_MODEL,
                },
            }
        except Exception as llm_err:
            logger.warning(f"SYNTHESIS_MODEL cross-domain summary failed: {llm_err}")

    parts = [f"{d.upper()}: {c}" for d, c in by_domain.items()]
    summary = (
        f"🧭 Cross-Domain Roadmap Synthesis: {len(tasks)} active tasks ({', '.join(parts) if parts else 'none'}), "
        f"{len(code_chunks)} technical code snippets, and {len(cw_chunks)} academic coursework notes indexed across {len(projects)} projects."
    )
    return {
        "response": summary,
        "data": {
            "open_tasks_by_domain": by_domain,
            "total_tasks": len(tasks),
            "code_chunks_count": len(code_chunks),
            "coursework_chunks_count": len(cw_chunks),
            "projects_count": len(projects),
            "model": settings.SYNTHESIS_MODEL,
        },
    }


@register_skill("chat")
async def handle_chat_skill(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Conversational fallback for greetings, questions, and non-actionable queries."""
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    msg = args.get("message") or args.get("query") or "Hello! I am Compass, your persistent multi-domain AI assistant."

    if settings.NEBIUS_API_KEY and msg != "Hello! I am Compass, your persistent multi-domain AI assistant.":
        try:
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=10.0)
            resp = await client.chat.completions.create(
                model=settings.ROUTER_MODEL,
                messages=[
                    {"role": "system", "content": "You are Compass, a smart multi-domain AI assistant managing Hackathon, Coursework, and Code. Be concise, friendly, and helpful."},
                    {"role": "user", "content": str(msg)}
                ],
                max_tokens=150,
            )
            p_tok = resp.usage.prompt_tokens if resp.usage else len(str(msg).split()) * 2
            c_tok = resp.usage.completion_tokens if resp.usage else 50
            record_usage(settings.ROUTER_MODEL, p_tok, c_tok)
            content = resp.choices[0].message.content
            if content and content.strip():
                return {"response": content.strip(), "data": {"type": "chat", "model": settings.ROUTER_MODEL}}
        except Exception as e:
            logger.debug(f"Chat skill LLM fallback: {e}")

    return {"response": str(msg), "data": {"type": "chat"}}


@register_skill("detect_deadline_conflicts")
async def handle_detect_deadline_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Scan active tasks for conflicting deadlines across domains within the next N days."""
    from backend.memory import structured
    from datetime import date, timedelta

    days = int(args.get("days_ahead") or 7)
    today = date.today()
    cutoff = today + timedelta(days=days)

    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        d = t.get("due_date")
        if d:
            d_str = str(d)[:10]
            try:
                task_date = date.fromisoformat(d_str)
                if today <= task_date <= cutoff:
                    by_date.setdefault(d_str, []).append(t)
            except Exception:
                pass

    conflicts = []
    for d_str, day_tasks in sorted(by_date.items()):
        domains = {t.get("domain", "general") for t in day_tasks}
        priorities = {t.get("priority", "medium") for t in day_tasks}
        if len(day_tasks) > 1 or ("urgent" in priorities and "hackathon" in domains and "coursework" in domains):
            is_critical = ("hackathon" in domains and "coursework" in domains) or ("urgent" in priorities)
            conflicts.append({
                "date": d_str,
                "task_count": len(day_tasks),
                "severity": "critical" if is_critical else "moderate",
                "domains": list(domains),
                "tasks": [
                    {"id": t["id"], "title": t["title"], "domain": t.get("domain"), "priority": t.get("priority")}
                    for t in day_tasks
                ],
                "recommendation": (
                    f"Reschedule non-urgent tasks on {d_str} to avoid clash between {', '.join(domains)}."
                    if is_critical
                    else f"Review task pacing on {d_str} to prevent bottleneck."
                )
            })

    if conflicts:
        summary = (
            f"⚠️ Detected {len(conflicts)} deadline conflict cluster(s) within the next {days} days. "
            f"Most critical: {conflicts[0]['date']} with {conflicts[0]['task_count']} tasks across {', '.join(conflicts[0]['domains'])}."
        )
    else:
        summary = f"✅ No critical deadline conflicts detected across domains in the next {days} days."

    return {
        "response": summary,
        "data": {
            "conflicts_count": len(conflicts),
            "conflicts": conflicts,
            "scanned_tasks_count": len(tasks),
            "days_ahead": days,
        },
    }


async def dispatch_skill(skill_name: str, args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Dispatch execution to registered skill handler or return fallback response."""
    if skill_name in SKILL_REGISTRY:
        return await SKILL_REGISTRY[skill_name](args, pool)
    raise ValueError(f"Skill '{skill_name}' is not registered in SKILL_REGISTRY.")


@register_skill("search_web")
async def handle_search_web(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Search the web using Tavily Search API and return a formatted summary of results.
    
    Makes a genuine HTTP call to https://api.tavily.com/search with the user's query.
    Requires TAVILY_API_KEY to be set in the environment.
    Falls back gracefully if the key is missing.
    """
    import httpx
    from backend.config import get_settings

    settings = get_settings()
    query = args.get("query", "").strip()
    search_depth = args.get("search_depth", "basic")

    if not query:
        return {"response": "Please provide a search query.", "data": {}}

    if not getattr(settings, "TAVILY_ENABLED", False):
        return {
            "response": "Web search is currently disabled (TAVILY_ENABLED=False).",
            "data": {"query": query, "error": "TAVILY_ENABLED is False"},
        }

    if not settings.TAVILY_API_KEY:
        return {
            "response": f"Web search is not configured (TAVILY_API_KEY missing). To enable it, add your Tavily API key to the .env file.",
            "data": {"query": query, "error": "TAVILY_API_KEY not set"},
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "search_depth": search_depth,
                    "max_results": 3,
                    "include_answer": True,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        answer = data.get("answer", "")

        # Format a concise, readable response
        parts = []
        if answer:
            parts.append(f"**Quick Answer:** {answer}")
        if results:
            parts.append("\n**Top Results:**")
            for r in results[:3]:
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                snippet = r.get("content", "")[:200].strip()
                parts.append(f"• [{title}]({url})\n  {snippet}")

        summary = "\n".join(parts) if parts else f"No results found for: {query}"
        return {
            "response": summary,
            "data": {"query": query, "results": results, "answer": answer},
        }
    except httpx.HTTPStatusError as e:
        logger.error(f"Tavily API HTTP error: {e.response.status_code} — {e.response.text}")
        return {
            "response": f"Web search failed (HTTP {e.response.status_code}). Please try again.",
            "data": {"query": query, "error": str(e)},
        }
    except Exception as e:
        logger.error(f"Tavily search_web error: {e}")
        return {
            "response": f"Web search encountered an error: {e}",
            "data": {"query": query, "error": str(e)},
        }


# ---------------------------------------------------------------------------
# Scheduling & Calendar Skill Handlers
# ---------------------------------------------------------------------------

@register_skill("get_calendar_availability")
async def handle_get_calendar_availability(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query free/busy windows and existing schedule blocks from Google Calendar & tasks."""
    from datetime import datetime, date, timedelta, timezone
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import get_available_windows
    from backend.memory.structured import get_scheduling_preferences

    start_str = args.get("start_date")
    end_str = args.get("end_date")

    now = datetime.now(timezone.utc)
    if start_str:
        try:
            start_dt = datetime.combine(date.fromisoformat(start_str[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now

    if end_str:
        try:
            end_dt = datetime.combine(date.fromisoformat(end_str[:10]), datetime.max.time(), tzinfo=timezone.utc)
        except Exception:
            end_dt = start_dt + timedelta(days=7)
    else:
        end_dt = start_dt + timedelta(days=7)

    busy = await get_calendar_freebusy(start_dt, end_dt, pool=pool)

    prefs = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                prefs = await get_scheduling_preferences(conn)
        except Exception:
            pass

    free_windows = get_available_windows(
        busy,
        start_dt,
        end_dt,
        work_start_time=prefs.get("work_start_time", "09:00:00"),
        work_end_time=prefs.get("work_end_time", "18:00:00"),
        work_days=prefs.get("work_days", [1, 2, 3, 4, 5]),
        buffer_minutes=prefs.get("buffer_minutes", 15),
    )

    summary = (
        f"📅 Calendar Availability ({start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}):\n"
        f"• {len(busy)} busy event(s)/commitments\n"
        f"• {len(free_windows)} available focus window(s) within working hours"
    )

    return {
        "response": summary,
        "data": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "busy_count": len(busy),
            "busy_intervals": busy,
            "free_windows_count": len(free_windows),
            "free_windows": [
                {"start": w.start.isoformat(), "end": w.end.isoformat(), "duration_minutes": w.duration_minutes}
                for w in free_windows
            ],
        },
    }


@register_skill("propose_schedule")
async def handle_propose_schedule(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Run deterministic interval slot allocation for pending tasks."""
    from datetime import datetime, date, timedelta, timezone
    from backend.memory.structured import list_tasks, get_scheduling_preferences
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import get_available_windows, allocate_task_slots

    target_date_str = args.get("target_date")
    domain = args.get("domain")
    task_ids = args.get("task_ids")

    now = datetime.now(timezone.utc)
    if target_date_str:
        try:
            start_dt = datetime.combine(date.fromisoformat(target_date_str[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now
    end_dt = start_dt + timedelta(days=7)

    tasks: List[Dict[str, Any]] = []
    dep_map: Dict[int, List[int]] = {}
    prefs = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}

    if pool is not None:
        async with pool.acquire() as conn:
            from backend.memory.structured import get_all_dependencies_map
            prefs = await get_scheduling_preferences(conn)
            dep_map = await get_all_dependencies_map(conn)
            if task_ids:
                all_tasks = await list_tasks(conn, domain=domain)
                id_set = set(task_ids)
                tasks = [t for t in all_tasks if t["id"] in id_set]
            else:
                tasks = await list_tasks(conn, domain=domain, status="open", unscheduled_only=True)
                if not tasks:
                    tasks = await list_tasks(conn, domain=domain, status="open")

    busy = await get_calendar_freebusy(start_dt, end_dt, pool=pool)
    free_windows = get_available_windows(
        busy,
        start_dt,
        end_dt,
        work_start_time=prefs.get("work_start_time", "09:00:00"),
        work_end_time=prefs.get("work_end_time", "18:00:00"),
        work_days=prefs.get("work_days", [1, 2, 3, 4, 5]),
        buffer_minutes=prefs.get("buffer_minutes", 15),
    )

    allocation = allocate_task_slots(
        tasks,
        free_windows,
        buffer_minutes=prefs.get("buffer_minutes", 15),
        dependencies=dep_map,
    )

    scheduled_list = allocation["scheduled"]
    lines = [f"⚡ Proposed Schedule Plan: {allocation['summary']}"]
    for s in scheduled_list:
        lines.append(f"  • Task #{s['task_id']} '{s['title']}' ({s['domain']}): {s['scheduled_start'][:16]} → {s['scheduled_end'][:16]}")
    if allocation["unassigned"]:
        lines.append(f"\n⚠️ Unplaced tasks ({len(allocation['unassigned'])}):")
        for u in allocation["unassigned"]:
            lines.append(f"  • Task #{u['task_id']} '{u['title']}': {u['reason']}")

    return {
        "response": "\n".join(lines),
        "data": {
            "status": "proposed",
            "horizon": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "scheduled": allocation["scheduled"],
            "unassigned": allocation["unassigned"],
            "conflicts": allocation["conflicts"],
            "summary": allocation["summary"],
        },
    }


@register_skill("commit_schedule")
async def handle_commit_schedule(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Commit approved time slots to tasks and synchronize to Google Calendar."""
    from backend.memory.structured import get_task, update_task
    from backend.services.calendar import link_calendar_event
    from backend.services.scheduler import _ensure_utc

    assignments = args.get("assignments") or []
    rationale = args.get("rationale") or "Schedule committed by Compass Agent."

    if not assignments:
        return {"response": "No task assignments provided to commit.", "data": {"status": "error"}}

    committed_results: List[Dict[str, Any]] = []
    previous_states: List[Dict[str, Any]] = []

    if pool is not None:
        async with pool.acquire() as conn:
            for item in assignments:
                t_id = item.get("task_id")
                s_start = item.get("scheduled_start")
                s_end = item.get("scheduled_end")
                if not t_id or not s_start or not s_end:
                    continue

                prev = await get_task(conn, t_id)
                if prev:
                    previous_states.append({
                        "task_id": t_id,
                        "scheduled_start": prev.get("scheduled_start").isoformat() if prev.get("scheduled_start") else None,
                        "scheduled_end": prev.get("scheduled_end").isoformat() if prev.get("scheduled_end") else None,
                    })

                s_start_dt = _ensure_utc(s_start)
                s_end_dt = _ensure_utc(s_end)

                updated = await update_task(
                    conn,
                    t_id,
                    scheduled_start=s_start_dt,
                    scheduled_end=s_end_dt,
                )
                if updated:
                    cal_link = await link_calendar_event(
                        task_id=t_id,
                        start_dt=s_start_dt,
                        end_dt=s_end_dt,
                        title=updated["title"],
                        pool=pool,
                    )
                    committed_results.append({
                        "task_id": t_id,
                        "title": updated["title"],
                        "scheduled_start": s_start_dt.isoformat(),
                        "scheduled_end": s_end_dt.isoformat(),
                        "calendar_event_id": cal_link.get("google_event_id"),
                    })

    response_text = (
        f"✅ Successfully committed schedule for {len(committed_results)} task(s) and synced to Google Calendar.\n"
        f"Rationale: {rationale}"
    )

    return {
        "response": response_text,
        "data": {
            "status": "committed",
            "committed_count": len(committed_results),
            "committed_tasks": committed_results,
            "previous_states": previous_states,
            "rationale": rationale,
        },
    }


@register_skill("detect_schedule_conflicts")
async def handle_detect_schedule_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Analyze scheduled tasks, calendar events, and dependencies for timing conflicts and violations."""
    from datetime import datetime, date, timedelta, timezone
    from backend.memory.structured import list_tasks, get_all_dependencies_map
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import detect_schedule_conflicts

    start_date = args.get("start_date")
    end_date = args.get("end_date")
    now = datetime.now(timezone.utc)

    if start_date:
        try:
            s_dt = datetime.combine(date.fromisoformat(start_date[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            s_dt = now
    else:
        s_dt = now

    if end_date:
        try:
            e_dt = datetime.combine(date.fromisoformat(end_date[:10]), datetime.max.time(), tzinfo=timezone.utc)
        except Exception:
            e_dt = s_dt + timedelta(days=14)
    else:
        e_dt = s_dt + timedelta(days=14)

    tasks: List[Dict[str, Any]] = []
    dep_map: Dict[int, List[int]] = {}
    if pool is not None:
        async with pool.acquire() as conn:
            tasks = await list_tasks(conn)
            dep_map = await get_all_dependencies_map(conn)

    # External busy intervals
    ext_events: List[Dict[str, Any]] = []
    if pool is not None:
        all_busy = await get_calendar_freebusy(s_dt, e_dt, pool=pool)
        ext_events = [b for b in all_busy if b.get("source") != "compass_task"]

    conflicts = detect_schedule_conflicts(
        scheduled_tasks=tasks,
        external_events=ext_events,
        dependencies=dep_map,
        current_time=now,
    )

    if conflicts:
        lines = [f"⚠️ Detected {len(conflicts)} schedule conflict(s) or constraint violation(s):"]
        for c in conflicts:
            lines.append(f"  • [{c['conflict_type'].upper()}] {c.get('issue', c)}")
        resp_text = "\n".join(lines)
    else:
        resp_text = "✅ No schedule conflicts, dependency timing violations, or slipped deadlines detected."

    return {
        "response": resp_text,
        "data": {
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "scanned_tasks_count": len(tasks),
            "scanned_external_events_count": len(ext_events),
        },
    }



