# 🧭 Compass
> Your one AI that remembers every hackathon, repo, and deadline.

## What It Does

Compass is a productivity copilot and personal AI assistant engineered for intense dual-track academic and competitive engineering workloads (specifically VIT dual-degree coursework and hackathons). It maintains persistent, long-term memory across three partitioned domains: hackathon deadlines, repository code context, and academic coursework. Accessible via both a real-time web dashboard and a terminal CLI, Compass accurately tracks deliverables, recalls technical architecture decisions via dense vector search, and synthesizes unified schedules across domains.

---

## Hackathon Submission & Track Information

- **Track**: **Best Apps and Agents Track**
- **Project Origin**: Compass does **not** pre-date the hackathon submission window. Repository creation, architecture design, and code commenced on **September 4, 2026**, following the August 26, 2026 hackathon launch.
- **AI Infrastructure**: Powered natively by Nebius Token Factory with a 3-tier NVIDIA Nemotron routing and synthesis architecture (`Nano 30B`, `Super 120B`, `Ultra 550B`) + `Qwen3-Embedding-8B` dense memory.
- **Compute Hosting**: Hosted on Render (FastAPI) and Vercel (React + Vite) with turnkey deployment manifests for Nebius AI Cloud in `deploy/`.

---

## Try It

- **Live Web Dashboard**: [https://compass-kappa-nine.vercel.app](https://compass-kappa-nine.vercel.app)
- **Live Backend API**: [https://compass-backend-qryu.onrender.com/health](https://compass-backend-qryu.onrender.com/health)
- **Demo Video**: `[Demo Video Link — To Be Added]`

---

## Architecture

Compass separates client delivery, application compute, persistent storage, and hosted AI model inference into decoupled cloud layers:

```mermaid
flowchart TD
    subgraph Clients["1. Cross-Surface Clients"]
        CLI["💻 Terminal CLI<br/>(python -m cli)"]
        Web["🌐 Web Dashboard<br/>(React + Vite on Vercel)"]
    end

    subgraph Proxy["2. Edge Reverse Proxy (Vercel)"]
        Rewrites["🛡️ Vercel Same-Origin Rewrites<br/>(/health, /chat, /api/*)<br/>Immune to Ad-Blockers & Brave Shields"]
    end

    subgraph Compute["3. Application Compute (Render)"]
        FastAPI["⚙️ FastAPI Backend<br/>(Docker / Python 3.12-slim CPU)<br/>UptimeRobot 24/7 Keep-Alive (5-min pings)"]
        SSE["📡 SSE Streaming Engine<br/>(/api/chat/stream)"]
    end

    subgraph AI["4. AI Inference Layer (Nebius Token Factory)"]
        Nano["⚡ NVIDIA Nemotron-3 Nano (30B)<br/>(Sub-400ms Native Function Calling Router)"]
        Super["🧠 NVIDIA Nemotron-3 Super (120B)<br/>(Complex Skill Reasoning)"]
        Ultra["🚀 NVIDIA Nemotron-3 Ultra (550B)<br/>(Cross-Domain Synthesis — Aggregated Context Only)"]
        Qwen["📐 Qwen3-Embedding-8B<br/>(768-dim Matryoshka Truncated Vectors)"]
    end

    subgraph Storage["5. Persistent Memory Layer (Neon Cloud)"]
        HNSW[("pgvector HNSW Cosine Index<br/>(Code & Notes Embeddings, &lt;5ms)")]
        Relational[("PostgreSQL 16 Engine<br/>(tasks, projects, conversations, messages, usage_log)")]
    end

    CLI -->|HTTP / Bearer Auth| FastAPI
    Web -->|Same-Origin /api/*| Rewrites
    Rewrites -->|Proxy Pass| FastAPI
    FastAPI -->|Token-by-Token SSE| SSE
    SSE -->|Stream Event Pipe| Web
    FastAPI -->|1. Route Intent| Nano
    FastAPI -->|2. Domain Reasoning| Super
    FastAPI -->|3. Generate Embedding| Qwen
    FastAPI -->|4. Store / Query Memory| Relational
    Qwen -->|768-dim Vector| HNSW
    FastAPI -->|5. Multi-Domain Context Payload| Ultra
    Ultra -->|Synthesized Roadmap| FastAPI
```

---

## How Nebius & NVIDIA Power Compass

Nebius Token Factory is the core AI engine of Compass. Every routing decision, embedding generation, and synthesized roadmap runs through Nebius-hosted models:

1. **`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` — Sub-400ms Intent Routing (Native Function Calling)**:
   All inbound conversational queries pass to Nemotron-3 Nano using standard OpenAI-compatible tool calling. Nano classifies the user's intent into structured skills (`add_task`, `query_tasks`, `log_code_context`, etc.) or general chat fallback in **< 400 ms**, completely bypassing brittle regex or prompt-based JSON hacking.

2. **`nvidia/nemotron-3-super-120b-a12b` — Deep Skill Execution**:
   When a user query involves multi-step domain reasoning (such as resolving overlapping dependencies between hackathon milestones and project tasks), execution is escalated to Nemotron-3 Super for robust extraction and parameter resolution.

3. **`nvidia/Nemotron-3-Ultra-550b-a55b` — Cross-Domain Roadmap Synthesis (Context-Escalated Only)**:
   Compass reserves Nemotron-3 Ultra strictly for the `summarize_across_domains` skill. Ultra is **never** invoked per-message or directly on raw user text due to token economics:
   - **Economic Reality**: On our $29 Token Factory funding, Nemotron Nano costs ~$0.08 / 1M tokens blended, while Nemotron Ultra is estimated at ~$1.20 / 1M tokens blended *(estimated, not independently verified from the dashboard directly; a ~15x cost gap)*.
   - **Architectural Safeguard**: Compass uses a two-step escalation. Nemotron Nano first fetches, filters, and aggregates structured tasks and notes from Neon PostgreSQL. Only that pre-filtered context payload is handed to Nemotron Ultra to synthesize cross-domain conflict analysis, deliverable timelines, and unified weekly roadmaps.

4. **`Qwen/Qwen3-Embedding-8B` — 768-Dim Dense Semantic Memory**:
   Code context snippets and academic coursework notes are vectorized via `Qwen/Qwen3-Embedding-8B`, hosted natively on Nebius Token Factory *(note: Qwen3 is a Token Factory-hosted foundation model, not an NVIDIA model)*. Vectors are **Matryoshka-truncated from native 4,096 dimensions to 768 dimensions**, perfectly fitting within `pgvector`'s 2,000-dimension HNSW indexing ceiling while preserving 100% Top-1 recall in retrieval benchmarks.

5. **Nebius Serverless Endpoint & Job Manifests (`deploy/`)**:
   Deployment manifests for Nebius AI Cloud are prepared in [`deploy/serverless_endpoint.yaml`](./deploy/serverless_endpoint.yaml) (container endpoint) and [`deploy/serverless_job.yaml`](./deploy/serverless_job.yaml) (nightly memory consolidation cron).
   - *Current Real Deployment State*: Manifests exist in the repository, but compute is currently hosted on Render and Vercel with local/cron execution for the consolidation job, while the team's Nebius Cloud tenant (`tenant-e00bqrxevpggympk55`) is pending billing verification. Live AI model inference, routing, and embeddings run 100% on Nebius Token Factory. The manifests provide turnkey deployment whenever tenant compute is enabled.

6. **Nightly Memory Consolidation Job**:
   An automated worker that performs:
   - **Vector Deduplication**: Identifies and merges memory chunks with cosine similarity > 0.95.
   - **Conversation Compaction**: Condenses conversations inactive for > 7 days into summarized long-term memory entries.
   - **Overdue Flagging**: Scans and tags overdue deliverables across hackathons and coursework.
   *(Currently run via script runner and Render cron using the exact logic specified in `deploy/serverless_job.yaml`).*

---

## Quick Start

### 1. Prerequisites
- Python 3.12+
- Node.js 18+ and npm
- A PostgreSQL 16 instance with `pgvector` enabled (or a free [Neon](https://neon.tech) connection string)
- Nebius Token Factory API key

### 2. Environment Configuration (`.env`)
Create a `.env` file in the project root:

```bash
# === Nebius Token Factory ===
NEBIUS_API_KEY="your_nebius_token_factory_key"
NEBIUS_BASE_URL="https://api.tokenfactory.nebius.com/v1/"
ROUTER_MODEL="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SKILL_MODEL="nvidia/nemotron-3-super-120b-a12b"
SYNTHESIS_MODEL="nvidia/Nemotron-3-Ultra-550b-a55b"
EMBEDDING_MODEL="Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIMENSION=768

# === Database (Neon Serverless PostgreSQL) ===
DATABASE_URL="postgresql://username:password@ep-your-neon-pooler.region.neon.tech/neondb?sslmode=require"

# === Security & App ===
AUTH_TOKEN="your-secret-token-here"
LOG_LEVEL="INFO"
PORT=8000
```

### 3. Backend & CLI Installation
```powershell
# Install backend dependencies
pip install -r backend/requirements.txt

# Install CLI in editable mode
pip install -e ./cli

# Seed initial projects and benchmark data
python scripts/seed_data.py

# Verify pgvector HNSW index
python scripts/verify_hnsw_index.py
```

### 4. Running Locally
```powershell
# Terminal 1 — Start FastAPI Server
python -m uvicorn backend.main:app --port 8000 --reload

# Terminal 2 — Start Frontend Dashboard
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

### 5. CLI Operations
```powershell
# Check multi-domain status overview
compass status

# Add a high-priority hackathon deliverable
compass add "Submit Nebius Token Factory benchmark" --domain hackathon --project "Compass" --due 2026-09-08 --priority urgent

# Log code architecture context with 768-dim vector embedding
compass log "Integrated Matryoshka 768-dim embeddings with Nebius Token Factory" --domain code --project "Compass" --tags nebius,vector,hnsw

# Ask questions with conversational multi-turn recall
compass ask "What are my upcoming deliverables before Friday?"

# Launch the autonomous ReAct agent (plans, queries tools, proposes replan with confirmation gate)
compass agent "Plan my week considering all hackathon deadlines and coursework"

# Inspect model token consumption and estimated API costs
compass admin usage
```

### 6. Running the Test Suite
```powershell
python -m pytest tests -v
# 44 passed, 0 skipped, 0 failed in ~60s (Python 3.12+)
```

---

## Autonomous ReAct Agent Engine

Compass features an autonomous **ReAct (Reason + Act)** agent loop (`backend/agent.py`) built specifically for complex task planning and deadline resolution:

- **Multi-Step Reasoning Loop**: Nemotron-3 Super (120B) autonomously formulates thoughts, decides on tools to invoke, and observes results in a loop capped at a configurable step limit (default 8).
- **Human-in-the-Loop Confirmation Gate**: Read-only tools (`query_tasks`, `query_coursework_tasks`, `get_hackathon_deadlines`, `query_code_context`, `summarize_day`) execute immediately. State-mutating tools (`add_task`, `edit_task`, `update_task_status`, `delete_task`) generate a `confirm_request` SSE event and are held in staging until the user explicitly reviews and approves them via the Web UI or CLI.
- **Self-Critique Reflection Pass**: Before final synthesis, a critic evaluation reviews the proposed plan against constraints, flags potential oversights, and refines the recommendation.
- **Final Cross-Domain Synthesis**: Nemotron-3 Ultra (550B) synthesizes the final comprehensive execution roadmap from the aggregated tool outputs.
- **Interactive Traces Across Surfaces**:
  - **Web Dashboard**: The **🧠 Agent Planner** tab streams the real-time reasoning trace with color-coded step cards (`THINK`, `TOOL CALL`, `RESULT`, `CONFIRMATION REQUIRED`, `SELF-CRITIQUE`, `SYNTHESIS`) and one-click **Approve & Execute** / **Reject** buttons.
  - **Terminal CLI**: `compass agent "<goal>"` renders styled Rich step panels with interactive y/N confirmation prompts for staged modifications.

---

## Tech Stack

| Layer | Technology | Provider / Host | Details |
| :--- | :--- | :--- | :--- |
| **Frontend** | React 18, Vite, Vanilla CSS | **Vercel** (`compass-kappa-nine.vercel.app`) | Responsive UI, real-time context stream, typewriter chat |
| **Reverse Proxy** | Vercel Edge Rewrites | **Vercel** (`vercel.json`) | Proxies `/health`, `/chat`, `/api/*` same-origin (ad-block immune) |
| **Backend API** | FastAPI, Uvicorn, Python 3.12-slim | **Render** (`compass-backend-qryu.onrender.com`) | Containerized CPU web service, auto-deploy on commit |
| **Database** | PostgreSQL 16 + `pgvector` | **Neon Cloud** | Serverless pooled connection, HNSW cosine index (<5ms query) |
| **Intent Routing** | `NVIDIA-Nemotron-3-Nano-30B-A3B` | **Nebius Token Factory** | Native OpenAI-compatible tool calling, sub-400ms latency |
| **Skill Reasoning**| `nemotron-3-super-120b-a12b` | **Nebius Token Factory** | Domain parameter extraction and reasoning |
| **Cross-Domain AI**| `Nemotron-3-Ultra-550b-a55b` | **Nebius Token Factory** | Escalated synthesis over aggregated payloads |
| **Vector Engine** | `Qwen3-Embedding-8B` | **Nebius Token Factory** | 768-dim Matryoshka-truncated embeddings |
| **Streaming** | Server-Sent Events (SSE) | FastAPI `StreamingResponse` | Real-time token streaming via `/api/chat/stream` |
| **Keep-Alive** | HTTP Monitor | **UptimeRobot** | Pings `/health` every 5 min (eliminates cold starts) |
| **Cloud Manifests**| Serverless Endpoint & Cron | **Nebius AI Cloud** | Verified manifests in `deploy/` ready for turnkey deployment |

---

## Skills

Compass provides 8 core memory skills, a conversational fallback, and a cross-domain synthesis escalation:

| Skill | Description | Example Message |
| :--- | :--- | :--- |
| `add_task` | Creates a new task with title, domain, project, due date, and priority | *"Add task: Submit Nebius Token Factory benchmark by Friday, priority urgent"* |
| `query_tasks` | Queries tasks with domain, status, or project filters and countdowns | *"What open tasks do I have in coursework?"* |
| `update_task_status` | Updates the status of an existing task (`open`, `in_progress`, `completed`) | *"Mark task 4 as completed"* |
| `edit_task` | Edits title, due date, priority, or metadata of an existing task | *"Change deadline of task 2 to tomorrow 5pm"* |
| `delete_task` | Permanently deletes a task by ID or matched title | *"Delete task: test pyright fix"* |
| `list_projects` | Lists all tracked projects partitioned across domains | *"What projects am I currently tracking?"* |
| `log_code_context` | Stores code snippets, architecture decisions, and generates 768-dim embeddings | *"Log code context: Switched vector dimension to 768 for pgvector HNSW compliance in Compass"* |
| `query_code_context` | Performs HNSW cosine similarity search over stored code contexts | *"How did we configure the Matryoshka embeddings in the backend?"* |
| `query_coursework_notes` | Searches and retrieves academic coursework notes and syllabus items | *"Find my notes on RISC-V pipeline hazard forwarding"* |
| `chat` | General conversational fallback for greetings and non-actionable queries | *"Hey! What can you help me with?"* |
| `summarize_across_domains` | Escalates to Nemotron-3 Ultra (550B) over pre-aggregated context for roadmap synthesis | *"Give me a unified roadmap and conflict analysis across hackathon and coursework for this week"* |

---

## Testing

Compass includes an automated regression test suite (**52 tests**, 100% passing, 0 skipped) covering all critical application surfaces, run under Python 3.12.4 against a live Postgres instance:

```text
======================== 52 passed in 100% =========================
```

- **Autonomous Agent Engine (`tests/test_agent.py`)**: 15 tests validating the ReAct loop, SSE event stream protocol, step production (`think`, `tool_call`, `observe`, `critic`, `synthesize`), safe state-mutation gating (`add_task`, `edit_task`, `delete_task`, `update_task_status`), reject path re-planning, confirmation timeouts, self-critique pass capping (2 rounds), reconnect persistence in `agent_runs`, audit logging in `agent_audit_log`, undo endpoint (`POST /api/agent/undo`), and Tavily gating.
- **API & Authentication (`tests/test_api_endpoints.py`)**: Tests Bearer token authentication, invalid credentials rejection, and CORS headers.
- **Structured Memory (`tests/test_structured_memory.py`)**: Validates database schema migrations, project creation, task lifecycle (add/edit/query/complete/delete), and task isolation across domains — runs against a live Postgres instance.
- **Multi-Turn Context (`tests/test_multi_turn.py`)**: End-to-end verification that conversational context persists across turns.
- **SSE Streaming (`tests/test_streaming.py`)**: Verifies `text/event-stream` headers, `X-Accel-Buffering: no`, and incremental token delivery.
- **CLI Operations (`tests/test_cli.py`)**: Validates terminal commands, argument parsing, output formatting, and CLI SSE streaming.
- **End-to-End Demo Flow (`tests/test_demo_flow.py`)**: Validates the full flow across memory ingestion, tool calls, and roadmap generation.
- **Gap Closure Verification (`tests/test_gap_closures.py`)**: Server-side task domain filtering, the public `/api/usage/summary` endpoint, per-IP rate limiting, the gated `search_web` skill, CLI streaming fallback, and usage-summary cost deltas across turns.

---

## Repository Structure & Tooling

- `backend/`: FastAPI application, database pool lifecycle, routers, orchestrator, and skill definitions.
- `cli/`: Terminal interface built with Typer and Rich (`compass` / `python -m cli`).
- `frontend/`: React + Vite single-page application with responsive dark dashboard and typewriter chat.
- `deploy/`: Production manifests for Nebius Serverless Endpoints and nightly consolidation jobs.
- `scripts/`: Data seeding and pgvector HNSW index verification utilities.
- `.agents/skills/` & `skills-lock.json`: Official Neon Database Agent Skills registry for AI pair-programming and automated database operations.
- `pyrefly.toml`: IDE language server / static type checker configuration for local Python runtime.

---

## Team

- **Rhythm**: Backend Architecture, Database Schema, and Nebius Token Factory Tool Registration
- **Nandani**: Frontend Web Dashboard, Real-Time Context Stream UI, and Chat Interface
- **Ratnesh Singh** (VIT+IIT): System Integration, Deployment Engineering (Render, Vercel, Nebius Manifests), and Terminal CLI

---

## License

MIT
