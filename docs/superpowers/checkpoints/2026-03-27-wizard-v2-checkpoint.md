# Checkpoint: Wizard v2 — Testing & Bugfixes

**Date:** 2026-03-27 00:45
**Context:** ctx window exhausted, need fresh session

---

## What was done

Wizard v2 повністю написаний і протестований вручну. Коміти:
- `8ff88ee` feat: wizard v2 — step-based architecture
- `4b940cc` fix: wizard v2 bugfixes from testing

### Files created/modified
- `python/wizard/` — новий пакет (замінив monolith `wizard.py`)
  - `__init__.py`, `__main__.py`, `engine.py`, `state.py`, `strings.py`
  - `platform.py`, `backend_detect.py`
  - `steps/`: identity, backend, embedding, docker, database, memory_import, summary
- `python/memory_proxy.py` — proactive bugfix (isinstance замість getattr)

### What works (tested manually)
- Welcome + progress bar
- Identity step + back navigation (b)
- Backend auto-detect (LM Studio found on :1234)
- LLM model selection from server
- Embedding auto-detect + model selection from server
- Docker detect + retry loop
- Database: Docker Compose + External PG
- Memory import auto-scan
- Summary with numbered lines + redo
- Unique systemd service per agent (lyume-proxy-{slug})
- Proactive module: healthy after fix
- Memory save/retrieve via chat: working

---

## What remains (TODO)

### Must fix before release
1. **Install dependencies step** — wizard не створює .venv, без нього сервіс не стартує. Додати крок між summary і service setup: `uv sync` або `pip install -r requirements.txt`
2. **Port conflict handling** — якщо порт 5432 або 1235 зайнятий, wizard має запропонувати інший порт
3. **Docker Compose not installed** — wizard показує помилку але інструкція могла б бути кращою

### Nice to have
4. **OpenClaw agent registration** — wizard не додає агента в openclaw.json
5. **i18n** — strings.py готовий, Blackhole частково переклав на укр, треба вирівняти
6. **Auto port selection** — wizard сканує зайняті порти і пропонує вільний

---

## Key files
- Spec: `docs/superpowers/specs/2026-03-26-wizard-v2-design.md`
- Plan: `docs/superpowers/plans/2026-03-26-wizard-v2-plan.md`
- Memory: `~/.claude/projects/-home-tarik/memory/project_wizard_v2_status.md`

## How to test
```bash
cd /home/tarik/.openclaw/workspace-lyume/python
# Set first_run: true in config.yaml, then:
python -m wizard
```

## Quick context for next session
Працюємо в `/home/tarik/.openclaw/workspace-lyume`. Lyume Memory Proxy — open-source проект. Wizard v2 написаний і працює, треба дофіксити залишки з TODO вище і підготувати до релізу.
