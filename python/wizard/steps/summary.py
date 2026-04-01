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


def _deploy_to_workspace(console: Console, state: WizardState) -> Path:
    """Copy lyumemory code into <workspace>/lyumemory/. Returns target dir."""
    workspace = Path(state.openclaw_workspace)
    target = workspace / "lyumemory"
    source = Path(__file__).resolve().parents[2]  # python/ directory

    console.print(f"\n[bold]Deploying to {target}...[/bold]")
    target.mkdir(parents=True, exist_ok=True)

    # Copy Python source files
    for item in source.iterdir():
        if item.name in (".venv", "__pycache__", ".pytest_cache", "config.yaml"):
            continue
        dest = target / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
        else:
            shutil.copy2(item, dest)

    # Copy project root files needed for install
    project_root = source.parent
    for fname in ("pyproject.toml", "docker-compose.yml", "Dockerfile", ".dockerignore"):
        src_file = project_root / fname
        if src_file.exists():
            shutil.copy2(src_file, target / fname)

    return target


def _install_deps(console: Console, target_dir: Path, state: WizardState) -> bool:
    """Install Python dependencies in target dir. Returns True on success."""
    console.print(f"\n[bold]{S.t('deps_installing')}[/bold]")

    has_uv = shutil.which("uv") is not None
    venv_path = target_dir / ".venv"

    while True:
        try:
            if has_uv:
                console.print(S.t("deps_uv_found"))
                subprocess.run(["uv", "sync"], cwd=str(target_dir), check=True)
            else:
                console.print(S.t("deps_pip_fallback"))
                if not venv_path.exists():
                    subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
                pip = str(venv_path / "bin" / "pip")
                subprocess.run([pip, "install", "-e", str(target_dir)], check=True)

            state.venv_python = str(venv_path / "bin" / "python")
            console.print(f"[green]✓ {S.t('deps_success')}[/green]")
            return True

        except subprocess.CalledProcessError as e:
            console.print(f"[red]{S.t('deps_fail', err=e)}[/red]")
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


class SummaryStep(BaseStep):
    title = S.STEP_SUMMARY

    def run(self, state: WizardState, console: Console) -> StepResult:
        # Check proxy port BEFORE showing summary
        if not _check_proxy_port(console, state):
            return StepResult.BACK

        summary_text = (
            f"  [bold]1.[/bold] {S.t('summary_agent')}:     {state.agent_name} ({state.openclaw_agent_id})\n"
            f"  [bold]2.[/bold] {S.t('summary_backend')}:   {state.backend_name} ({state.llm_model})\n"
            f"  [bold]3.[/bold] {S.t('summary_embedding')}: {state.embed_provider} ({state.embed_model})\n"
            f"  [bold]4.[/bold] {S.t('summary_database')}:  {state.db_provider} ({state.db_host}:{state.db_port})\n"
            f"  [bold]5.[/bold] {S.t('summary_proxy')}:       127.0.0.1:{state.proxy_port}\n"
            f"  [bold]6.[/bold] {S.t('summary_import')}:    {S.t('summary_sources', n=len(state.import_paths))}\n"
            f"  [dim]Workspace: {state.openclaw_workspace}[/dim]\n"
            f"  [dim]Deploy to: {state.openclaw_workspace}/lyumemory/[/dim]"
        )

        console.print(Panel(summary_text, title=S.t("summary_title"), border_style="cyan"))

        console.print(S.t("summary_redo_hint"))
        # Explicit "Press C" instruction
        console.print(f"\n{S.t('confirm_press_c')}\n")
        choice = Prompt.ask(S.t("summary_choice"), choices=["c", "b", "1", "2", "3", "4", "5", "6"], show_choices=False)

        if choice == "b":
            return StepResult.BACK

        if choice in ("1", "2", "3", "4", "6"):
            step_map = {"1": 1, "2": 2, "3": 3, "4": 4, "6": 5}
            state.current_step = step_map[choice]
            return StepResult.BACK
        if choice == "5":
            # Proxy port — re-check on re-entering Summary
            return StepResult.BACK

        if choice == "c":
            # 1. Deploy code to workspace
            target_dir = _deploy_to_workspace(console, state)

            # 2. Install dependencies
            if not _install_deps(console, target_dir, state):
                return StepResult.BACK

            # 3. Setup service
            info = detect_platform()
            venv_python = state.venv_python or str(target_dir / ".venv" / "bin" / "python")
            proxy_script = str(target_dir / "memory_proxy.py")
            working_dir = str(target_dir)

            # Note: proxy port was already checked at the start of run()

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
                    status_cmd = setup.get("status_cmd", "launchctl list | grep lyumemory")
                    logs_cmd = setup.get("logs_cmd", "tail -f /tmp/lyumemory-proxy.log")

                elif info.os == OS.WINDOWS:
                    for cmd in setup.get("setup_cmds", []):
                        subprocess.run(cmd, shell=True, check=True)
                    status_cmd = setup.get("status_cmd", 'schtasks /query /tn "LyuMemoryProxy"')
                    logs_cmd = setup.get("logs_cmd", "Check proxy output in terminal")

                console.print(f"\n[bold green]✓ {S.t('service_ok')}[/bold green]")
                console.print(f"\n[bold]{S.t('service_status')}[/bold]")
                console.print(f"  {status_cmd}")
                console.print(f"\n[bold]{S.t('service_logs')}[/bold]")
                console.print(f"  {logs_cmd}")

            except subprocess.CalledProcessError as e:
                console.print(f"\n[red]{S.t('service_fail', err=e)}[/red]")
                return StepResult.BACK

            return StepResult.NEXT

        return StepResult.NEXT
