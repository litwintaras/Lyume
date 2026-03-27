# Wizard v2 — Remaining Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete all 5 remaining tasks (deps install, port conflicts, Docker Compose diagnostics, OpenClaw registration, i18n) to ship Wizard v2.

**Architecture:** Each task adds/modifies focused files in `python/wizard/`. New utility `port_utils.py` handles port scanning. Dependencies install and OpenClaw registration are post-confirm actions in summary.py. i18n uses a `t()` function in strings.py with `LYUME_LANG` env toggle.

**Tech Stack:** Python 3.12+, Rich (console UI), subprocess, socket, shutil, PyYAML

**Workspace:** `/home/tarik/.openclaw/workspace-lyume`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `python/wizard/port_utils.py` | Port availability check + free port finder |
| Modify | `python/wizard/state.py` | Add `proxy_port` and `venv_python` fields |
| Modify | `python/wizard/strings.py` | Full i18n with `t()` function, UK/EN strings |
| Modify | `python/wizard/engine.py` | Use `t()` for engine strings |
| Modify | `python/wizard/platform.py` | Add `compose_install_instructions()` |
| Modify | `python/wizard/steps/docker.py` | Split Docker Engine vs Compose detection |
| Modify | `python/wizard/steps/database.py` | Port conflict check before PG setup |
| Modify | `python/wizard/steps/summary.py` | Deps install, proxy port check, OpenClaw registration |
| Modify | `python/wizard/steps/identity.py` | Use `t()` |
| Modify | `python/wizard/steps/backend.py` | Use `t()` |
| Modify | `python/wizard/steps/embedding.py` | Use `t()` |
| Modify | `python/wizard/steps/memory_import.py` | Use `t()` |

---

## Task 1: Port Utilities

**Files:**
- Create: `python/wizard/port_utils.py`

- [ ] **Step 1: Create port_utils.py**

```python
"""Port availability utilities."""
import socket


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a TCP port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def find_free_port(host: str, start: int, max_attempts: int = 10) -> int | None:
    """Find the first free port starting from `start`.
    Returns the port number or None if all checked ports are in use.
    """
    for offset in range(max_attempts):
        port = start + offset
        if not is_port_in_use(host, port):
            return port
    return None
```

- [ ] **Step 2: Commit**

```bash
git add python/wizard/port_utils.py
git commit -m "feat(wizard): add port_utils — port availability check + free port finder"
```

---

## Task 2: State — Add proxy_port and venv_python Fields

**Files:**
- Modify: `python/wizard/state.py`

- [ ] **Step 1: Add fields to WizardState dataclass**

In `state.py`, add after `current_step: int = 0`:

```python
    # Post-confirm
    proxy_port: int = 1235
    venv_python: str = ""
```

- [ ] **Step 2: Update generate_config() to use proxy_port**

In `state.py`, change the `server` section in `generate_config()`:

Old:
```python
            "server": {"host": "127.0.0.1", "port": 1235, "log_level": "info"},
```

New:
```python
            "server": {"host": "127.0.0.1", "port": self.proxy_port, "log_level": "info"},
```

- [ ] **Step 3: Commit**

```bash
git add python/wizard/state.py
git commit -m "feat(wizard): add proxy_port and venv_python fields to WizardState"
```

---

## Task 3: i18n — Full strings.py with t() Function

**Files:**
- Modify: `python/wizard/strings.py`

- [ ] **Step 1: Rewrite strings.py with i18n support**

Replace entire `strings.py` with:

```python
"""User-facing text constants for Lyume wizard — i18n support."""
import os

_LANG = os.environ.get("LYUME_LANG", "uk")

_STRINGS = {
    "uk": {
        "welcome_title": "Ласкаво просимо до Lyume Wizard",
        "welcome_body": "Цей майстер допоможе вам налаштувати вашу систему Lyume для роботи з великими мовними моделями.",
        "step_identity": "Особисті дані та назва проєкту",
        "step_backend": "Вибір бекенду (LLM)",
        "step_embedding": "Вибір моделі ембеддингів",
        "step_docker": "Перевірка Docker",
        "step_database": "Налаштування бази даних",
        "step_import": "Імпорт початкових даних (опціонально)",
        "step_summary": "Підсумок конфігурації",
        "back_hint": "(введіть 'b', щоб повернутися назад)",
        "checkpoint_found": "Знайдено попередню сесію налаштувань.",
        "checkpoint_continue": "Продовжити з місця, де ви зупинилися?",
        "step_progress": "Крок {current}/{total}: {title}",
        # Identity
        "agent_name": "Ім'я агента",
        "user_name": "Ім'я користувача",
        # Backend
        "scanning_backends": "Сканую локальні бекенди...",
        "found_backends": "Знайдені бекенди:",
        "no_backends_found": "Не знайдено жодного доступного локального бекенду LLM.",
        "pick_backend": "Виберіть (1-{n}) або 'm' для ручного вводу або 'b' назад",
        "manual_url": "Введіть URL бекенду",
        "llm_models": "LLM моделі:",
        "pick_model": "Виберіть модель або 'b' назад",
        "api_key": "API ключ (залиште порожнім якщо не потрібен)",
        # Embedding
        "embed_models_available": "Доступні моделі ембеддингів:",
        "pick_embed_model": "Виберіть модель або 'b' назад",
        "no_embed_models": "Не знайдено моделей ембеддингів.",
        "embed_recommend": "Рекомендовано: nomic-embed-text-v1.5",
        "embed_download": "Завантажити (Ollama: ollama pull nomic-embed-text)",
        "embed_diff_url": "Використати інший URL",
        "embed_local_gguf": "Використати локальний GGUF файл",
        "embed_dims": "Розмірність ембеддингів: {dims}",
        "embed_test_fail": "Не вдалося протестувати ембеддинг: {err}",
        "enter_gguf_path": "Введіть шлях до GGUF файлу",
        # Docker
        "docker_ok": "Docker запущено",
        "docker_not_running": "Docker встановлено, але не запущено.",
        "docker_start_hint": "Запустіть: sudo systemctl start docker",
        "docker_retry": "[r] Повторити | [s] Пропустити",
        "docker_now_running": "Docker тепер запущено",
        "docker_not_installed": "Docker не встановлено.",
        "docker_purpose": "Docker запускає PostgreSQL для зберігання пам'яті.",
        "docker_install_time": "Встановлення займає ~2 хвилини.",
        "docker_restart": "[r] Перезапустити wizard | [s] Пропустити",
        "docker_compose_missing": "Docker Compose не встановлено.",
        "docker_compose_hint": "Docker Compose потрібен для запуску PostgreSQL.",
        # Database
        "db_docker_option": "[1] Docker PostgreSQL (рекомендовано — нульова конфігурація)",
        "db_external_option": "[2] Зовнішній PostgreSQL",
        "db_choose": "Виберіть",
        "db_no_docker": "Docker не доступний. Використовуємо зовнішній PostgreSQL.",
        "db_waiting": "Очікую готовність PostgreSQL...",
        "db_not_ready": "Попередження: база даних може бути ще не готова",
        "db_start_fail": "Не вдалося запустити Docker PostgreSQL: {err}",
        "db_compose_not_found": "Docker Compose не знайдено.",
        "db_host": "PostgreSQL хост",
        "db_port": "PostgreSQL порт",
        "db_user": "PostgreSQL користувач",
        "db_password": "PostgreSQL пароль",
        "port_in_use": "Порт {port} зайнятий.",
        "port_suggest": "Використати {port} замість цього? [Y/n]",
        "port_custom": "Введіть порт вручну",
        "port_all_busy": "Не вдалося знайти вільний порт в діапазоні {start}-{end}.",
        # Import
        "import_auto_scan": "[1] Авто-сканування",
        "import_enter_path": "[2] Ввести шлях",
        "import_skip": "[3] Пропустити",
        "import_choose": "Виберіть",
        "import_found": "Знайдено:",
        "import_not_found": "Не знайдено відомих шляхів пам'яті.",
        "import_enter": "Введіть шлях для імпорту",
        "import_path_missing": "Шлях не існує",
        # Summary
        "summary_title": "Підсумок конфігурації",
        "summary_redo_hint": "Хочете щось змінити? Введіть номер [bold](1-6)[/bold] щоб переробити крок.",
        "summary_confirm_hint": "Або натисніть [bold][c][/bold] щоб підтвердити  |  [bold][b][/bold] назад",
        "summary_choice": "Ваш вибір",
        # Dependencies
        "deps_installing": "Встановлюю залежності...",
        "deps_uv_found": "Знайдено uv — використовую uv sync",
        "deps_pip_fallback": "uv не знайдено — використовую pip",
        "deps_success": "Залежності встановлені",
        "deps_fail": "Не вдалося встановити залежності: {err}",
        "deps_retry": "Спробувати ще раз? [Y/n]",
        "deps_manual_hint": "Встановіть вручну:\n  cd {dir}\n  {cmd}",
        # Service
        "service_ok": "Сервіс налаштовано успішно!",
        "service_fail": "Не вдалося налаштувати сервіс: {err}",
        "service_status": "Перевірити статус:",
        "service_logs": "Переглянути логи:",
        # Proxy port
        "proxy_port_check": "Перевіряю порт проксі ({port})...",
        "proxy_port_ok": "Порт {port} вільний",
        # OpenClaw
        "openclaw_registering": "Реєструю агента в OpenClaw...",
        "openclaw_ok": "Агент зареєстрований в OpenClaw",
        "openclaw_not_found": "openclaw CLI не знайдено — пропускаю реєстрацію",
        "openclaw_fail": "Не вдалося зареєструвати агента: {err}",
    },
    "en": {
        "welcome_title": "Welcome to Lyume Wizard",
        "welcome_body": "This wizard will help you set up your Lyume system for working with large language models.",
        "step_identity": "Identity & Project Name",
        "step_backend": "LLM Backend Selection",
        "step_embedding": "Embedding Model Selection",
        "step_docker": "Docker Check",
        "step_database": "Database Setup",
        "step_import": "Import Initial Data (optional)",
        "step_summary": "Configuration Summary",
        "back_hint": "(type 'b' to go back)",
        "checkpoint_found": "Previous setup session found.",
        "checkpoint_continue": "Continue from where you left off?",
        "step_progress": "Step {current}/{total}: {title}",
        # Identity
        "agent_name": "Agent name",
        "user_name": "User name",
        # Backend
        "scanning_backends": "Scanning local backends...",
        "found_backends": "Found backends:",
        "no_backends_found": "No available local LLM backends found.",
        "pick_backend": "Pick (1-{n}) or 'm' for manual or 'b' back",
        "manual_url": "Enter backend URL",
        "llm_models": "LLM models:",
        "pick_model": "Pick model or 'b' back",
        "api_key": "API key (leave empty if not needed)",
        # Embedding
        "embed_models_available": "Embedding models available:",
        "pick_embed_model": "Pick model or 'b' back",
        "no_embed_models": "No embedding models found.",
        "embed_recommend": "Recommended: nomic-embed-text-v1.5",
        "embed_download": "Download (Ollama: ollama pull nomic-embed-text)",
        "embed_diff_url": "Use different URL",
        "embed_local_gguf": "Use local GGUF file",
        "embed_dims": "Embedding dimensions: {dims}",
        "embed_test_fail": "Could not test embedding: {err}",
        "enter_gguf_path": "Enter path to GGUF file",
        # Docker
        "docker_ok": "Docker is running",
        "docker_not_running": "Docker installed but not running.",
        "docker_start_hint": "Start with: sudo systemctl start docker",
        "docker_retry": "[r] Retry | [s] Skip",
        "docker_now_running": "Docker is now running",
        "docker_not_installed": "Docker is not installed.",
        "docker_purpose": "Docker runs PostgreSQL for memory storage.",
        "docker_install_time": "Installation takes ~2 minutes.",
        "docker_restart": "[r] Restart wizard | [s] Skip",
        "docker_compose_missing": "Docker Compose is not installed.",
        "docker_compose_hint": "Docker Compose is needed to run PostgreSQL.",
        # Database
        "db_docker_option": "[1] Docker PostgreSQL (recommended — zero config)",
        "db_external_option": "[2] External PostgreSQL",
        "db_choose": "Choose",
        "db_no_docker": "Docker not available. Using external PostgreSQL.",
        "db_waiting": "Waiting for PostgreSQL to be ready...",
        "db_not_ready": "Warning: database may not be ready yet",
        "db_start_fail": "Failed to start Docker PostgreSQL: {err}",
        "db_compose_not_found": "Docker Compose not found.",
        "db_host": "PostgreSQL host",
        "db_port": "PostgreSQL port",
        "db_user": "PostgreSQL user",
        "db_password": "PostgreSQL password",
        "port_in_use": "Port {port} is in use.",
        "port_suggest": "Use {port} instead? [Y/n]",
        "port_custom": "Enter port manually",
        "port_all_busy": "Could not find a free port in range {start}-{end}.",
        # Import
        "import_auto_scan": "[1] Auto-scan",
        "import_enter_path": "[2] Enter path",
        "import_skip": "[3] Skip",
        "import_choose": "Choose",
        "import_found": "Found:",
        "import_not_found": "No known memory paths found.",
        "import_enter": "Enter path to import",
        "import_path_missing": "Path does not exist",
        # Summary
        "summary_title": "Configuration Summary",
        "summary_redo_hint": "Want to change something? Enter a number [bold](1-6)[/bold] to redo that step.",
        "summary_confirm_hint": "Or press [bold][c][/bold] to confirm  |  [bold][b][/bold] to go back",
        "summary_choice": "Your choice",
        # Dependencies
        "deps_installing": "Installing dependencies...",
        "deps_uv_found": "Found uv — using uv sync",
        "deps_pip_fallback": "uv not found — using pip",
        "deps_success": "Dependencies installed",
        "deps_fail": "Failed to install dependencies: {err}",
        "deps_retry": "Retry? [Y/n]",
        "deps_manual_hint": "Install manually:\n  cd {dir}\n  {cmd}",
        # Service
        "service_ok": "Service configured successfully!",
        "service_fail": "Failed to configure service: {err}",
        "service_status": "Check status:",
        "service_logs": "View logs:",
        # Proxy port
        "proxy_port_check": "Checking proxy port ({port})...",
        "proxy_port_ok": "Port {port} is free",
        # OpenClaw
        "openclaw_registering": "Registering agent in OpenClaw...",
        "openclaw_ok": "Agent registered in OpenClaw",
        "openclaw_not_found": "openclaw CLI not found — skipping registration",
        "openclaw_fail": "Failed to register agent: {err}",
    },
}


def t(key: str, **kwargs) -> str:
    """Get translated string for current LYUME_LANG."""
    lang = _LANG if _LANG in _STRINGS else "uk"
    text = _STRINGS[lang].get(key, _STRINGS["uk"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text


# Backward-compatible constants (used in step title attributes)
STEP_IDENTITY = t("step_identity")
STEP_BACKEND = t("step_backend")
STEP_EMBEDDING = t("step_embedding")
STEP_DOCKER = t("step_docker")
STEP_DATABASE = t("step_database")
STEP_IMPORT = t("step_import")
STEP_SUMMARY = t("step_summary")
```

- [ ] **Step 2: Commit**

```bash
git add python/wizard/strings.py
git commit -m "feat(wizard): full i18n strings.py with t() function and UK/EN support"
```

---

## Task 4: i18n — Migrate All Steps to t()

**Files:**
- Modify: `python/wizard/engine.py`
- Modify: `python/wizard/steps/identity.py`
- Modify: `python/wizard/steps/backend.py`
- Modify: `python/wizard/steps/embedding.py`
- Modify: `python/wizard/steps/docker.py`
- Modify: `python/wizard/steps/database.py`
- Modify: `python/wizard/steps/memory_import.py`
- Modify: `python/wizard/steps/summary.py`

This task replaces all hardcoded user-facing strings in every file with `t()` calls. Each file is a sub-step below.

- [ ] **Step 1: Update engine.py**

Replace the checkpoint and welcome strings with `t()` calls:

Old (line 47-48):
```python
            console.print(f"\n{S.CHECKPOINT_FOUND}")
            choice = Prompt.ask(S.CHECKPOINT_CONTINUE, choices=["y", "n"], default="y")
```
New:
```python
            console.print(f"\n{S.t('checkpoint_found')}")
            choice = Prompt.ask(S.t("checkpoint_continue"), choices=["y", "n"], default="y")
```

Old (line 55-58):
```python
        console.print(Panel(
            f"[bold cyan]{S.WELCOME_TITLE}[/bold cyan]\n\n{S.WELCOME_BODY}",
            title="Welcome",
            border_style="cyan",
        ))
```
New:
```python
        console.print(Panel(
            f"[bold cyan]{S.t('welcome_title')}[/bold cyan]\n\n{S.t('welcome_body')}",
            title="Lyume",
            border_style="cyan",
        ))
```

Old (line 70):
```python
            console.print(f"\n[dim][{bar}] Step {idx + 1}/{total}: {step.title}[/dim]")
```
New:
```python
            console.print(f"\n[dim][{bar}] {S.t('step_progress', current=idx+1, total=total, title=step.title)}[/dim]")
```

- [ ] **Step 2: Update identity.py**

Replace full `run` method body:

```python
    def run(self, state: WizardState, console: Console) -> StepResult:
        console.print(S.t("back_hint"))

        agent_name_input = Prompt.ask(S.t("agent_name"), default=state.agent_name)
        if agent_name_input == 'b':
            return StepResult.BACK

        user_name_input = Prompt.ask(S.t("user_name"), default=state.user_name)
        if user_name_input == 'b':
            return StepResult.BACK

        state.agent_name = agent_name_input
        state.user_name = user_name_input

        return StepResult.NEXT
```

- [ ] **Step 3: Update docker.py**

Replace all hardcoded strings. Full new `run` method:

```python
    def run(self, state: WizardState, console: Console) -> StepResult:
        info = detect_platform()

        if info.docker_running:
            # Check for Compose
            has_compose = _check_compose()
            if has_compose:
                console.print(f"[green]✓ {S.t('docker_ok')}[/green]")
                state.docker_available = True
                return StepResult.NEXT
            else:
                console.print(f"[yellow]! {S.t('docker_compose_missing')}[/yellow]")
                console.print(S.t("docker_compose_hint"))
                instructions = compose_install_instructions(info)
                console.print(instructions)
                while True:
                    choice = Prompt.ask(S.t("docker_retry"), choices=["r", "s", "b"], show_choices=False)
                    if choice == "r":
                        if _check_compose():
                            console.print(f"[green]✓ {S.t('docker_ok')}[/green]")
                            state.docker_available = True
                            return StepResult.NEXT
                    elif choice == "s":
                        state.docker_available = False
                        return StepResult.NEXT
                    elif choice == "b":
                        return StepResult.BACK

        elif info.docker_installed and not info.docker_running:
            console.print(f"! {S.t('docker_not_running')}")
            console.print(S.t("docker_start_hint"))

            while True:
                choice = Prompt.ask(S.t("docker_retry"), choices=["r", "s", "b"], show_choices=False)
                if choice == "r":
                    info = detect_platform()
                    if info.docker_running:
                        console.print(f"[green]✓ {S.t('docker_now_running')}[/green]")
                        state.docker_available = True
                        return StepResult.NEXT
                    elif not info.docker_installed:
                        break
                elif choice == "s":
                    state.docker_available = False
                    return StepResult.NEXT
                elif choice == "b":
                    return StepResult.BACK

        # Not installed
        console.print(f"! {S.t('docker_not_installed')}")
        console.print(S.t("docker_purpose"))
        console.print(S.t("docker_install_time"))

        instructions = docker_install_instructions(info)
        console.print(instructions)

        while True:
            choice = Prompt.ask(S.t("docker_restart"), choices=["r", "s", "b"], show_choices=False)
            if choice == "r":
                return StepResult.RESTART
            elif choice == "s":
                state.docker_available = False
                return StepResult.NEXT
            elif choice == "b":
                return StepResult.BACK

        return StepResult.NEXT
```

Add helper at top of docker.py (after imports):

```python
import subprocess

def _check_compose() -> bool:
    """Check if Docker Compose plugin is available."""
    for cmd in [["docker", "compose", "version"], ["docker-compose", "version"]]:
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False
```

Add import at top:
```python
from wizard.platform import detect_platform, docker_install_instructions, compose_install_instructions
```

- [ ] **Step 4: Update database.py**

Replace all hardcoded strings and add port conflict handling. Full new `run` method:

```python
    def run(self, state: WizardState, console: Console) -> StepResult:
        if state.docker_available:
            console.print(S.t("db_docker_option"))
            console.print(S.t("db_external_option"))
            choice = Prompt.ask(S.t("db_choose"), choices=["1", "2", "b"], show_choices=False)

            if choice == "b":
                return StepResult.BACK
            elif choice == "1":
                # Check port before starting Docker PG
                target_port = _resolve_port(console, "127.0.0.1", 5432)
                if target_port is None:
                    return StepResult.BACK

                compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"

                compose_cmd = None
                for cmd in [["docker", "compose"], ["docker-compose"]]:
                    try:
                        subprocess.run(cmd + ["version"], capture_output=True, check=True)
                        compose_cmd = cmd
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue

                if not compose_cmd:
                    console.print(f"[red]{S.t('db_compose_not_found')}[/red]")
                    return StepResult.BACK

                try:
                    env = dict(os.environ, POSTGRES_PORT=str(target_port)) if target_port != 5432 else None
                    subprocess.run(
                        compose_cmd + ["-f", str(compose_path), "up", "-d", "db"],
                        check=True, env=env,
                    )

                    console.print(S.t("db_waiting"))
                    for _ in range(30):
                        result = subprocess.run(
                            compose_cmd + ["-f", str(compose_path), "ps", "db"],
                            capture_output=True, text=True,
                        )
                        if "healthy" in result.stdout:
                            break
                        time.sleep(1)
                    else:
                        console.print(f"[yellow]{S.t('db_not_ready')}[/yellow]")

                except subprocess.CalledProcessError as e:
                    console.print(f"[red]{S.t('db_start_fail', err=e)}[/red]")
                    return StepResult.BACK

                state.db_provider = "docker"
                state.db_host = "127.0.0.1"
                state.db_port = target_port
                state.db_user = "postgres"
                state.db_password = "lyume"

            elif choice == "2":
                state.db_provider = "external"
                state.db_host = Prompt.ask(S.t("db_host"))
                ext_port = int(Prompt.ask(S.t("db_port"), default="5432"))
                state.db_port = ext_port
                state.db_user = Prompt.ask(S.t("db_user"), default="postgres")
                state.db_password = Prompt.ask(S.t("db_password"), password=True)

        else:
            console.print(S.t("db_no_docker"))
            state.db_provider = "external"
            state.db_host = Prompt.ask(S.t("db_host"))
            state.db_port = int(Prompt.ask(S.t("db_port"), default="5432"))
            state.db_user = Prompt.ask(S.t("db_user"), default="postgres")
            state.db_password = Prompt.ask(S.t("db_password"), password=True)

        normalized = re.sub(r"[^a-z0-9_]", "_", state.agent_name.lower()).strip("_")
        state.db_name = f"ai_memory_{normalized}"

        return StepResult.NEXT
```

Add helper function and imports at top of database.py:

```python
import os
from wizard.port_utils import is_port_in_use, find_free_port

def _resolve_port(console: Console, host: str, default_port: int) -> int | None:
    """Check if port is free, offer alternative if not. Returns port or None."""
    if not is_port_in_use(host, default_port):
        return default_port

    console.print(f"[yellow]{S.t('port_in_use', port=default_port)}[/yellow]")
    alt = find_free_port(host, default_port + 1)
    if alt:
        yn = Prompt.ask(S.t("port_suggest", port=alt), default="Y")
        if yn.lower() in ("y", ""):
            return alt
        custom = Prompt.ask(S.t("port_custom"))
        try:
            return int(custom)
        except ValueError:
            return None
    else:
        console.print(f"[red]{S.t('port_all_busy', start=default_port, end=default_port+10)}[/red]")
        custom = Prompt.ask(S.t("port_custom"))
        try:
            return int(custom)
        except ValueError:
            return None
```

- [ ] **Step 5: Update embedding.py**

Replace hardcoded strings with `t()` calls. Key replacements:

- `"Could not fetch models from {state.llm_url}: {e}"` → `S.t("embed_test_fail", err=e)` (or similar context message)
- `"Embedding models available:"` → `S.t("embed_models_available")`
- `"Pick model or 'b' back"` → `S.t("pick_embed_model")`
- `"! No embedding models found."` → `S.t("no_embed_models")`
- `"Recommended: nomic-embed-text-v1.5"` → `S.t("embed_recommend")`
- `f"Embedding dimensions: {dims}"` → `S.t("embed_dims", dims=dims)`
- `"Could not test embedding: {e}"` → `S.t("embed_test_fail", err=e)`
- `"Enter path to GGUF file"` → `S.t("enter_gguf_path")`
- `"[1] Download ..."` → `f"[1] {S.t('embed_download')}"`
- `"[2] Use different URL"` → `f"[2] {S.t('embed_diff_url')}"`
- `"[3] Use local GGUF file"` → `f"[3] {S.t('embed_local_gguf')}"`

- [ ] **Step 6: Update memory_import.py**

Replace hardcoded strings:

- `"[1] Auto-scan"` → `S.t("import_auto_scan")`
- `"[2] Enter path"` → `S.t("import_enter_path")`
- `"[3] Skip"` → `S.t("import_skip")`
- `"Choose"` → `S.t("import_choose")`
- `"Found:"` → `S.t("import_found")`
- `"No known memory paths found."` → `S.t("import_not_found")`
- `"Enter path to import"` → `S.t("import_enter")`
- `"[red]Path does not exist[/red]"` → `f"[red]{S.t('import_path_missing')}[/red]"`

- [ ] **Step 7: Update summary.py**

Replace hardcoded strings:

- `"Configuration Summary"` panel title → `S.t("summary_title")`
- `"Want to change something?..."` → `S.t("summary_redo_hint")`
- `"Or press [c]..."` → `S.t("summary_confirm_hint")`
- `"Your choice"` → `S.t("summary_choice")`

- [ ] **Step 8: Commit**

```bash
git add python/wizard/engine.py python/wizard/steps/
git commit -m "refactor(wizard): migrate all user-facing strings to t() i18n"
```

---

## Task 5: Docker Compose — Better Diagnostics

**Files:**
- Modify: `python/wizard/platform.py`

- [ ] **Step 1: Add compose_install_instructions() to platform.py**

Add after `docker_install_instructions()`:

```python
def compose_install_instructions(info: PlatformInfo) -> str:
    """Return platform-specific Docker Compose install instructions."""
    if info.os == OS.LINUX:
        cmds = {
            Distro.ARCH: "sudo pacman -S docker-compose",
            Distro.UBUNTU: "sudo apt install docker-compose-plugin",
            Distro.DEBIAN: "sudo apt install docker-compose-plugin",
            Distro.FEDORA: "sudo dnf install docker-compose-plugin",
            Distro.RHEL: "sudo dnf install docker-compose-plugin",
        }
        cmd = cmds.get(info.distro, "sudo apt install docker-compose-plugin")
        return f"Install Docker Compose:\n\n  {cmd}"
    elif info.os == OS.MACOS:
        return "Docker Compose is included with Docker Desktop. Reinstall Docker Desktop if missing."
    elif info.os == OS.WINDOWS:
        return "Docker Compose is included with Docker Desktop. Reinstall Docker Desktop if missing."
    return "Visit https://docs.docker.com/compose/install/ for instructions."
```

- [ ] **Step 2: Commit**

```bash
git add python/wizard/platform.py
git commit -m "feat(wizard): add compose_install_instructions() for split Docker diagnostics"
```

---

## Task 6: Summary — Dependencies Install, Proxy Port Check, OpenClaw Registration

**Files:**
- Modify: `python/wizard/steps/summary.py`

This is the largest task. After user confirms config (`choice == "c"`), the summary step now does 4 things in order:
1. Install dependencies (.venv)
2. Check proxy port
3. Setup service
4. Register in OpenClaw

- [ ] **Step 1: Add imports to summary.py**

Add at top:

```python
import shutil
import re
import os
from wizard.port_utils import is_port_in_use, find_free_port
```

- [ ] **Step 2: Add _install_deps() helper**

Add before the SummaryStep class:

```python
def _install_deps(console: Console, python_dir: Path, state: WizardState) -> bool:
    """Install Python dependencies. Returns True on success."""
    console.print(f"\n[bold]{S.t('deps_installing')}[/bold]")

    has_uv = shutil.which("uv") is not None
    venv_path = python_dir / ".venv"

    while True:
        try:
            if has_uv:
                console.print(S.t("deps_uv_found"))
                subprocess.run(["uv", "sync"], cwd=str(python_dir), check=True)
            else:
                console.print(S.t("deps_pip_fallback"))
                if not venv_path.exists():
                    subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
                pip = str(venv_path / "bin" / "pip")
                subprocess.run([pip, "install", "-e", str(python_dir.parent)], check=True)

            state.venv_python = str(venv_path / "bin" / "python")
            console.print(f"[green]✓ {S.t('deps_success')}[/green]")
            return True

        except subprocess.CalledProcessError as e:
            console.print(f"[red]{S.t('deps_fail', err=e)}[/red]")
            cmd = "uv sync" if has_uv else f"python -m venv .venv && .venv/bin/pip install -e .."
            console.print(S.t("deps_manual_hint", dir=str(python_dir), cmd=cmd))
            retry = Prompt.ask(S.t("deps_retry"), default="Y")
            if retry.lower() != "y":
                return False
```

- [ ] **Step 3: Add _check_proxy_port() helper**

```python
def _check_proxy_port(console: Console, state: WizardState) -> bool:
    """Check proxy port, offer alternative if busy. Returns True on success."""
    port = state.proxy_port
    console.print(S.t("proxy_port_check", port=port))

    if not is_port_in_use("127.0.0.1", port):
        console.print(f"[green]✓ {S.t('proxy_port_ok', port=port)}[/green]")
        return True

    console.print(f"[yellow]{S.t('port_in_use', port=port)}[/yellow]")
    alt = find_free_port("127.0.0.1", port + 1)
    if alt:
        yn = Prompt.ask(S.t("port_suggest", port=alt), default="Y")
        if yn.lower() in ("y", ""):
            state.proxy_port = alt
            return True

    custom = Prompt.ask(S.t("port_custom"))
    try:
        state.proxy_port = int(custom)
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Add _register_openclaw() helper**

```python
def _register_openclaw(console: Console, state: WizardState, workspace_path: str):
    """Register agent in OpenClaw if CLI available."""
    openclaw = shutil.which("openclaw")
    if not openclaw:
        console.print(f"[dim]{S.t('openclaw_not_found')}[/dim]")
        return

    console.print(S.t("openclaw_registering"))
    slug = re.sub(r"[^a-z0-9]", "-", state.agent_name.lower()).strip("-") or "lyume"

    try:
        subprocess.run(
            [
                openclaw, "agents", "add", slug,
                "--workspace", workspace_path,
                "--model", state.llm_model,
                "--non-interactive",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print(f"[green]✓ {S.t('openclaw_ok')}[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]{S.t('openclaw_fail', err=e.stderr or e)}[/yellow]")
```

- [ ] **Step 5: Rewrite the confirm block in SummaryStep.run()**

Replace the `if choice == "c":` block (lines 44-104) with:

```python
        if choice == "c":
            project_root = Path(__file__).resolve().parents[3]
            python_dir = project_root / "python"
            workspace_path = str(project_root)

            # 1. Install dependencies
            if not _install_deps(console, python_dir, state):
                return StepResult.BACK

            # 2. Check proxy port
            if not _check_proxy_port(console, state):
                return StepResult.BACK

            # 3. Setup service
            info = detect_platform()
            venv_python = state.venv_python or str(python_dir / ".venv" / "bin" / "python")
            proxy_script = str(python_dir / "memory_proxy.py")
            working_dir = str(python_dir)

            setup = service_setup_commands(info, venv_python, proxy_script, working_dir, agent_name=state.agent_name)
            svc = setup["service_name"]

            try:
                if info.os == OS.LINUX:
                    unit_path = Path(setup["unit_path"]).expanduser()
                    unit_path.parent.mkdir(parents=True, exist_ok=True)
                    unit_path.write_text(setup["unit_content"])

                    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
                    subprocess.run(["systemctl", "--user", "enable", svc], check=True)
                    subprocess.run(["systemctl", "--user", "start", svc], check=True)

                    status_cmd = setup["status_cmd"]
                    logs_cmd = setup["logs_cmd"]

                elif info.os == OS.MACOS:
                    plist_path = Path(setup["plist_path"]).expanduser()
                    plist_path.parent.mkdir(parents=True, exist_ok=True)
                    plist_path.write_text(setup["plist_content"])
                    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
                    status_cmd = setup.get("status_cmd", "launchctl list | grep lyume")
                    logs_cmd = setup.get("logs_cmd", "tail -f /tmp/lyume-proxy.log")

                elif info.os == OS.WINDOWS:
                    for cmd in setup.get("setup_cmds", []):
                        subprocess.run(cmd, shell=True, check=True)
                    status_cmd = setup.get("status_cmd", 'schtasks /query /tn "LyumeProxy"')
                    logs_cmd = setup.get("logs_cmd", "Check proxy output in terminal")

                console.print(f"\n[bold green]✓ {S.t('service_ok')}[/bold green]")
                console.print(f"\n[bold]{S.t('service_status')}[/bold]")
                console.print(f"  {status_cmd}")
                console.print(f"\n[bold]{S.t('service_logs')}[/bold]")
                console.print(f"  {logs_cmd}")

            except subprocess.CalledProcessError as e:
                console.print(f"\n[red]{S.t('service_fail', err=e)}[/red]")
                return StepResult.BACK

            # 4. Register in OpenClaw
            _register_openclaw(console, state, workspace_path)

            return StepResult.NEXT
```

- [ ] **Step 6: Commit**

```bash
git add python/wizard/steps/summary.py
git commit -m "feat(wizard): deps install, proxy port check, OpenClaw registration in summary"
```

---

## Task 7: Manual Test

- [ ] **Step 1: Set first_run: true in config.yaml**

```bash
cd /home/tarik/.openclaw/workspace-lyume/python
# Edit config.yaml: set first_run: true
```

- [ ] **Step 2: Run wizard**

```bash
cd /home/tarik/.openclaw/workspace-lyume/python
python -m wizard
```

**Verify:**
1. All steps show Ukrainian text (default LYUME_LANG=uk)
2. Port conflict detection works — if 5432 or 1235 is in use, wizard offers alternative
3. Docker step distinguishes between Docker Engine and Compose
4. After confirm: dependencies install (.venv created), service setup, OpenClaw registration attempted
5. Back navigation still works at every step

- [ ] **Step 3: Test English**

```bash
LYUME_LANG=en python -m wizard
```

Verify all strings are in English.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(wizard): wizard v2 complete — all remaining tasks implemented"
```
