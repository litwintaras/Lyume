import sys
import subprocess
import shutil
import re
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from wizard.engine import BaseStep, StepResult
from wizard.state import WizardState
from wizard import strings as S
from wizard.platform import detect_platform, service_setup_commands, OS
from wizard.port_utils import is_port_in_use, find_free_port


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
            cmd = "uv sync" if has_uv else "python -m venv .venv && .venv/bin/pip install -e .."
            console.print(S.t("deps_manual_hint", dir=str(python_dir), cmd=cmd))
            retry = Prompt.ask(S.t("deps_retry"), default="Y")
            if retry.lower() != "y":
                return False


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


class SummaryStep(BaseStep):
    title = S.STEP_SUMMARY

    def run(self, state: WizardState, console: Console) -> StepResult:
        # Show Panel with summary
        summary_text = (
            f"  [bold]1.[/bold] {S.t('summary_agent')}:     {state.agent_name}\n"
            f"  [bold]2.[/bold] {S.t('summary_user')}:      {state.user_name}\n"
            f"  [bold]3.[/bold] {S.t('summary_backend')}:   {state.backend_name} ({state.llm_model})\n"
            f"  [bold]4.[/bold] {S.t('summary_embedding')}: {state.embed_provider} ({state.embed_model})\n"
            f"  [bold]5.[/bold] {S.t('summary_database')}:  {state.db_provider} ({state.db_host}:{state.db_port})\n"
            f"  [bold]6.[/bold] {S.t('summary_import')}:    {S.t('summary_sources', n=len(state.import_paths))}"
        )

        console.print(Panel(summary_text, title=S.t("summary_title"), border_style="cyan"))

        console.print(S.t("summary_redo_hint"))
        console.print(S.t("summary_confirm_hint"))
        choice = Prompt.ask(S.t("summary_choice"), choices=["c", "b", "1", "2", "3", "4", "5", "6"], show_choices=False)

        if choice == "b":
            return StepResult.BACK

        if choice in ("1", "2", "3", "4", "5", "6"):
            step_map = {"1": 0, "2": 0, "3": 1, "4": 2, "5": 4, "6": 5}
            state.current_step = step_map[choice]
            return StepResult.BACK

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

        return StepResult.NEXT
