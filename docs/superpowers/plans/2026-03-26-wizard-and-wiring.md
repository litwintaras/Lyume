# Wizard, Proxy Wiring, Integration Tests, README — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 2 remaining tasks: TUI wizard (rich-based CLI), wire wizard into proxy startup, integration tests, README update.

**Architecture:** `wizard.py` uses `rich.prompt` / `rich.console` for interactive CLI setup. It validates LLM/embedding connectivity via existing `LLMClient` and `HTTPEmbeddingClient`, generates `config.yaml`, writes `IDENTITY.md` / `USER.md`, optionally runs memory import. Proxy lifespan checks `first_run` flag and launches wizard before connecting to DB.

**Tech Stack:** Python 3.12, rich (console/prompt), yaml, httpx, asyncio, pytest

**Working directory:** `/home/tarik/.openclaw/workspace-lyume`

**Existing files you need to know:**
- `python/config.py` — loads `config.yaml`, `_migrate_config()`, `_env_override()`, exports `cfg` singleton
- `python/config.yaml` — current config (already in new `llm:` format, `first_run: false`)
- `python/llm_client.py` — `LLMClient(url, api_key, model, timeout)` with `.complete()`, `.is_available()`, `.list_models()`
- `python/embedding_client.py` — `HTTPEmbeddingClient(url, api_key, model)` with `.embed()`, `create_embedding_client()` factory
- `python/memory_import.py` — `scan_markdown_files(dir)`, `parse_blocks(content)`, `ImportPipeline(mm, embed_client)`
- `python/memory_proxy.py` — FastAPI app, `lifespan()` at line 191, `_llm_client` init at line 31
- `README.md` — current readme, references old `lm_studio:` config section

---

## Task 1: Wizard — Core Functions (generate_config, detect_known_memory_paths)

**Files:**
- Create: `python/wizard.py`
- Create: `python/tests/test_wizard.py`

- [ ] **Step 1: Write tests for pure functions**

```python
# python/tests/test_wizard.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


def test_generate_config_all_fields():
    """generate_config() produces dict with all required sections."""
    from wizard import generate_config

    config = generate_config(
        agent_name="TestBot",
        user_name="Taras",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
        llm_api_key="",
        embed_provider="http",
        embed_url="http://localhost:11434/v1",
        embed_model="nomic-embed-text",
        db_provider="docker",
        db_host="127.0.0.1",
        db_port=5432,
        db_user="postgres",
        db_password="lyume",
        db_name="ai_memory_testbot",
    )
    assert config["first_run"] is False
    assert config["llm"]["url"] == "http://localhost:11434/v1"
    assert config["llm"]["model"] == "llama3"
    assert config["llm"]["api_key"] == ""
    assert config["embedding"]["provider"] == "http"
    assert config["embedding"]["url"] == "http://localhost:11434/v1"
    assert config["embedding"]["model"] == "nomic-embed-text"
    assert config["database"]["provider"] == "docker"
    assert config["database"]["host"] == "127.0.0.1"
    assert config["database"]["port"] == 5432
    assert config["database"]["name"] == "ai_memory_testbot"
    assert config["_agent_name"] == "TestBot"
    assert config["_user_name"] == "Taras"


def test_generate_config_defaults():
    """generate_config() fills defaults for optional params."""
    from wizard import generate_config

    config = generate_config(
        agent_name="Lyume",
        user_name="User",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    assert config["embedding"]["provider"] == "http"
    assert config["database"]["provider"] == "docker"
    assert config["database"]["password"] == "lyume"
    assert config["memory"]["search_limit"] == 3
    assert config["lessons"]["elo_start"] == 50
    assert config["consolidation"]["enabled"] is True


def test_generate_config_local_embedding():
    """generate_config() with local embedding sets model_path."""
    from wizard import generate_config

    config = generate_config(
        agent_name="Lyume",
        user_name="User",
        llm_url="http://localhost:1234",
        llm_model="qwen",
        embed_provider="local",
        embed_model_path="/path/to/model.gguf",
    )
    assert config["embedding"]["provider"] == "local"
    assert config["embedding"]["model_path"] == "/path/to/model.gguf"


def test_detect_known_memory_paths_finds_claude():
    """detect_known_memory_paths() finds Claude Code memory directories."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        claude_dir = Path(d) / ".claude" / "projects" / "myproject" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "MEMORY.md").write_text("# Memory\n- test")

        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert len(paths) >= 1
            assert any("claude" in str(p).lower() for p in paths)


def test_detect_known_memory_paths_empty():
    """detect_known_memory_paths() returns empty list when nothing found."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert paths == []


def test_detect_known_memory_paths_finds_cursor():
    """detect_known_memory_paths() finds Cursor rules."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        cursor_dir = Path(d) / ".cursor" / "rules"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "memory.mdc").write_text("rule: test")

        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert any("cursor" in str(p).lower() for p in paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wizard'`

- [ ] **Step 3: Write wizard.py — pure functions**

```python
# python/wizard.py
"""CLI Wizard — first-run setup for Lyume Memory Proxy."""

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress

console = Console()

KNOWN_MEMORY_PATHS = [
    ("Claude Code", ".claude/projects/*/memory/"),
    ("Cursor", ".cursor/rules/"),
    ("Cursor (legacy)", ".cursorrules"),
    ("Windsurf", ".windsurfrules.md"),
    ("Cline", ".clinerules/memory/"),
    ("GitHub Copilot", ".github/copilot-instructions.md"),
    ("OpenAI Codex", "AGENTS.md"),
    ("Gemini CLI", "GEMINI.md"),
    ("Aider", "CONVENTIONS.md"),
]


def detect_known_memory_paths() -> list[dict]:
    """Scan home directory for known AI agent memory locations.

    Returns list of dicts: {"name": "Claude Code", "path": Path(...)}
    """
    home = Path.home()
    found = []
    for name, pattern in KNOWN_MEMORY_PATHS:
        matches = list(home.glob(pattern))
        for m in matches:
            if m.is_dir():
                # Check directory has at least one .md/.mdc file
                has_files = any(m.glob("*.md")) or any(m.glob("*.mdc"))
                if has_files:
                    found.append({"name": name, "path": m})
            elif m.is_file() and m.stat().st_size > 0:
                found.append({"name": name, "path": m.parent})
    return found


def generate_config(
    agent_name: str,
    user_name: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str = "",
    embed_provider: str = "http",
    embed_url: str = "",
    embed_model: str = "nomic-embed-text",
    embed_model_path: str = "",
    db_provider: str = "docker",
    db_host: str = "127.0.0.1",
    db_port: int = 5432,
    db_user: str = "postgres",
    db_password: str = "lyume",
    db_name: str = "",
) -> dict:
    """Generate a complete config.yaml dict from wizard inputs."""
    # Normalize agent name for DB
    normalized = re.sub(r"[^a-z0-9_]", "_", agent_name.lower()).strip("_")
    if not db_name:
        db_name = f"ai_memory_{normalized}"

    config = {
        "first_run": False,
        "_agent_name": agent_name,
        "_user_name": user_name,
        "server": {
            "host": "127.0.0.1",
            "port": 1235,
            "log_level": "info",
        },
        "llm": {
            "url": llm_url,
            "api_key": llm_api_key,
            "model": llm_model,
            "request_timeout": 300,
            "reflection_timeout": 120,
            "reflection_max_messages": 30,
        },
        "database": {
            "provider": db_provider,
            "host": db_host,
            "port": db_port,
            "user": db_user,
            "password": db_password,
            "name": db_name,
            "pool_min": 1,
            "pool_max": 5,
        },
        "embedding": {},
        "memory": {
            "search_limit": 3,
            "similarity_threshold": 0.3,
            "dedup_similarity": 0.9,
            "save_max_chars": 300,
            "dedup_ttl": 5,
            "hybrid_search": True,
            "hybrid_rrf_k": 60,
            "hybrid_bm25_limit": 10,
        },
        "lessons": {
            "search_limit": 3,
            "similarity_threshold": 0.70,
            "elo_start": 50,
            "elo_implicit_delta": 5,
            "elo_explicit_delta": 10,
            "elo_floor": 20,
            "elo_deactivate_days": 30,
        },
        "features": {
            "strip_think_tags": True,
            "marker_fallback": True,
            "session_summary": True,
            "summary_interval": 20,
            "session_timeout": 1800,
        },
        "consolidation": {
            "enabled": True,
            "schedule": "03:00",
            "semantic_threshold": 0.85,
            "lesson_threshold": 0.85,
            "cooldown_days": 180,
            "stale_days": 365,
        },
    }

    # Embedding section depends on provider
    if embed_provider == "local":
        config["embedding"] = {
            "provider": "local",
            "model_path": embed_model_path,
            "n_ctx": 512,
            "n_gpu_layers": 0,
            "dimensions": 768,
        }
    else:
        config["embedding"] = {
            "provider": "http",
            "url": embed_url or llm_url,
            "model": embed_model,
            "dimensions": 768,
        }

    return config
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/wizard.py python/tests/test_wizard.py
git commit -m "feat: add wizard core — generate_config() + detect_known_memory_paths()"
```

---

## Task 2: Wizard — Interactive CLI (run_wizard)

**Files:**
- Modify: `python/wizard.py`
- Modify: `python/tests/test_wizard.py`

- [ ] **Step 1: Write test for save_config and save_identity**

```python
# Append to python/tests/test_wizard.py

import yaml


def test_save_config(tmp_path):
    """save_config() writes valid YAML without internal keys."""
    from wizard import generate_config, save_config

    config = generate_config(
        agent_name="Luna",
        user_name="Alex",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    config_path = tmp_path / "config.yaml"
    save_config(config, str(config_path))

    loaded = yaml.safe_load(config_path.read_text())
    assert loaded["llm"]["model"] == "llama3"
    assert loaded["first_run"] is False
    # Internal keys stripped
    assert "_agent_name" not in loaded
    assert "_user_name" not in loaded


def test_save_identity(tmp_path):
    """save_identity() writes IDENTITY.md and USER.md."""
    from wizard import save_identity

    save_identity("Luna", "Alex", str(tmp_path))

    identity = (tmp_path / "IDENTITY.md").read_text()
    assert "Luna" in identity

    user = (tmp_path / "USER.md").read_text()
    assert "Alex" in user
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py::test_save_config python/tests/test_wizard.py::test_save_identity -v`
Expected: FAIL with `ImportError: cannot import name 'save_config'`

- [ ] **Step 3: Add save_config, save_identity, run_wizard to wizard.py**

Append to `python/wizard.py`:

```python
def save_config(config: dict, path: str) -> None:
    """Write config dict to YAML file, stripping internal keys."""
    clean = {k: v for k, v in config.items() if not k.startswith("_")}
    Path(path).write_text(yaml.dump(clean, default_flow_style=False, sort_keys=False))


def save_identity(agent_name: str, user_name: str, directory: str) -> None:
    """Write IDENTITY.md and USER.md files."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / "IDENTITY.md").write_text(f"Name: {agent_name}\nRole: Memory companion\n")
    (d / "USER.md").write_text(f"{user_name}\n")


def _normalize_name(name: str) -> str:
    """Normalize agent name to lowercase alphanumeric + underscore."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")


def run_wizard(config_path: str) -> dict:
    """Interactive CLI wizard for first-run setup. Returns generated config."""
    from llm_client import LLMClient
    from embedding_client import HTTPEmbeddingClient

    config_dir = str(Path(config_path).parent)

    console.print(Panel(
        "[bold cyan]Lyume Memory Proxy — First Run Setup[/bold cyan]\n\n"
        "This wizard will configure your LLM backend, embedding,\n"
        "database, and optionally import memories from other AI agents.",
        title="Welcome",
        border_style="cyan",
    ))

    # Step 0: Agent Identity
    console.print("\n[bold]Step 0: Agent Identity[/bold]")
    agent_name = Prompt.ask("Agent name", default="Lyume")
    user_name = Prompt.ask("Your name", default="User")
    save_identity(agent_name, user_name, config_dir)
    console.print(f"  [green]✓[/green] Identity saved: {agent_name} / {user_name}")

    # Step 1: LLM Backend
    console.print("\n[bold]Step 1: LLM Backend[/bold]")
    llm_url = Prompt.ask(
        "LLM API URL (OpenAI-compatible)",
        default="http://127.0.0.1:11434/v1",
    )
    llm_api_key = Prompt.ask("API key (leave empty if none)", default="")

    # Try to connect and list models
    llm_model = ""
    client = LLMClient(url=llm_url, api_key=llm_api_key)
    try:
        available = asyncio.run(client.is_available())
        if available:
            models = asyncio.run(client.list_models())
            if models:
                console.print(f"  [green]✓[/green] Connected! Found {len(models)} model(s):")
                for i, m in enumerate(models[:20], 1):
                    console.print(f"    {i}. {m}")
                choice = Prompt.ask(
                    "Select model number or type name",
                    default="1",
                )
                if choice.isdigit() and 1 <= int(choice) <= len(models):
                    llm_model = models[int(choice) - 1]
                else:
                    llm_model = choice
            else:
                console.print("  [yellow]![/yellow] Connected but no models found.")
                llm_model = Prompt.ask("Model name")
        else:
            console.print(f"  [yellow]![/yellow] Cannot connect to {llm_url}")
            llm_model = Prompt.ask("Model name (will be used when server is available)")
    except Exception as e:
        console.print(f"  [yellow]![/yellow] Connection error: {e}")
        llm_model = Prompt.ask("Model name (will be used when server is available)")
    console.print(f"  [green]✓[/green] LLM: {llm_url} / {llm_model}")

    # Step 2: Embedding
    console.print("\n[bold]Step 2: Embedding[/bold]")
    embed_provider = "http"
    embed_url = ""
    embed_model = "nomic-embed-text"
    embed_model_path = ""

    try:
        # Try embedding on same URL
        test_embed = HTTPEmbeddingClient(url=llm_url, api_key=llm_api_key, model="nomic-embed-text")
        test_result = asyncio.run(test_embed.embed("test"))
        if test_result and len(test_result) > 0:
            embed_url = llm_url
            console.print(f"  [green]✓[/green] Embedding available on {llm_url}")
            embed_model = Prompt.ask("Embedding model", default="nomic-embed-text")
        else:
            raise ValueError("empty embedding")
    except Exception:
        console.print(f"  [yellow]![/yellow] No embedding endpoint found on {llm_url}")
        embed_choice = Prompt.ask(
            "Use [1] different HTTP endpoint or [2] local llama-cpp?",
            choices=["1", "2"],
            default="1",
        )
        if embed_choice == "1":
            embed_url = Prompt.ask("Embedding API URL")
            embed_model = Prompt.ask("Embedding model", default="nomic-embed-text")
        else:
            embed_provider = "local"
            embed_model_path = Prompt.ask("Path to GGUF embedding model")
    console.print(f"  [green]✓[/green] Embedding: {embed_provider}")

    # Step 3: Database
    console.print("\n[bold]Step 3: Database[/bold]")
    db_choice = Prompt.ask(
        "Use [1] Docker PostgreSQL (recommended) or [2] existing PostgreSQL?",
        choices=["1", "2"],
        default="1",
    )
    db_provider = "docker" if db_choice == "1" else "external"
    db_host = "127.0.0.1"
    db_port = 5432
    db_user = "postgres"
    db_password = "lyume"

    if db_choice == "2":
        db_host = Prompt.ask("PostgreSQL host", default="127.0.0.1")
        db_port = int(Prompt.ask("PostgreSQL port", default="5432"))
        db_user = Prompt.ask("PostgreSQL user", default="postgres")
        db_password = Prompt.ask("PostgreSQL password", default="lyume")
    else:
        # Check Docker
        try:
            subprocess.run(["docker", "info"], capture_output=True, check=True)
            console.print("  [green]✓[/green] Docker is available")
        except (subprocess.CalledProcessError, FileNotFoundError):
            console.print("  [red]✗[/red] Docker not found. Install Docker or use existing PostgreSQL.")
            db_provider = "external"
            db_host = Prompt.ask("PostgreSQL host", default="127.0.0.1")
            db_port = int(Prompt.ask("PostgreSQL port", default="5432"))
            db_user = Prompt.ask("PostgreSQL user", default="postgres")
            db_password = Prompt.ask("PostgreSQL password", default="lyume")

    db_name = f"ai_memory_{_normalize_name(agent_name)}"
    console.print(f"  [green]✓[/green] Database: {db_provider} → {db_name}")

    # Step 4: Memory Import
    console.print("\n[bold]Step 4: Memory Import (optional)[/bold]")
    import_paths = []

    console.print(Panel(
        "Many AI agents store memory in text files.\n"
        "Lyume can import them so it knows about you right away.\n\n"
        "Known formats: Claude Code, Cursor, Windsurf, Cline,\n"
        "GitHub Copilot, OpenAI Codex, Gemini CLI, Aider",
        border_style="dim",
    ))

    import_choice = Prompt.ask(
        "[1] Auto-scan  [2] Enter path  [3] Skip",
        choices=["1", "2", "3"],
        default="3",
    )
    if import_choice == "1":
        found = detect_known_memory_paths()
        if found:
            console.print(f"  Found {len(found)} source(s):")
            for i, f in enumerate(found, 1):
                console.print(f"    {i}. {f['name']} → {f['path']}")
            if Confirm.ask("Import all found sources?", default=True):
                import_paths = [str(f["path"]) for f in found]
        else:
            console.print("  No known memory sources found.")
    elif import_choice == "2":
        path = Prompt.ask("Path to directory with .md files")
        if Path(path).is_dir():
            import_paths = [path]
        else:
            console.print(f"  [red]✗[/red] {path} is not a valid directory")

    # Generate and save config
    config = generate_config(
        agent_name=agent_name,
        user_name=user_name,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        embed_provider=embed_provider,
        embed_url=embed_url,
        embed_model=embed_model,
        embed_model_path=embed_model_path,
        db_provider=db_provider,
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
    )
    config["_import_paths"] = import_paths
    save_config(config, config_path)

    console.print(f"\n  [green]✓[/green] Config saved to {config_path}")

    # Step 5: Done
    console.print(Panel(
        f"[bold green]Setup complete![/bold green]\n\n"
        f"Agent: {agent_name}\n"
        f"LLM: {llm_url} / {llm_model}\n"
        f"Embedding: {embed_provider}\n"
        f"Database: {db_name}\n"
        f"Import: {len(import_paths)} source(s) queued"
        + ("\n\nMemory import will run when proxy starts." if import_paths else ""),
        title="Done",
        border_style="green",
    ))

    return config


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "config.yaml")
    run_wizard(config_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/wizard.py python/tests/test_wizard.py
git commit -m "feat: add wizard interactive CLI — LLM, embedding, DB, import steps"
```

---

## Task 3: Wire Wizard into Proxy Startup

**Files:**
- Modify: `python/memory_proxy.py:190-200` (lifespan function)

- [ ] **Step 1: Write test for wizard trigger logic**

```python
# Append to python/tests/test_wizard.py

from unittest.mock import AsyncMock, MagicMock


def test_wizard_triggers_on_first_run():
    """Wizard should be called when first_run is True."""
    from wizard import should_run_wizard

    assert should_run_wizard(config_path="/nonexistent/config.yaml") is True


def test_wizard_skips_when_configured(tmp_path):
    """Wizard should NOT run when config exists and first_run is False."""
    from wizard import should_run_wizard

    config_path = tmp_path / "config.yaml"
    config_path.write_text("first_run: false\nllm:\n  url: http://localhost:1234\n")
    assert should_run_wizard(config_path=str(config_path)) is False


def test_wizard_triggers_when_first_run_true(tmp_path):
    """Wizard should run when config has first_run: true."""
    from wizard import should_run_wizard

    config_path = tmp_path / "config.yaml"
    config_path.write_text("first_run: true\nllm:\n  url: http://localhost:1234\n")
    assert should_run_wizard(config_path=str(config_path)) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py::test_wizard_triggers_on_first_run python/tests/test_wizard.py::test_wizard_skips_when_configured python/tests/test_wizard.py::test_wizard_triggers_when_first_run_true -v`
Expected: FAIL with `ImportError: cannot import name 'should_run_wizard'`

- [ ] **Step 3: Add should_run_wizard() to wizard.py**

Add before `run_wizard()` in `python/wizard.py`:

```python
def should_run_wizard(config_path: str) -> bool:
    """Check if wizard should run: no config file or first_run: true."""
    p = Path(config_path)
    if not p.exists():
        return True
    try:
        data = yaml.safe_load(p.read_text())
        return data.get("first_run", True) is True
    except Exception:
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_wizard.py -v`
Expected: ALL PASS

- [ ] **Step 5: Modify proxy lifespan to check wizard**

In `python/memory_proxy.py`, replace the lifespan function (lines 190-200):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if first run — launch wizard
    config_path = str(Path(__file__).parent / "config.yaml")
    from wizard import should_run_wizard
    if should_run_wizard(config_path):
        from wizard import run_wizard
        run_wizard(config_path)
        # Reload config after wizard
        import importlib
        import config as config_module
        importlib.reload(config_module)
        from config import cfg as new_cfg
        # Update LLM client
        global _llm_client, LM_STUDIO_URL, LM_STUDIO_API_KEY, LM_STUDIO_HEADERS
        _llm_client = LLMClient(
            url=new_cfg.llm.url,
            api_key=getattr(new_cfg.llm, "api_key", ""),
            model=getattr(new_cfg.llm, "model", ""),
            timeout=getattr(new_cfg.llm, "request_timeout", 300),
        )
        LM_STUDIO_URL = new_cfg.llm.url
        LM_STUDIO_API_KEY = getattr(new_cfg.llm, "api_key", "")
        LM_STUDIO_HEADERS = {"Content-Type": "application/json"}
        if LM_STUDIO_API_KEY:
            LM_STUDIO_HEADERS["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"

    await mm.connect()

    # Deferred memory import (from wizard)
    if hasattr(cfg, '_import_paths') and cfg._import_paths:
        from memory_import import ImportPipeline
        from embedding_client import create_embedding_client
        emb_cfg = cfg.embedding
        embed_client = create_embedding_client(
            provider=getattr(emb_cfg, "provider", "http"),
            url=getattr(emb_cfg, "url", ""),
            api_key=getattr(emb_cfg, "api_key", ""),
            model=getattr(emb_cfg, "model", "nomic-embed-text"),
            model_path=getattr(emb_cfg, "model_path", ""),
        )
        pipeline = ImportPipeline(memory_manager=mm, embedding_client=embed_client)
        for path in cfg._import_paths:
            stats = await pipeline.import_directory(path)
            print(f"[import] {path}: {stats['imported']} imported, {stats['duplicate']} duplicates", flush=True)

    _mind_state["session_start"] = datetime.now(timezone.utc).isoformat()
    global session_tracker
    if cfg.features.session_summary:
        session_tracker = SessionTracker(mm, LM_STUDIO_URL, LM_STUDIO_HEADERS)
        print("[session] Session tracker enabled", flush=True)
    print("Memory proxy started — port 1235 → LM Studio 1234", flush=True)
    yield
    await mm.close()
```

Also add this import at the top of `memory_proxy.py` (after line 14):

```python
from pathlib import Path
```

- [ ] **Step 6: Run full test suite**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS (existing 112 + new wizard tests)

- [ ] **Step 7: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/wizard.py python/tests/test_wizard.py python/memory_proxy.py
git commit -m "feat: wire wizard into proxy startup + deferred memory import"
```

---

## Task 4: Integration Tests

**Files:**
- Create: `python/tests/test_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# python/tests/test_integration.py
"""Integration tests — verify Phase 2 components work together."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from llm_client import LLMClient
from embedding_client import HTTPEmbeddingClient, create_embedding_client
from memory_import import scan_markdown_files, parse_blocks, ImportPipeline
from wizard import generate_config, detect_known_memory_paths, save_config
from config import _migrate_config


def test_old_config_migrates_and_clients_init():
    """Old lm_studio config migrates and LLMClient can be created from it."""
    old = {
        "lm_studio": {
            "url": "http://localhost:1234",
            "api_key": "sk-test",
            "model_name": "qwen",
        },
        "embedding": {"model_path": "/fake/model.gguf", "n_ctx": 512, "dimensions": 768},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
    }
    config = _migrate_config(old)

    llm = LLMClient(
        url=config["llm"]["url"],
        api_key=config["llm"]["api_key"],
        model=config["llm"]["model"],
    )
    assert llm.url == "http://localhost:1234"
    assert llm.model == "qwen"
    assert config["embedding"]["provider"] == "local"


def test_wizard_config_creates_valid_clients():
    """Wizard-generated config can create LLMClient and HTTPEmbeddingClient."""
    config = generate_config(
        agent_name="TestBot",
        user_name="Tester",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
        embed_provider="http",
        embed_url="http://localhost:11434/v1",
        embed_model="nomic-embed-text",
        db_provider="docker",
    )

    llm = LLMClient(url=config["llm"]["url"], model=config["llm"]["model"])
    assert llm.model == "llama3"

    embed = HTTPEmbeddingClient(url=config["embedding"]["url"], model=config["embedding"]["model"])
    assert embed.model == "nomic-embed-text"


def test_wizard_config_roundtrip(tmp_path):
    """Config survives generate → save → load cycle."""
    import yaml

    config = generate_config(
        agent_name="RoundTrip",
        user_name="Test",
        llm_url="http://localhost:1234",
        llm_model="model-x",
    )
    config_path = tmp_path / "config.yaml"
    save_config(config, str(config_path))

    loaded = yaml.safe_load(config_path.read_text())
    assert loaded["llm"]["model"] == "model-x"
    assert loaded["database"]["name"] == "ai_memory_roundtrip"
    assert loaded["first_run"] is False
    assert "_agent_name" not in loaded


@pytest.mark.asyncio
async def test_import_pipeline_end_to_end():
    """Full import: scan → parse → embed → dedup → save."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "memory.md").write_text(
            "## Preferences\n\nUser prefers dark theme and vim keybindings.\n\n"
            "## Skills\n\nUser knows Python and TypeScript well."
        )

        files = scan_markdown_files(d)
        assert len(files) == 1

        content = files[0].read_text()
        blocks = parse_blocks(content)
        assert len(blocks) == 2

        mock_mm = AsyncMock()
        mock_mm.search_semantic = AsyncMock(return_value=[])
        mock_mm.save_semantic = AsyncMock()

        mock_embed = AsyncMock()
        mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

        pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)
        stats = await pipeline.import_directory(d)

        assert stats["imported"] == 2
        assert stats["duplicate"] == 0
        assert mock_mm.save_semantic.call_count == 2
```

- [ ] **Step 2: Run integration tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_integration.py -v`
Expected: ALL PASS (4 tests)

- [ ] **Step 3: Run full test suite**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/tests/test_integration.py
git commit -m "test: add integration tests for Phase 2 — config migration, wizard, import"
```

---

## Task 5: README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Quick Start section**

Replace the existing "Quick Start" section (lines 34-93) and "Configuration" section (lines 122-132) in `README.md`:

Replace lines 34-93 with:

```markdown
## Quick Start

### Option A: Interactive wizard (recommended)

```bash
git clone https://github.com/lyume/lyume-memory-proxy.git
cd lyume-memory-proxy
uv run python python/wizard.py
```

The wizard will guide you through:
1. **Agent identity** — name your AI companion
2. **LLM backend** — auto-detects models from Ollama, LM Studio, or any OpenAI-compatible server
3. **Embedding** — configures vector embeddings (HTTP endpoint or local CPU fallback)
4. **Database** — Docker PostgreSQL or existing server
5. **Memory import** — optionally imports memories from Claude Code, Cursor, Windsurf, and other AI agents

Then start the proxy:

```bash
docker compose up -d    # if using Docker PostgreSQL
uv run python -m uvicorn memory_proxy:app --host 127.0.0.1 --port 1235
```

### Option B: Manual setup

```bash
git clone https://github.com/lyume/lyume-memory-proxy.git
cd lyume-memory-proxy
cp python/config.yaml.example python/config.yaml
# Edit python/config.yaml with your LLM URL, model, and database settings
docker compose up -d
```

### Verify it works

Point your app to `http://localhost:1235` instead of your LLM's direct URL.

```bash
curl http://localhost:1235/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "any",
    "messages": [
      {"role": "user", "content": "My name is Alex, I live in Berlin"}
    ]
  }'
```

In a new session, ask:

```bash
curl http://localhost:1235/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "any",
    "messages": [
      {"role": "user", "content": "Where do I live?"}
    ]
  }'
```

The AI recalls "Berlin" — without you re-stating it.
```

Replace lines 122-132 (Configuration section) with:

```markdown
## Configuration

Edit `python/config.yaml` (created by wizard or manually). Key sections:

- **`llm:`** — LLM API URL, model name, API key, timeouts (works with any OpenAI-compatible server)
- **`embedding:`** — provider (`http` or `local`), model, dimensions
- **`database:`** — provider (`docker` or `external`), PostgreSQL connection settings
- **`memory:`** — search limits, similarity thresholds, dedup settings
- **`lessons:`** — ELO rating system, similarity thresholds
- **`features:`** — toggle think-tag stripping, session summaries, marker fallback
- **`consolidation:`** — automatic memory merging schedule and thresholds

See [python/config.yaml](python/config.yaml) for all options and defaults.

### Memory Import

Import memories from other AI agents at any time:

```bash
uv run python python/wizard.py  # re-run wizard, choose "Memory Import"
```

Supported sources: Claude Code, Cursor, Windsurf, Cline, GitHub Copilot, OpenAI Codex, Gemini CLI, Aider.
```

- [ ] **Step 2: Verify README renders correctly**

Run: `cd /home/tarik/.openclaw/workspace-lyume && head -80 README.md`
Expected: New Quick Start section visible

- [ ] **Step 3: Run full test suite one final time**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add README.md
git commit -m "docs: update README with wizard Quick Start and new config sections"
```
