# Wizard v2 — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-03-26-wizard-v2-design.md`
**Working dir:** `/home/tarik/.openclaw/workspace-lyume`

---

## Task 1: Scaffold wizard package + state + engine

**Create:** `python/wizard/__init__.py`, `engine.py`, `state.py`, `steps/__init__.py`, `strings.py`
**Delete:** `python/wizard.py` (old monolith)

- WizardState dataclass: all config fields + current_step + checkpoint save/load to `.wizard_checkpoint.yaml`
- WizardEngine: step list, run loop with `b` navigation, progress bar (rich), checkpoint on each step
- BaseStep ABC with `run(state) -> StepResult`
- `__init__.py` exports `run_wizard()`, `should_run_wizard()`
- `strings.py`: all user-facing text as constants

**Test:** `python -m pytest python/tests/test_wizard.py -v` (update imports)

---

## Task 2: platform.py + backend_detect.py

**Create:** `python/wizard/platform.py`, `python/wizard/backend_detect.py`

- `platform.py`: detect OS (linux/macos/windows), distro (arch/ubuntu/debian/fedora), Docker install instructions, service setup commands
- `backend_detect.py`: async scan LM Studio(:1234), Ollama(:11434), llama.cpp(:8080) via `/v1/models`, return BackendInfo(name, url, models)

**Test:** unit tests for platform detection + mock tests for backend scan

---

## Task 3: Steps — identity, backend, embedding

**Create:** `python/wizard/steps/identity.py`, `backend.py`, `embedding.py`

- identity: ask name, save IDENTITY.md/USER.md
- backend: call backend_detect, show found backends, select model, handle manual URL, API key on 401
- embedding: filter models by embed patterns, offer download, test embed, auto-detect dimensions

---

## Task 4: Steps — docker, database, memory_import, summary

**Create:** `python/wizard/steps/docker.py`, `database.py`, `memory_import.py`, `summary.py`

- docker: check docker, show platform-specific install instructions, checkpoint restart
- database: Docker Compose PG or external, test connection
- memory_import: reuse existing detect_known_memory_paths logic
- summary: show table, `c` to confirm, `1-5` to redo step

---

## Task 5: Proxy service auto-setup + wiring

**Modify:** `python/wizard/steps/summary.py` (add service setup after confirm)
**Modify:** `python/memory_proxy.py` (update wizard import path)

- Linux: generate + enable systemd user service
- macOS: generate + load launchd plist
- Windows: create scheduled task at logon
- Update `memory_proxy.py` lifespan to import from `wizard` package

---

## Task 6: Bugfix proactive + generate_config defaults

**Modify:** `python/memory_proxy.py` lines 56-57
**Modify:** `python/wizard/state.py` (generate_config adds proactive defaults)

- `getattr(cfg.memory, "proactive_high_similarity", 0.85)` in proxy
- Add `proactive_high_similarity: 0.85` and `proactive_dormant_days: 30` to memory section in generate_config

---

## Task 7: Update tests + existing test fix

**Modify:** `python/tests/test_wizard.py` — update all imports from `wizard` to `wizard.state`/`wizard.steps` etc.
**Run:** full test suite to verify nothing broken
