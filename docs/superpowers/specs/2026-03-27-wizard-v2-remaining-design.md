# Spec: Wizard v2 — Remaining Tasks

**Date:** 2026-03-27
**Status:** Approved
**Scope:** 5 tasks (must-fix + nice-to-have) to complete Wizard v2 for release

---

## 1. Dependencies Step

**Problem:** Wizard doesn't create `.venv` or install dependencies. Service won't start without them.

**Solution:** New step `steps/dependencies.py`, executed after Summary confirm, before service setup.

**Flow:**
1. Detect `pyproject.toml` in workspace root
2. Check if `uv` is available (`shutil.which("uv")`)
3. If `uv`: run `uv sync` (auto-creates .venv)
4. If no `uv`: run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
5. Show spinner/progress during install
6. On error: show output, offer retry or manual instructions
7. Store `.venv/bin/python` path in state for service setup

**Integration:** `summary.py` calls this after user confirms config, before service setup. Not a wizard navigation step — it's a post-confirm action (no back navigation needed).

---

## 2. Port Conflict Handling + Auto Port Selection

**Problem:** If port 5432 (PG) or 1235 (proxy) is occupied, wizard silently fails or errors.

**Solution:** New utility `wizard/port_utils.py` + integration in database.py and summary.py.

**port_utils.py API:**
```python
def is_port_in_use(host: str, port: int) -> bool
    # socket.connect_ex(), returns True if occupied

def find_free_port(host: str, start: int, max_attempts: int = 10) -> int | None
    # Scans start..start+max_attempts, returns first free port or None
```

**Integration in database.py:**
- Before starting Docker PG or accepting external PG port
- If port in use: `"Port 5432 is in use. Use 5433 instead? [Y/n/custom]"`
- Store chosen port in state

**Integration in summary.py (service setup):**
- Before creating service: check proxy port (default 1235)
- If in use: same prompt pattern
- Store in config output

---

## 3. Docker Compose — Better Diagnostics

**Problem:** Single error message for Docker issues. No distinction between Docker Engine missing vs Compose plugin missing.

**Solution:** Split detection in `steps/docker.py` into 3 checks.

**Detection matrix:**

| Docker Engine | Compose Plugin | Action |
|---|---|---|
| Yes + running | Yes | Proceed |
| Yes + running | No | Show Compose install instructions |
| Yes + stopped | N/A | Show start instructions + retry |
| No | N/A | Show full install instructions |

**Compose install instructions (platform-specific via platform.py):**
- Arch: `sudo pacman -S docker-compose`
- Ubuntu/Debian: `sudo apt install docker-compose-plugin`
- Fedora/RHEL: `sudo dnf install docker-compose-plugin`
- macOS: included with Docker Desktop
- Windows: included with Docker Desktop

---

## 4. OpenClaw Agent Registration

**Problem:** Wizard doesn't register the agent in OpenClaw after setup.

**Solution:** After service setup in summary.py, attempt OpenClaw registration.

**Method:** Shell out to `openclaw agents add` CLI:
```bash
openclaw agents add {slug} \
  --workspace {workspace_path} \
  --model {llm_model} \
  --non-interactive
```

**Behavior:**
- Check `shutil.which("openclaw")` first
- If CLI not found: skip silently (OpenClaw is optional)
- If CLI found: attempt registration
- On success: show confirmation
- On error: show warning, don't block wizard completion
- Agent ID/slug: normalized agent_name (lowercase, hyphens)

---

## 5. i18n — Complete strings.py

**Problem:** Some strings still hardcoded in step files. No language toggle.

**Solution:** Extract all user-facing strings to strings.py with language support.

**Language selection:**
- Environment variable `LYUME_LANG=uk|en` (default: `uk`)
- Not a wizard step — respects system preference

**strings.py structure:**
```python
_STRINGS = {
    "uk": {
        "welcome_title": "Ласкаво просимо до Lyume Wizard",
        "port_in_use": "Порт {port} зайнятий. Використати {alt}? [Y/n]",
        ...
    },
    "en": {
        "welcome_title": "Welcome to Lyume Wizard",
        "port_in_use": "Port {port} is in use. Use {alt} instead? [Y/n]",
        ...
    }
}

def t(key: str, **kwargs) -> str
    # Get translated string for current LYUME_LANG, format with kwargs
```

**Scope:** Extract all hardcoded strings from all step files + engine.py. Add English translations for each.

---

## Files Changed/Created

| Action | File |
|--------|------|
| Create | `wizard/port_utils.py` |
| Modify | `wizard/steps/dependencies.py` (new post-confirm action) |
| Modify | `wizard/steps/database.py` (port check) |
| Modify | `wizard/steps/docker.py` (split detection, compose instructions) |
| Modify | `wizard/steps/summary.py` (deps install, port check, openclaw registration) |
| Modify | `wizard/platform.py` (add compose install instructions) |
| Modify | `wizard/strings.py` (full i18n with uk/en, t() function) |
| Modify | `wizard/engine.py` (use t() for engine strings) |
| Modify | `wizard/state.py` (add proxy_port, venv_python fields) |
