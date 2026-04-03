from wizard.engine import BaseStep, StepResult
from rich.console import Console
from rich.prompt import Prompt, Confirm
from wizard.state import WizardState
from wizard import strings as S
import subprocess
import re
import time
import os
from pathlib import Path
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


class DatabaseStep(BaseStep):
    title = S.STEP_DATABASE

    def run(self, state: WizardState, console: Console) -> StepResult:
        if state.docker_available:
            console.print(S.t("db_docker_option"))
            console.print(S.t("db_external_option"))
            choice = Prompt.ask(S.t("db_choose"), choices=["1", "2", "b"], show_choices=False)

            if choice == "b":
                return StepResult.BACK
            elif choice == "1":
                target_port = _resolve_port(console, "127.0.0.1", 5432)
                if target_port is None:
                    return StepResult.BACK

                compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"

                # Detect compose command
                compose_cmd = None
                for cmd in [["docker", "compose"], ["docker-compose"]]:
                    try:
                        subprocess.run(cmd + ["version"], capture_output=True, check=True)
                        compose_cmd = cmd
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue

                if not compose_cmd:
                    console.print(S.t("db_compose_not_found"))
                    return StepResult.BACK

                try:
                    subprocess.run(
                        compose_cmd + ["-f", str(compose_path), "up", "-d", "db"],
                        check=True,
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
                    console.print(S.t("db_start_fail", err=e))
                    return StepResult.BACK

                state.db_provider = "docker"
                state.db_host = "127.0.0.1"
                state.db_port = target_port
                state.db_user = "postgres"
                state.db_password = "lyume"

            elif choice == "2":
                state.db_provider = "external"
                state.db_host = Prompt.ask(S.t("db_host"))
                state.db_port = int(Prompt.ask(S.t("db_port"), default="5432"))
                state.db_user = Prompt.ask(S.t("db_user"), default="postgres")
                state.db_password = Prompt.ask(S.t("db_password"), password=True)

        else:  # no docker
            console.print(S.t("db_no_docker"))
            state.db_provider = "external"
            state.db_host = Prompt.ask(S.t("db_host"))
            state.db_port = int(Prompt.ask(S.t("db_port"), default="5432"))
            state.db_user = Prompt.ask(S.t("db_user"), default="postgres")
            state.db_password = Prompt.ask(S.t("db_password"), password=True)

        # Generate db_name from openclaw identity name
        identity = state.openclaw_identity_name or state.openclaw_agent_id or state.agent_name
        normalized = re.sub(r"[^a-z0-9_]", "_", identity.lower()).strip("_")
        state.db_name = f"openclaw_{normalized}"

        return StepResult.NEXT
