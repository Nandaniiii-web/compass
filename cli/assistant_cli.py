"""
Compass — CLI Interface.

Interactive command-line client for the Compass personal AI assistant.
Communicates with the backend at http://localhost:8000 via httpx.

Usage:
    compass --help          Show all available commands
    compass chat            Interactive conversation REPL
    compass ask "question"  One-shot question
    compass tasks           View current tasks
    compass add "title"     Add a new task
    compass projects        List tracked projects
    compass log "summary"   Log a memory entry
    compass status          Dashboard overview

Install:
    pip install -e ./cli
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Fix Windows console encoding before importing Rich
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import httpx
import typer
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Python 3.11+ tomllib or fallback
try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Load environment & persistent config (~/.compass/config.toml)
# ---------------------------------------------------------------------------
load_dotenv()

CONFIG_DIR = Path.home() / ".compass"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def load_config() -> tuple[str, str]:
    """Read API base URL and AUTH_TOKEN from ~/.compass/config.toml, env vars, or defaults."""
    api_url = os.getenv("COMPASS_API_URL")
    auth_token = os.getenv("AUTH_TOKEN")

    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text(encoding="utf-8")
            if tomllib:
                cfg = tomllib.loads(content)
                api_url = api_url or cfg.get("api_url")
                auth_token = auth_token or cfg.get("auth_token")
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("api_url"):
                        api_url = api_url or line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("auth_token"):
                        auth_token = auth_token or line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

    return api_url or os.getenv("COMPASS_API_URL") or "http://localhost:8000", auth_token or os.getenv("AUTH_TOKEN") or "dev-token"


API_BASE, AUTH_TOKEN = load_config()

# Domain color branding
DOMAIN_COLORS = {
    "hackathon": "#f59e0b",   # Amber
    "coursework": "#3b82f6",  # Blue
    "code": "#10b981",        # Green
    "general": "dim white",
}

DOMAIN_EMOJI = {
    "hackathon": "🚀",
    "coursework": "📚",
    "code": "💻",
    "general": "📌",
}

STATUS_EMOJI = {
    "open": "⬚",
    "in_progress": "▶",
    "done": "✅",
    "overdue": "🔴",
}

PRIORITY_STYLE = {
    "urgent": "bold red",
    "high": "bold yellow",
    "medium": "white",
    "low": "dim",
}

# ---------------------------------------------------------------------------
# Rich Console
# ---------------------------------------------------------------------------
compass_theme = Theme({
    "hackathon": "bold #f59e0b",
    "coursework": "bold #3b82f6",
    "code": "bold #10b981",
    "general": "dim white",
    "compass.title": "bold cyan",
    "compass.error": "bold red",
    "compass.success": "bold green",
})
console = Console(theme=compass_theme, legacy_windows=False)

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="compass",
    help="🧭 Compass — Your personal AI assistant CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    """Return auth headers for API requests."""
    if not AUTH_TOKEN:
        console.print(
            "[compass.error]❌ AUTH_TOKEN not set. "
            "Copy .env.example → .env and set your token.[/]"
        )
        raise typer.Exit(1)
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


def _get(path: str, params: dict | None = None) -> dict:
    """Make an authenticated GET request to the backend."""
    try:
        resp = httpx.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[compass.error]❌ Cannot connect to backend at "
                      f"{API_BASE}. Is the server running?[/]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ API error {e.response.status_code}: "
                      f"{e.response.text}[/]")
        raise typer.Exit(1)


def _post(path: str, data: dict) -> dict:
    """Make an authenticated POST request to the backend."""
    try:
        resp = httpx.post(f"{API_BASE}{path}", headers=_headers(), json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[compass.error]❌ Cannot connect to backend at "
                      f"{API_BASE}. Is the server running?[/]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ API error {e.response.status_code}: "
                      f"{e.response.text}[/]")
        raise typer.Exit(1)


def _stream_chat(payload: dict) -> tuple[str, str | None, str | None]:
    """Consume the SSE streaming endpoint /api/chat/stream, printing tokens live.

    Returns (full_response, conversation_id, skill_used).
    Falls back cleanly to synchronous _post('/chat', payload) if streaming fails.
    """
    import json
    url = f"{API_BASE}/api/chat/stream"
    full_text = []
    conv_id = payload.get("conversation_id")
    skill_used = None

    try:
        with httpx.stream("POST", url, headers=_headers(), json=payload, timeout=60.0) as resp:
            if resp.status_code != 200:
                res = _post("/chat", payload)
                resp_text = res.get("response", "")
                console.print(resp_text)
                return resp_text, res.get("conversation_id"), res.get("skill_used")

            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except Exception:
                    continue

                ev_type = ev.get("type")
                if ev_type == "token":
                    val = ev.get("value", "")
                    console.print(val, end="", markup=False)
                    full_text.append(val)
                elif ev_type == "done":
                    conv_id = ev.get("conversation_id", conv_id)
                    skill_used = ev.get("skill_used")
                elif ev_type == "error":
                    err_msg = ev.get("message", "Unknown error")
                    console.print(f"\n[dim red]Error: {err_msg}[/]")

            console.print()
            return "".join(full_text), conv_id, skill_used

    except (httpx.ConnectError, httpx.HTTPError):
        res = _post("/chat", payload)
        resp_text = res.get("response", "")
        console.print(resp_text)
        return resp_text, res.get("conversation_id"), res.get("skill_used")


def _domain_text(domain: str) -> Text:
    """Return a Rich Text styled with the domain's color."""
    emoji = DOMAIN_EMOJI.get(domain, "")
    color = DOMAIN_COLORS.get(domain, "white")
    return Text(f"{emoji} {domain}", style=f"bold {color}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def chat():
    """💬 Interactive conversation with Compass (streaming tokens live)."""
    console.print(Panel(
        "[compass.title]🧭 Compass Chat[/]\n"
        "Type your message and press Enter. Type [bold]quit[/] or [bold]exit[/] to leave.",
        border_style="cyan",
    ))

    conversation_id: str | None = None

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye! 👋[/]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye! 👋[/]")
            break

        if not user_input.strip():
            continue

        payload = {"message": user_input}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        console.print("\n[bold green]Compass[/]: ", end="")
        _, new_conv_id, skill = _stream_chat(payload)
        if new_conv_id:
            conversation_id = new_conv_id
        if skill:
            console.print(f"[dim]({skill})[/]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Your question for Compass"),
):
    """❓ Ask a one-shot question (streamed live from Nebius Token Factory)."""
    console.print("\n[bold green]Compass[/]: ", end="")
    _, _, skill = _stream_chat({"message": query})
    if skill:
        console.print(f"[dim]({skill})[/]")


@app.command()
def add(
    title: str = typer.Argument(..., help="Task title"),
    domain: str = typer.Option("general", "--domain", "-d", help="Domain: hackathon, coursework, code, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    due: Optional[str] = typer.Option(None, "--due", help="Due date (YYYY-MM-DD)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Additional notes"),
):
    """➕ Add a new task via the chat endpoint."""
    parts = [f"Add task: {title}"]
    parts.append(f"--domain {domain}")
    if project:
        parts.append(f"--project {project}")
    if due:
        parts.append(f"--due {due}")
    if notes:
        parts.append(f"--notes {notes}")

    message = " ".join(parts)
    result = _post("/chat", {"message": message})

    console.print(f"\n[compass.success]✅ Task sent to Compass[/]")
    console.print(f"   Response: {result.get('response', '')}")


@app.command()
def tasks(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """📋 View current tasks."""
    params = {}
    if domain:
        params["domain"] = domain
    if project:
        params["project"] = project
    if status:
        params["status"] = status

    data = _get("/tasks", params)
    task_list = data.get("tasks", [])

    table = Table(
        title="🧭 Compass Tasks",
        title_style="bold cyan",
        border_style="dim",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Domain", width=12)
    table.add_column("Title", min_width=25)
    table.add_column("Status", width=12, justify="center")
    table.add_column("Priority", width=10, justify="center")
    table.add_column("Due", width=12, justify="center")
    table.add_column("Project", width=15)

    if not task_list:
        console.print(table)
        console.print("[dim]No tasks found.[/]")
        return

    for task in task_list:
        domain_name = task["domain"]
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        status_str = task["status"]
        status_icon = STATUS_EMOJI.get(status_str, "")
        priority_str = task["priority"]
        priority_style = PRIORITY_STYLE.get(priority_str, "white")
        project_name = task["project"]["name"] if task.get("project") else "—"
        due_str = task.get("due_date") or "—"

        table.add_row(
            str(task["id"]),
            Text(f"{emoji} {domain_name}", style=f"bold {color}"),
            task["title"],
            f"{status_icon} {status_str}",
            Text(priority_str, style=priority_style),
            due_str,
            project_name,
        )

    console.print(table)


@app.command()
def projects(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
):
    """📁 List tracked projects."""
    params = {}
    if domain:
        params["domain"] = domain

    data = _get("/projects", params)
    project_list = data.get("projects", [])

    console.print(Panel("[compass.title]🧭 Compass Projects[/]", border_style="cyan"))
    if not project_list:
        console.print("[dim]No projects found.[/]")
        return

    # Group by domain
    grouped: dict[str, list] = {}
    for proj in project_list:
        d = proj["domain"]
        grouped.setdefault(d, []).append(proj)

    for domain_name, projs in grouped.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        console.print(f"\n  [{color}]{emoji} {domain_name.upper()}[/{color}]")
        for p in projs:
            desc = f" — {p['description']}" if p.get("description") else ""
            console.print(f"    • [bold]{p['name']}[/]{desc}")


@app.command()
def log(
    summary: str = typer.Argument(..., help="Summary of what to log"),
    domain: str = typer.Option("code", "--domain", "-d", help="Domain: code, coursework, hackathon, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Associated project"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
):
    """📝 Log a memory entry (code context, coursework note, etc.)."""
    payload = {
        "summary": summary,
        "domain": domain,
        "project": project,
        "tags": tags,
    }
    result = _post("/api/log", payload)

    console.print(f"\n[compass.success]✅ Memory logged to pgvector with 768-dim embedding[/]")
    console.print(f"   Domain:   {_domain_text(domain)}")
    if project:
        console.print(f"   Project:  [bold]{project}[/]")
    if tags:
        console.print(f"   Tags:     [cyan]{tags}[/]")
    console.print(f"   Status:   {result.get('message', 'Logged')}")


@app.command()
def status():
    """📊 Dashboard overview — formatted terminal table across Hackathon, Coursework, Code."""
    data = _get("/dashboard")

    console.print(Panel(
        "[compass.title]🧭 Compass Cognitive Memory Overview[/]",
        border_style="cyan",
    ))

    table = Table(title="Cross-Domain Active Metrics", border_style="dim", show_lines=True)
    table.add_column("Domain", width=18)
    table.add_column("Projects", justify="center", width=10)
    table.add_column("Open Tasks", justify="center", width=12)
    table.add_column("Nearest Deadline", min_width=32)

    domains = data.get("domains", {})
    for domain_name, stats in domains.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        proj_count = stats.get("project_count", 0)
        task_count = stats.get("open_task_count", 0)
        deadline = stats.get("nearest_deadline")

        deadline_str = f"⏰ {deadline['title']} (due {deadline['due_date']})" if deadline else "—"
        table.add_row(
            Text(f"{emoji} {domain_name.upper()}", style=f"bold {color}"),
            str(proj_count),
            str(task_count),
            deadline_str,
        )

    console.print(table)
    total_tasks = data.get("total_open_tasks", 0)
    total_projects = data.get("total_projects", 0)
    console.print(f"\n  📊 [bold]{total_projects}[/] total projects  •  [bold]{total_tasks}[/] total open tasks across persistent memory\n")



@app.command()
def config(
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Set the Compass API base URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="Set the Bearer auth token"),
):
    """⚙️ View or update persistent CLI settings (~/.compass/config.toml)."""
    global API_BASE, AUTH_TOKEN
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if url is None and token is None:
        console.print(Panel(
            f"[bold cyan]Compass CLI Configuration[/]\n\n"
            f"  [bold]Config file:[/] {CONFIG_FILE}\n"
            f"  [bold]API URL:[/]     {API_BASE}\n"
            f"  [bold]Auth Token:[/]  {'*' * len(AUTH_TOKEN) if AUTH_TOKEN else '[dim]not set[/]'}",
            border_style="cyan",
        ))
        return

    new_url = url or API_BASE
    new_token = token or AUTH_TOKEN

    content = f'api_url = "{new_url}"\nauth_token = "{new_token}"\n'
    CONFIG_FILE.write_text(content, encoding="utf-8")
    API_BASE = new_url
    AUTH_TOKEN = new_token

    console.print(f"[compass.success]✅ Configuration saved to {CONFIG_FILE}[/]")
    console.print(f"   API URL:    {new_url}")
    console.print(f"   Auth Token: {'*' * len(new_token) if new_token else '[dim]not set[/]'}")


@app.command()
def login():
    """🔐 Interactively configure Compass API URL and Bearer token."""
    console.print(Panel(
        "[bold cyan]🧭 Compass Login[/]\n\n"
        "Configure your backend endpoint and authentication token.",
        border_style="cyan",
    ))
    new_url = Prompt.ask("Compass API Base URL", default=API_BASE)
    new_token = Prompt.ask("Bearer Auth Token", password=True, default=AUTH_TOKEN)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    content = f'api_url = "{new_url}"\nauth_token = "{new_token}"\n'
    CONFIG_FILE.write_text(content, encoding="utf-8")

    console.print(f"\n[compass.success]✅ Credentials saved to {CONFIG_FILE}[/]")


# ---------------------------------------------------------------------------
# Admin Sub-Typer
# ---------------------------------------------------------------------------
admin_app = typer.Typer(
    name="admin",
    help="🛠️ Admin maintenance commands (token usage, database consolidation)",
    no_args_is_help=True,
)
app.add_typer(admin_app, name="admin")


@admin_app.command("usage")
def admin_usage():
    """💰 Pretty-print token consumption and estimated USD cost across models."""
    data = _get("/admin/usage")

    console.print(Panel(
        "[compass.title]🧭 Compass Token Usage & Cost Overview[/]",
        border_style="cyan",
    ))

    table = Table(title="Model Consumption Breakdown", border_style="dim")
    table.add_column("Model", style="bold cyan")
    table.add_column("Calls", justify="right", style="magenta")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Est. Cost (USD)", justify="right", style="bold green")

    by_model = data.get("by_model", {})
    for m_id, stats in by_model.items():
        table.add_row(
            m_id.split("/")[-1],
            str(stats.get("calls", 0)),
            f"{stats.get('input_tokens', 0):,}",
            f"{stats.get('output_tokens', 0):,}",
            f"${stats.get('estimated_cost_usd', 0.0):.6f}",
        )

    console.print(table)
    console.print(
        f"\n  [bold]Total Input:[/]  {data.get('total_input_tokens', 0):,} tokens\n"
        f"  [bold]Total Output:[/] {data.get('total_output_tokens', 0):,} tokens\n"
        f"  [bold green]Total Estimated Cost:[/] ${data.get('total_estimated_cost_usd', 0.0):.6f}\n"
    )


@admin_app.command("consolidate")
def admin_consolidate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate without applying updates"),
    threshold: float = typer.Option(0.95, "--threshold", "-t", help="Cosine similarity threshold"),
    stale_days: int = typer.Option(7, "--stale-days", "-s", help="Days before marking thread stale"),
):
    """🧹 Trigger memory consolidation and overdue task flagging."""
    import asyncio
    from backend.jobs.consolidate import run_consolidation

    mode_text = "[yellow](DRY RUN)[/]" if dry_run else "[green](LIVE)[/]"
    console.print(f"🧭 Triggering memory consolidation {mode_text}...")

    payload = {
        "dry_run": dry_run,
        "similarity_threshold": threshold,
        "stale_thread_days": stale_days,
    }

    try:
        report = _post("/admin/consolidate", payload)
        console.print(f"\n[compass.success]✅ Consolidation complete[/]")
        console.print(f"  • Overdue tasks flagged: [bold]{report.get('overdue_tasks_flagged', 0)}[/]")
        console.print(f"  • Duplicate pairs merged: [bold]{report.get('duplicate_chunks_merged', 0)}[/]")
        console.print(f"  • Stale conversations rolled up: [bold]{report.get('stale_conversations_rolled_up', 0)}[/]")
    except Exception as e:
        console.print(f"[compass.error]❌ Remote consolidation request failed: {e}[/]")


# ---------------------------------------------------------------------------
# Agent — Autonomous ReAct multi-step planner
# ---------------------------------------------------------------------------
@app.command()
def agent(
    goal: str = typer.Argument(..., help="The goal for the agent to accomplish"),
    max_steps: int = typer.Option(8, "--max-steps", "-m", help="Max reasoning steps"),
    no_critic: bool = typer.Option(False, "--no-critic", help="Disable self-critique pass"),
    demo_reject: bool = typer.Option(False, "--demo-reject", help="Run in pre-loaded reject-path demo mode"),
):
    """🧠 Run the autonomous agent to plan, analyze, and act on your tasks.

    The agent reasons step-by-step, calling tools autonomously to gather data
    and propose solutions. State-mutating actions require your confirmation.

    Examples:
        compass agent "Plan my week considering all deadlines"
        compass agent "Flag deadline conflicts and suggest resolutions"
        compass agent "Write a retrospective for the Compass project"
        compass agent --demo-reject "Reschedule conflicting tasks"
    """
    import json as _json

    console.print(Panel(
        f"[bold]Goal:[/] {goal}\n"
        f"[dim]Max steps: {max_steps} | Critic: {'disabled' if no_critic else 'enabled'}[/]",
        title="🧠 Compass Agent",
        border_style="blue",
    ))

    # Step type → Rich style mapping
    STEP_COLORS = {
        "think": ("bold blue", "🧠 THINKING"),
        "tool_call": ("bold yellow", "🔧 TOOL CALL"),
        "observe": ("bold green", "👁️ RESULT"),
        "confirm_request": ("bold red", "⚠️ CONFIRM"),
        "critic": ("bold magenta", "⚖️ SELF-CRITIQUE"),
        "synthesize": ("bold cyan", "✨ SYNTHESIS"),
        "error": ("bold red", "❌ ERROR"),
        "done": ("bold green", "✅ COMPLETE"),
    }

    pending_actions = []
    run_id = None

    try:
        with httpx.stream(
            "POST",
            f"{API_BASE}/api/agent/run",
            json={
                "goal": goal,
                "max_steps": max_steps,
                "enable_critic": not no_critic,
                "confirmed_actions": [],
            },
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue

                    try:
                        event = _json.loads(line[6:])
                    except _json.JSONDecodeError:
                        continue

                    if event.get("run_id"):
                        run_id = event["run_id"]

                    step_type = event.get("type", "think")
                    content = event.get("content", "")
                    step_n = event.get("step", 0)
                    elapsed = event.get("elapsed_ms", 0)
                    tool = event.get("tool", "")
                    args = event.get("args", {})

                    color, label = STEP_COLORS.get(step_type, ("dim", "STEP"))

                    if step_type == "tool_call":
                        args_str = _json.dumps(args) if args else ""
                        console.print(Panel(
                            f"[yellow]{tool}[/]({args_str})",
                            title=f"[{color}]{label}[/] [dim]Step {step_n} · {elapsed}ms[/]",
                            border_style="yellow",
                            padding=(0, 1),
                        ))
                    elif step_type == "confirm_request":
                        console.print(Panel(
                            content,
                            title=f"[{color}]{label}[/]",
                            border_style="red",
                            padding=(0, 1),
                        ))
                        pending_actions.append({"tool": tool, "args": args})
                    elif step_type == "done":
                        try:
                            done_data = _json.loads(content)
                            tools_list = ", ".join(done_data.get("tools_used", [])) or "none"
                            total = done_data.get("total_steps", 0)
                            pending_count = len(done_data.get("pending_confirmations", []))
                            done_text = f"Completed in {total} steps. Tools: {tools_list}."
                            if pending_count > 0:
                                done_text += f"\n⚠️ {pending_count} action(s) pending your approval."
                            console.print(Panel(done_text, title=f"[{color}]{label}[/]", border_style="green"))
                        except _json.JSONDecodeError:
                            console.print(Panel(content, title=f"[{color}]{label}[/]", border_style="green"))
                    else:
                        border = color.split()[-1] if " " in color else "blue"
                        console.print(Panel(
                            content,
                            title=f"[{color}]{label}[/] [dim]Step {step_n} · {elapsed}ms[/]",
                            border_style=border,
                            padding=(0, 1),
                        ))

    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ Agent request failed: {e.response.status_code}[/]")
        return
    except httpx.ConnectError:
        console.print(f"[compass.error]❌ Cannot connect to backend at {API_BASE}[/]")
        return

    # Handle pending confirmations interactively
    if pending_actions:
        console.print()
        console.print(f"[bold red]⚠️ {len(pending_actions)} action(s) need your approval:[/]")
        for i, action in enumerate(pending_actions):
            console.print(f"  {i+1}. [yellow]{action['tool']}[/]({_json.dumps(action['args'])})")

        if demo_reject:
            console.print("[yellow]⚡ Demo Trigger: Simulating user decline for deadline conflict...[/]")
            confirm = "no"
            feedback = "Do not move OS Homework 2 deadline"
        else:
            confirm = Prompt.ask("\nApprove these actions?", choices=["yes", "no"], default="no")
            feedback = None

        if confirm == "yes":
            console.print("[green]Executing approved actions...[/]")
            try:
                resp = httpx.post(
                    f"{API_BASE}/api/agent/confirm",
                    json={"actions": pending_actions, "run_id": run_id if 'run_id' in locals() else None},
                    headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                for r in results:
                    status = r.get("status", "unknown")
                    tool_name = r.get("tool", "")
                    if status == "success":
                        console.print(f"  ✅ {tool_name}: success")
                    else:
                        console.print(f"  ❌ {tool_name}: {r.get('message', 'failed')}")
            except Exception as e:
                console.print(f"[compass.error]❌ Failed to execute actions: {e}[/]")
        else:
            if not feedback:
                feedback = Prompt.ask("Reason / alternative plan instruction (optional)", default="User rejected this action")
            console.print(f"[dim]Actions rejected ({feedback}). Feeding rejection back to agent for re-planning...[/]")
            active_rid = run_id if 'run_id' in locals() else None
            if active_rid:
                try:
                    with httpx.stream(
                        "POST",
                        f"{API_BASE}/api/agent/run",
                        json={
                            "run_id": active_rid,
                            "action": "reject",
                            "feedback": feedback,
                        },
                        timeout=120.0,
                    ) as resp:
                        resp.raise_for_status()
                        buf = ""
                        for ch in resp.iter_text():
                            buf += ch
                            while "\n" in buf:
                                l, buf = buf.split("\n", 1)
                                l = l.strip()
                                if not l.startswith("data: "):
                                    continue
                                try:
                                    ev = _json.loads(l[6:])
                                except Exception:
                                    continue
                                stype = ev.get("type", "think")
                                c = ev.get("content", "")
                                col, lbl = STEP_COLORS.get(stype, ("dim", "STEP"))
                                if stype == "synthesize":
                                    console.print(Panel(c, title=f"[{col}]{lbl}[/]", border_style="cyan"))
                                elif stype != "done":
                                    console.print(Panel(c, title=f"[{col}]{lbl}[/]", border_style="blue", padding=(0, 1)))
                except Exception as ex:
                    console.print(f"[compass.error]❌ Re-planning failed: {ex}[/]")


@app.command("agent-undo")
def agent_undo(
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Specific run ID to revert"),
    log_id: Optional[int] = typer.Option(None, "--log-id", "-l", help="Specific audit log entry ID to revert"),
):
    """Revert an agent-executed mutation using the audit log."""
    try:
        resp = httpx.post(
            f"{API_BASE}/api/agent/undo",
            json={"run_id": run_id, "audit_log_id": log_id},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            console.print(f"[green]✅ {data.get('message')}[/]")
            if "reverted" in data:
                console.print(f"[dim]Reverted: {data['reverted']}[/]")
        else:
            console.print(f"[yellow]⚠️ {data.get('message', 'Nothing to undo')}[/]")
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to undo: {e}[/]")


@app.command("agent-activity")
def agent_activity(limit: int = typer.Option(15, "--limit", "-n", help="Number of entries to show")):
    """📋 View recent agent mutations from the audit log with per-item IDs for undo."""
    try:
        resp = httpx.get(f"{API_BASE}/api/agent/activity?limit={limit}", timeout=15.0)
        resp.raise_for_status()
        entries = resp.json().get("activity", [])

        if not entries:
            console.print("[dim]No agent activity recorded yet.[/]")
            return

        table = Table(
            title="📋 Agent Activity Log (Audit Trail)",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        table.add_column("Log ID", style="bold", justify="right")
        table.add_column("Tool", style="yellow")
        table.add_column("Target", style="white")
        table.add_column("Status", style="bold")
        table.add_column("Timestamp", style="dim")
        table.add_column("Run ID", style="dim cyan")

        for item in entries:
            lid = str(item.get("id", ""))
            tool = item.get("tool", "")
            tbl = item.get("affected_table", "tasks")
            aff_id = str(item.get("affected_id") or "")
            reverted = item.get("is_reverted", False)
            st_badge = "[red]REVERTED[/]" if reverted else "[green]ACTIVE[/]"
            ts = item.get("created_at", "")[:19].replace("T", " ")
            rid = (item.get("run_id") or "")[:12]

            table.add_row(lid, tool, f"{tbl} #{aff_id}", st_badge, ts, rid)

        console.print(table)
        console.print("[dim]Revert any mutation using: compass agent-undo --log-id <ID>[/]")

    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch activity: {e}[/]")


@app.command("agent-stats")
def agent_stats():
    """⚖️ Surface real self-critique pass effectiveness metrics."""
    try:
        resp = httpx.get(f"{API_BASE}/api/agent/critique-stats", timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        tot = data.get("total_runs_analyzed", 0)
        crit = data.get("runs_with_critique", 0)
        flagged = data.get("critique_issues_flagged", 0)
        rate = data.get("critique_effectiveness_rate", 0.0)

        panel_content = (
            f"[bold]Total Agent Runs Analyzed:[/] {tot}\n"
            f"[bold]Runs with Self-Critique Pass:[/] {crit}\n"
            f"[bold]Critique Issues Flagged / Revised:[/] [yellow]{flagged}[/]\n"
            f"[bold]Critique Intervention Rate:[/] [cyan]{rate}%[/]\n\n"
            "[dim]A single-model self-critique pass checks plan constraints against real database data before final synthesis.[/]"
        )
        console.print(Panel(panel_content, title="⚖️ Self-Critique Effectiveness", border_style="magenta"))

        recent = data.get("recent_critique_evaluations", [])
        if recent:
            t = Table(title="Recent Self-Critique Evaluations", box=box.SIMPLE, header_style="bold magenta")
            t.add_column("Run ID", style="dim cyan")
            t.add_column("Flagged Issue?", justify="center")
            t.add_column("Critique Summary", style="white")

            for ev in recent[:5]:
                f_icon = "⚠️ YES" if ev.get("flagged_issue") else "✅ NO"
                t.add_row(ev.get("run_id", "")[:12], f_icon, ev.get("critique_summary", "")[:80])
            console.print(t)

    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch critique stats: {e}[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app()

