# Wizard v2 — Noob-Friendly Cross-Platform Setup

**Date:** 2026-03-26
**Status:** Draft
**Scope:** Rewrite wizard as step-based package with navigation, auto-detect, checkpoint/restart, cross-platform service setup, proactive bugfix

---

## Goals

1. Anyone can `git clone` and run the wizard without prior knowledge
2. Works on Linux, macOS, and Windows
3. Back navigation (`b`) on every step + final summary with step redo
4. Auto-detect LLM backends (LM Studio, Ollama, llama.cpp) and embedding models
5. Docker install guidance with checkpoint/restart so progress is preserved
6. Auto-setup proxy as system service (survives terminal close + reboots)
7. English UI, i18n-ready (strings separated)
8. Fix proactive module crash from missing config keys

---

## Architecture

### File Structure

```
python/
  wizard.py              → DELETED (replaced by package)
  wizard/
    __init__.py          → run_wizard(), should_run_wizard() — public API
    engine.py            → WizardEngine: step navigation, checkpoint, state, "b" for back
    state.py             → WizardState dataclass + checkpoint save/load
    steps/
      __init__.py
      identity.py        → Step 0: agent name, user name
      backend.py         → Step 1: detect backends, select LLM model
      embedding.py       → Step 2: auto-detect/download embedding models
      docker.py          → Step 3: detect Docker, install instructions, restart
      database.py        → Step 4: Docker Compose PG or external PG
      memory_import.py   → Step 5: scan + import memories from other AI agents
      summary.py         → Step 6: final summary, redo any step, confirm
    strings.py           → all user-facing strings (i18n-ready)
    platform.py          → OS detection, Docker install instructions per platform
    backend_detect.py    → async scan for LM Studio/Ollama/llama.cpp
```

### WizardEngine

Central controller that manages step flow:

```python
class WizardEngine:
    def __init__(self, steps: list[BaseStep], config_path: str)
    def run(self) -> dict  # returns final config

class StepResult(Enum):
    NEXT = "next"
    BACK = "back"
    RESTART = "restart"  # exit wizard, preserve checkpoint

class BaseStep:
    title: str
    number: int
    def run(self, state: WizardState) -> StepResult
```

**Navigation rules:**
- User types `b` at any prompt → engine calls previous step
- Previous values are preserved as defaults when going back
- Step 0 ignores `b` (nothing before it)
- Rich progress bar: `[■■■□□□□] Step 3/7: Docker Setup`

### Checkpoint

File: `.wizard_checkpoint.yaml` in config directory.

- Saved after each completed step (contains step number + full state)
- On wizard start: if checkpoint exists → "Continue from step N? [y/n]"
- Deleted after successful wizard completion
- Primary use case: Docker install → restart → continue from Docker step

---

## Step Details

### Step 0: Identity

- Ask agent name (default: "Lyume")
- Ask user name (default: "User")
- Write `IDENTITY.md` and `USER.md`

### Step 1: Backend (LLM)

1. Async scan known ports (timeout 2s each):
   - LM Studio: `http://127.0.0.1:1234/v1/models`
   - Ollama: `http://127.0.0.1:11434/v1/models`
   - llama.cpp: `http://127.0.0.1:8080/v1/models`
2. If found 1+ backends → show list, user selects
3. If none found → manual URL input
4. Fetch model list from selected backend → user picks LLM model
5. If no models loaded → suggest download:
   - Ollama: `ollama pull <model>`
   - LM Studio / llama.cpp: show instructions
6. API key asked only if backend returns 401

### Step 2: Embedding

1. Fetch `/v1/models` from selected backend
2. Filter by known embedding patterns: `embed`, `nomic`, `bge`, `e5`, `gte`, `minilm`
3. If embedding models found → user selects
4. If no embedding models:
   ```
   ! No embedding models found.
   Recommended: nomic-embed-text-v1.5

   [1] Download now (Ollama: ollama pull nomic-embed-text)
   [2] Download now (LM Studio: instructions)
   [3] Use different URL for embeddings
   [4] Use local GGUF file
   ```
5. Validate with test embed("test") call
6. Auto-detect dimensions from test result (`len(embedding)`)

### Step 3: Docker

1. Check `docker --version` + `docker info`
2. **Docker running:** → proceed
3. **Docker installed, daemon stopped:**
   ```
   ! Docker installed but not running.
   Start with: sudo systemctl start docker

   [r] Retry
   [s] Skip — use external PostgreSQL
   ```
4. **Docker not installed:**
   ```
   ! Docker is not installed.

   Docker runs the PostgreSQL database for memory storage.
   Installation takes ~2 minutes.

   <platform-specific instructions from platform.py>

   [r] Restart wizard (progress saved — you'll continue from here)
   [s] Skip — use external PostgreSQL
   ```
   - `r` saves checkpoint at Step 3, exits wizard
   - Next launch resumes from Step 3

### Step 4: Database

1. If Docker available:
   ```
   [1] Docker PostgreSQL (recommended — zero config)
   [2] External PostgreSQL
   ```
2. Docker: run `docker compose up -d db`, wait for healthcheck
3. External: ask host/port/user/password, test connection

### Step 5: Memory Import

Unchanged from current logic:
- Auto-scan known paths (Claude Code, Cursor, Windsurf, Cline, Copilot, Codex, Gemini, Aider)
- Manual path entry
- Skip

### Step 6: Summary

```
╭─ Setup Complete ─────────────────────────────────╮
│  Agent:     Lyume                                 │
│  User:      Tarik                                 │
│  Backend:   LM Studio (127.0.0.1:1234)           │
│  LLM:       qwen3.5-35b-a3b                      │
│  Embedding: nomic-embed-text-v1.5 (768d)         │
│  Database:  Docker PostgreSQL (ai_memory_lyume)   │
│  Import:    2 sources queued                      │
╰──────────────────────────────────────────────────╯

[c] Confirm and start proxy
[1-5] Redo step (e.g. "2" to change embedding)
```

---

## Proxy Service Auto-Setup

After user confirms in summary, wizard:

1. Writes `config.yaml`
2. Sets up auto-start service:

| Platform | Method | Enable | Status |
|----------|--------|--------|--------|
| Linux | systemd user service | `systemctl --user enable --now lyume-proxy` | `systemctl --user status lyume-proxy` |
| macOS | launchd plist | `launchctl load ~/Library/LaunchAgents/com.lyume.proxy.plist` | `launchctl list | grep lyume` |
| Windows | Scheduled Task at logon | `schtasks /create /tn "LyumeProxy" /tr "..." /sc onlogon` | `schtasks /query /tn "LyumeProxy"` |

3. Shows:
   ```
   ✓ Lyume proxy is running on http://127.0.0.1:1235
   ✓ Auto-start enabled — proxy will survive terminal close and reboots

   To check status: <platform-specific command>
   To view logs:    <platform-specific command>
   ```

---

## Platform Detection (platform.py)

Detects OS and provides:
- Docker install instructions (pacman/apt/dnf/brew/winget/chocolatey)
- Docker install URL
- Service setup commands (systemd/launchd/schtasks)
- Python/venv paths

Supported:
- **Linux:** Arch, Ubuntu/Debian, Fedora/RHEL
- **macOS:** Homebrew-based
- **Windows:** winget or manual download

---

## Backend Detection (backend_detect.py)

Async scan of known LLM backend ports:

```python
async def scan_backends(timeout: float = 2.0) -> list[BackendInfo]:
    """Scan known ports for running LLM backends.
    Returns list of BackendInfo(name, url, models)."""
```

Known backends:
- LM Studio: port 1234
- Ollama: port 11434
- llama.cpp: port 8080

All use OpenAI-compatible `/v1/models` endpoint.

---

## Strings (strings.py) — i18n Ready

All user-facing text in one module as constants:

```python
WELCOME_TITLE = "Lyume Memory Proxy — First Run Setup"
STEP_IDENTITY = "Agent Identity"
STEP_BACKEND = "LLM Backend"
# ...
```

Future i18n: replace with `gettext` or dict-based lookup keyed by locale.

---

## Bugfix: Proactive Config Defaults

**Problem:** `memory_proxy.py:56-57` reads `cfg.memory.proactive_high_similarity` and `cfg.memory.proactive_dormant_days` which don't exist in config.yaml. `_Section.__getattr__` returns empty `_Section({})`, which crashes on comparison with int.

**Fix (two parts):**

1. `generate_config()` adds defaults to `memory` section:
   ```yaml
   memory:
     proactive_high_similarity: 0.85
     proactive_dormant_days: 30
   ```

2. `memory_proxy.py` uses safe getattr:
   ```python
   PROACTIVE_HIGH_SIM = getattr(cfg.memory, "proactive_high_similarity", 0.85)
   PROACTIVE_DORMANT_DAYS = getattr(cfg.memory, "proactive_dormant_days", 30)
   ```

---

## Out of Scope

- Full i18n implementation (only string separation)
- Cloud deployment
- GUI/web-based wizard
- Automatic LLM model recommendations (just list what's available)
