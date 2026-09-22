# Autonomous Iterative Learning Agent

An autonomous AI agent system that solves arbitrary tasks through iterative experimentation, observation, and accumulated learning. The agent follows an **Observe → Hypothesize → Act → Evaluate → Learn → Repeat** cycle with persistent vector-based memory.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│  Dashboard │ Live View │ Rules │ Memory │ Settings       │
└───────────────────────┬─────────────────────────────────┘
                        │ REST API + WebSocket
┌───────────────────────┴─────────────────────────────────┐
│                   FastAPI Backend                         │
│  Auth │ Tasks │ Memory │ Settings │ WebSocket             │
└───────────────────────┬─────────────────────────────────┘
                        │ Redis Queue
┌───────────────────────┴─────────────────────────────────┐
│                   Worker Process                          │
│  ┌─────────────────────────────────────────────────┐     │
│  │              Agent Orchestrator                  │     │
│  │  Task Analyzer → Experiment Planner → Action     │     │
│  │  → Evaluator → Learning Extractor → Strategy     │     │
│  │  → Rule Discovery → Synthesis                    │     │
│  └─────────────────────────────────────────────────┘     │
└─────────┬──────────┬──────────┬──────────┬──────────────┘
          │          │          │          │
     PostgreSQL    Redis     Qdrant     Ollama
     (state)      (queue)   (vectors)  (LLM)
```

## Key Principle

```
LEARNING = ALWAYS ON
MEMORY RETRIEVAL = USER CONTROLLED
```

These are **independent mechanisms**. The "Use Persistent Learnings" toggle controls ONLY whether previously stored knowledge is retrieved. Learning generation and storage continues unconditionally.

## Prerequisites

- **Ollama** (for local LLM inference)
- **Python 3.12+**
- **Node.js 20+**
- *Docker is completely optional (the project now supports 100% zero-Docker local mode)*

## Quick Start (No Docker Required)

Double-click `start.bat` in the project root, OR run:

### Terminal 1 (Backend API)
```bash
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --port 8000 --reload
```

### Terminal 2 (Frontend UI)
```bash
cd frontend
npm run dev
```

Open your browser at **http://localhost:5173**!

---

## Alternative: Quick Start with Docker

### 1. Clone and configure

```bash
git clone <repository-url>
cd autonomous-learning-agent
cp .env.example .env
# Edit .env if needed (defaults work for local development)
```

### 2. Install and start Ollama

```bash
# Download from https://ollama.com
# Then pull a model:
ollama pull phi3:mini          # Recommended for 8GB RAM / 4GB VRAM
# OR
ollama pull llama3.2:3b        # Alternative small model
```

### 3. Start all services

```bash
docker-compose up -d
```

This starts:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **Qdrant**: http://localhost:6333 (dashboard at /dashboard)

### 4. Create an account and start experimenting

Open http://localhost:5173, register an account, and create your first task.

## Local Development (without Docker)

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL, Redis, Qdrant (via Docker or local installs)
docker-compose up -d postgres redis qdrant

# Run the API server
uvicorn app.main:app --reload --port 8000

# In another terminal, run the worker
python -m app.workers.task_worker
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Ollama Setup

Ollama is the default LLM provider. It runs locally and supports many open models.

### Installation

- **Windows**: Download from https://ollama.com/download
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`
- **Mac**: `brew install ollama`

### Model Recommendations

| RAM | VRAM | Recommended Model | Command |
|-----|------|-------------------|---------|
| 8 GB | 4 GB | phi3:mini | `ollama pull phi3:mini` |
| 16 GB | 8 GB | llama3.1:8b | `ollama pull llama3.1:8b` |
| 32 GB+ | 16 GB+ | llama3.1:70b | `ollama pull llama3.1:70b` |

### Verify Ollama is running

```bash
curl http://localhost:11434/api/tags
```

## PostgreSQL Setup

PostgreSQL stores all structured application state: tasks, iterations, rules, learnings, snapshots, strategies.

With Docker (recommended):
```bash
docker-compose up -d postgres
```

The database is auto-created with the credentials in `.env`.

## Qdrant Setup

Qdrant stores vector embeddings for synthesized learnings, enabling semantic memory retrieval.

```bash
docker-compose up -d qdrant
```

Dashboard: http://localhost:6333/dashboard

## Environment Variables

See `.env.example` for all configuration options. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `OLLAMA_BASE_URL` | Ollama API URL | `http://localhost:11434` |
| `PRIMARY_MODEL` | Main reasoning model | `phi3:mini` |
| `DEFAULT_MAX_ITERATIONS` | Default iteration limit | `100` |
| `DEFAULT_USE_PERSISTENT_LEARNING` | Default retrieval setting | `false` |
| `EMBEDDING_MODEL` | Sentence transformer model | `all-MiniLM-L6-v2` |

## Creating a Task

1. Open the Dashboard
2. Enter a task description (can be anything - optimization, research, code, puzzle, etc.)
3. Configure:
   - **Max Iterations**: How many iterations to run (10 - 5000)
   - **Snapshot Interval**: How often to save snapshots (e.g., every 50 iterations)
   - **Synthesis Interval**: How often to synthesize learnings (e.g., every 100)
   - **Persistent Learning Retrieval**: ON/OFF (see below)
4. Click Start

## Understanding Memory Retrieval

The toggle "Use Persistent Learnings" controls ONLY retrieval:

| Setting | Retrieval | Learning | Storage |
|---------|-----------|----------|---------|
| **ON** | ✅ Retrieves previous knowledge | ✅ Always records | ✅ Always stores |
| **OFF** | ❌ No retrieval | ✅ Always records | ✅ Always stores |

This means:
- Running 1000 iterations with retrieval OFF still builds the knowledge base
- Switching to ON later gives access to all accumulated knowledge
- You can compare runs with and without retrieval to measure memory effectiveness

## Running 100/1000+ Iterations

The system is designed for long-running experiments:

```
Task → Worker Process → Agent Loop (100-5000 iterations)
   ↓ every iteration: raw learning logged
   ↓ every N iterations: snapshot created
   ↓ every M iterations: synthesis + vector DB update
   ↓ on completion: final synthesis
```

- **Real-time monitoring**: Watch via WebSocket in the Live View
- **Checkpoints**: State saved every 10 iterations for crash recovery
- **Pause/Resume**: Control execution via the UI
- **Snapshots**: Compare agent knowledge at different points

## Viewing Snapshots

Snapshots capture the agent's state at configured intervals:
- Known rules and their confidence levels
- Important discoveries
- Successful and failed strategies
- Remaining unknowns
- Current strategy

Use the Snapshot Comparison tool to see how the agent evolved between iterations.

## Adding Custom Environments

Create a new file in `backend/app/environments/`:

```python
from app.environments.base import Environment, EnvironmentState, ActionResult

class MyEnvironment(Environment):
    name = "my_environment"
    description = "Description of my environment"
    
    async def observe(self) -> EnvironmentState:
        # Return current state
        ...
    
    async def act(self, action: dict) -> ActionResult:
        # Execute action, return result
        ...
    
    async def reset(self) -> EnvironmentState:
        # Reset to initial state
        ...
    
    async def is_finished(self) -> bool:
        # Check if task is complete
        ...
    
    def get_available_actions(self) -> list[dict]:
        # List available actions
        ...
```

Register it in the environment registry.

## Adding Custom Tools

```python
from app.tools.registry import BaseTool, ToolResult, PermissionLevel, SafetyLevel

class MyTool(BaseTool):
    name = "my_tool"
    description = "What my tool does"
    safety_level = SafetyLevel.MEDIUM
    permission_level = PermissionLevel.LIMITED
    
    async def execute(self, parameters: dict) -> ToolResult:
        # Execute tool logic
        ...
```

## Adding Models

Add any model supported by Ollama:

```bash
ollama pull <model-name>
```

Then select it in Settings or when creating a task.

## API Documentation

Interactive API docs available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/register | Create account |
| POST | /api/auth/login | Get JWT token |
| POST | /api/tasks | Create task |
| POST | /api/tasks/{id}/start | Start execution |
| POST | /api/tasks/{id}/pause | Pause execution |
| GET | /api/tasks/{id}/iterations | List iterations |
| GET | /api/tasks/{id}/learnings | Get learnings |
| GET | /api/tasks/{id}/rules | Get discovered rules |
| GET | /api/tasks/{id}/snapshots | List snapshots |
| POST | /api/memory/search | Semantic memory search |
| WS | /ws/tasks/{id} | Real-time updates |

## Testing

```bash
cd backend
pip install pytest pytest-asyncio
pytest tests/ -v
```

The test suite verifies 8 critical invariants:
1. Retrieval OFF → no vector queries
2. Retrieval OFF → raw learning still written
3. Retrieval OFF → synthesis still inserts to Qdrant
4. Retrieval ON → relevant memories retrieved
5. 1000 iterations → learning persisted throughout
6. Crash/restart → resume from checkpoint
7. Contradiction → not silently merged
8. Duplicate → deduplicated

## Troubleshooting

### Ollama connection refused
```bash
# Check Ollama is running
ollama list
# Start Ollama service
ollama serve
```

### PostgreSQL connection error
```bash
# Check PostgreSQL is running
docker-compose ps postgres
# Check logs
docker-compose logs postgres
```

### Qdrant not responding
```bash
# Check Qdrant health
curl http://localhost:6333/healthz
# Restart Qdrant
docker-compose restart qdrant
```

### Worker not processing tasks
```bash
# Check worker logs
docker-compose logs worker
# Restart worker
docker-compose restart worker
```

### Out of memory with large models
Use a smaller model:
```bash
ollama pull phi3:mini  # ~2GB
```
Or adjust `PRIMARY_MODEL` in `.env`.

## Deploy on Render

The repo ships a `render.yaml` Blueprint that provisions three resources:
`ala-postgres` (database), `ala-backend` (Docker web service) and
`ala-frontend` (static site).

### 1. Create a Qdrant Cloud cluster (required)

Render does not host Qdrant. Create a free cluster at
[cloud.qdrant.io](https://cloud.qdrant.io), then copy its **Cluster URL** and
**API key** — you will paste them in step 3.

### 2. Apply the Blueprint

1. Push this repo to GitHub (already done if you cloned it from there).
2. In the [Render Dashboard](https://dashboard.render.com) choose **New +** →
   **Blueprint**, select this repository, and click **Apply**.
3. Render prompts for the variables marked `sync: false`:
   - `GROQ_API_KEY` — your Groq API key (or set a different provider below)
   - `QDRANT_URL` — your Qdrant Cloud cluster URL
   - `QDRANT_API_KEY` — your Qdrant Cloud API key

Wait for both services to deploy (the backend image installs PyTorch and
pre-downloads the embedding model, so the first build takes several minutes).

### 3. Open the app

- Frontend: `https://ala-frontend.onrender.com`
- API docs: `https://ala-backend.onrender.com/docs`
- Health: `https://ala-backend.onrender.com/api/health`

Register an account and create a task. The frontend receives the backend URL at
build time via `VITE_API_BASE_URL`; locally the Vite dev proxy is used instead.

### Render notes and limits

- **Backend plan:** the blueprint uses `1c-2g` (1 CPU / 2 GB). The free `512 MB`
  plan is not enough for PyTorch + sentence-transformers and will run out of memory.
- **Free Postgres** instances expire after 90 days unless upgraded.
- **Free web services spin down** after idle time, which kills any in-process
  agent run; paid instances stay up. Keep a single instance — the job manager
  runs tasks in-process unless you configure `REDIS_URL`.
- **Ephemeral disk:** `backend/storage` (raw learning logs, snapshots) resets on
  each deploy. Durable state lives in Postgres and Qdrant.
- **Real-time updates:** the WebSocket connects directly to the backend host, so
  the frontend does not need a proxy.
- Prefer another LLM provider? Set `LLM_PROVIDER` (`ollama` | `openai` |
  `gemini` | `openrouter`) and the matching key in the backend service's
  environment, then update the model variables.

## License

MIT
