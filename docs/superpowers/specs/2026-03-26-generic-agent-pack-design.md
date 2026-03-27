# Phase 2: Generic Agent Pack — Design Spec

**Date:** 2026-03-26
**Status:** Approved
**Scope:** Model-agnostic proxy, TUI wizard, memory import

---

## 1. Goals

- One-click first start for any new user
- Support any OpenAI-compatible LLM backend (Ollama, LM Studio, llama.cpp, vLLM, LocalAI)
- Import memory from existing AI agents (Claude Code, Cursor, Windsurf, Cline, Copilot, Codex, Gemini, Aider)
- Keep existing functionality intact (markers, ELO, hybrid search, consolidation, sessions)

## 2. Architecture: Config-Driven with Auto-Detection

Single `config.yaml` as source of truth. TUI wizard fills it on first run. Proxy reads config and connects accordingly.

### 2.1 New Config Structure

```yaml
first_run: true  # wizard sets to false after setup

llm:
  url: "http://127.0.0.1:11434/v1"   # any OpenAI-compatible endpoint
  api_key: ""                          # optional
  model: ""                            # auto-detected or user-selected
  request_timeout: 300

embedding:
  provider: "http"                     # "http" or "local" (llama-cpp fallback)
  url: "http://127.0.0.1:11434/v1"    # same or different server
  model: "nomic-embed-text"
  dimensions: 768
  # local fallback (when provider: "local"):
  # model_path: "/path/to/model.gguf"
  # n_ctx: 512

database:
  provider: "docker"                   # "docker" or "external"
  host: "127.0.0.1"
  port: 5432
  user: "postgres"
  password: "lyume"
  name: "ai_memory_lyume"             # derived from agent name: ai_memory_{name}

server:
  host: "127.0.0.1"
  port: 1235

memory:
  search_limit: 3
  similarity_threshold: 0.3
  dedup_similarity: 0.9
  hybrid_search: true
  hybrid_rrf_k: 60

lessons:
  search_limit: 3
  similarity_threshold: 0.70
  elo_start: 50
  elo_implicit_delta: 5
  elo_explicit_delta: 10
  elo_floor: 20
  elo_deactivate_days: 30

consolidation:
  enabled: true
  schedule: "03:00"
  semantic_threshold: 0.85
  lesson_threshold: 0.85
  cooldown_days: 180
  stale_days: 365
```

**Backward compatibility:** If config contains old `lm_studio:` section, `config.py` auto-migrates it to `llm:` on load.

### 2.2 LLMClient (`python/llm_client.py`)

Single class for all LLM requests. Replaces scattered httpx calls.

```python
class LLMClient:
    def __init__(self, url: str, api_key: str = "", model: str = "")
    async def complete(self, messages, model=None, max_tokens=4096, temperature=0.7, stream=False) -> str
    async def complete_stream(self, messages, model=None, max_tokens=4096, temperature=0.7) -> AsyncIterator
    async def is_available(self) -> bool
    async def list_models(self) -> list[str]
```

Under the hood: httpx to `{url}/v1/chat/completions` — OpenAI-compatible, works with all backends.

Used by: `memory_proxy.py`, `memory_consolidator.py`

### 2.3 EmbeddingClient (`python/embedding_client.py`)

Abstraction with two implementations:

```python
class HTTPEmbeddingClient:
    """Sends request to {url}/v1/embeddings — works with Ollama, LM Studio, etc."""
    def __init__(self, url: str, api_key: str = "", model: str = "nomic-embed-text")
    async def embed(self, text: str) -> list[float]

class LocalEmbeddingClient:
    """llama-cpp-python fallback — loads GGUF model locally on CPU."""
    def __init__(self, model_path: str, n_ctx: int = 512, dimensions: int = 768)
    async def embed(self, text: str) -> list[float]
```

Selection via `config.yaml: embedding.provider` ("http" or "local").

Used by: `memory_manager.py`

### 2.4 Multi-Agent: Separate DB per Agent

Each agent gets its own PostgreSQL database: `ai_memory_{agent_name}` (e.g. `ai_memory_lyume`, `ai_memory_nova`).

**Why separate DBs instead of shared DB with namespace:**
- Zero risk of memory cross-contamination between agents
- Simple backup/restore per agent
- Clean deletion: `DROP DATABASE ai_memory_nova` and it's gone
- No migration needed for existing single-agent setups

**Wizard re-run behavior:**
- If `config.yaml` exists and `first_run: false` → wizard shows choice:
  - **"Reconfigure this agent"** → edit existing config, keep DB
  - **"Create new agent"** → new name, new DB, new config directory
- Recommendation shown to user:

```
We recommend keeping one agent.

One agent = deeper memory, richer context, better understanding of you.
Multiple agents split your history and start from zero each time.

Create a new agent only if you need a completely separate workspace
(e.g. work vs personal, or a fresh start).
```

**Database naming:**
- Agent name normalized to lowercase alphanumeric + underscore
- DB name: `ai_memory_{normalized_name}`
- Config stored per agent: `~/.openclaw/workspace-{name}/config.yaml`

**Future:** Export/import by agent ID (separate feature, not in this phase).

### 2.5 TUI Wizard (`python/wizard.py`)

Runs when `config.yaml` doesn't exist or has `first_run: true`. Built with `textual` library.

**Step 0 — Agent Identity:**
- Ask agent name (default: "Lyume")
- Ask user's name
- Saved to `IDENTITY.md` (agent name) and `USER.md` (user name)
- Proxy uses these for system prompt personalization
- DB name derived from agent name: `ai_memory_{name}`

**Step 1 — LLM Backend:**
- Ask URL (default: `http://127.0.0.1:11434/v1` for Ollama)
- Try connect → `list_models()` → show available models
- User selects model

**Step 2 — Embedding:**
- Try embedding endpoint on same URL
- If available → show embedding models, user selects
- If not → offer: "Install locally (llama-cpp-python + nomic)?" or guide how to set up embedding in Ollama

**Step 3 — Database:**
- "Docker (recommended)" or "Existing PostgreSQL"
- Docker: check docker is installed → `docker compose up -d db` → wait for readiness
- External: ask connection string → test connection
- Run migrations + init.sql

**Step 4 — Memory Import (optional):**
With helper text for newcomers:

```
📂 Memory Import

Many AI agents store memory in text files.
Lyume can import them into its database so it
knows about you and your projects right away.

Known formats:

  Claude Code    →  ~/.claude/projects/*/memory/
                    (MEMORY.md + topic files)
  Cursor         →  .cursor/rules/*.mdc
                    (or legacy .cursorrules)
  Windsurf       →  .windsurfrules.md
  Cline          →  .clinerules/memory/
  GitHub Copilot →  .github/copilot-instructions.md
  OpenAI Codex   →  AGENTS.md or ~/.codex/skills/
  Gemini CLI     →  GEMINI.md
  Aider          →  CONVENTIONS.md
                    (via .aider.conf.yml → read:)
  Other          →  any folder with .md files

[Auto-scan]  [Enter path]  [Skip]
```

**Auto-scan** checks known paths on user's system, shows what was found.
**Enter path** — manual input.

**Step 5 — Done:**
- Save `config.yaml` with `first_run: false`
- Start proxy

### 2.6 Memory Import Pipeline (`python/memory_import.py`)

1. **Scan** — find `.md` / `.mdc` files in given folder
2. **Parse** — split each file into logical blocks (by `##` headers or `---` separators)
3. **Classify** — each block through intent classifier → determine type: fact, lesson, preference
4. **Embed** — generate embedding for each block
5. **Dedup** — check if similar already exists in DB (cosine similarity > 0.9 = skip)
6. **Save** — store in `memories_semantic` or `lessons`

Progress display:
```
Found 12 files, 47 memory blocks
[████████████░░░░░░░░] 28/47  Imported: 24  Duplicates: 4
```

Import only reads files — never modifies or deletes the source.

### 2.7 Database Init (`python/migrations/init.sql`)

Runs once on first connection if tables don't exist.

Creates:
- `memories_semantic` table (id, content, embedding vector(768), emotional_context, source, created_at, updated_at, last_recalled_at, recall_count, merged_into, search_vector)
- `lessons` table (id, trigger, content, embedding vector(768), elo_rating, last_elo_change, elo_floor_since, is_active, created_at, updated_at, last_recalled_at, recall_count, search_vector)
- pgvector extension
- GIN indexes for tsvector
- IVFFlat indexes for vector search
- Update triggers for search_vector

Logic in `memory_manager.connect()`:
1. Check if tables exist
2. If not → execute `init.sql`
3. Then run incremental migrations as before

## 3. Changes to Existing Files

| File | Change |
|------|--------|
| `config.yaml` | `lm_studio:` → `llm:`, add `embedding.provider`, `database.provider`, `first_run` |
| `config.py` | Parse new config structure, backward compat for old `lm_studio:` |
| `memory_proxy.py` | Replace ~5 httpx calls with `LLMClient.complete()` / `.complete_stream()` |
| `memory_manager.py` | Replace `get_embed_model()` singleton with `EmbeddingClient.embed()`, add init.sql logic |
| `memory_consolidator.py` | Replace ~2 httpx calls with `LLMClient.complete()` |
| `docker-compose.yml` | Remove hardcoded embedding model path, make proxy ENV generic |
| `pyproject.toml` | `llama-cpp-python` becomes optional: `[project.optional-dependencies] local-embedding` |

## 4. New Files

| File | Purpose |
|------|---------|
| `python/llm_client.py` | Generic LLM client (OpenAI-compatible) |
| `python/embedding_client.py` | HTTP + local embedding abstraction |
| `python/wizard.py` | TUI first-run wizard (textual) |
| `python/memory_import.py` | Import pipeline for .md/.mdc files |
| `python/migrations/init.sql` | Database schema creation |

## 5. What Does NOT Change

- Marker system (>>SAVE, >>RECALL, >>FORGET, >>LESSON, >>USEFUL, >>USELESS, >>RATE_LESSON)
- ELO rating system
- Hybrid search (Vector + BM25 + RRF)
- Memory consolidation (3 passes)
- Session tracker
- Intent classifier
- Think stripping
- SOUL.md, IDENTITY.md, USER.md, AGENTS.md
- All existing tests (87/87)

## 6. Dependencies

**Required:**
- `uv` (package manager, already used)
- `textual` (TUI, already in deps)
- `httpx` (HTTP client, already in deps)

**Optional:**
- `llama-cpp-python` (local embedding fallback)
- Docker (for PostgreSQL container)

## 7. Success Criteria

- [ ] New user can run `uv run python wizard.py` and have working proxy in < 5 minutes
- [ ] Works with Ollama, LM Studio, and llama.cpp server without code changes
- [ ] Memory import from Claude Code `~/.claude/projects/*/memory/` works correctly
- [ ] Existing Lyume setup continues working after config migration
- [ ] All 87 existing tests still pass
- [ ] New tests for LLMClient, EmbeddingClient, wizard, import pipeline
