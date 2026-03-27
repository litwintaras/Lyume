from wizard.engine import BaseStep, StepResult
from rich.console import Console
from wizard.state import WizardState
from wizard import strings as S
from wizard.platform import detect_platform, docker_install_instructions, compose_install_instructions
from rich.prompt import Prompt
import subprocess as _sp


def _check_compose() -> bool:
    """Check if Docker Compose plugin is available."""
    for cmd in [["docker", "compose", "version"], ["docker-compose", "version"]]:
        try:
            _sp.run(cmd, capture_output=True, check=True, timeout=5)
            return True
        except (_sp.CalledProcessError, FileNotFoundError, _sp.TimeoutExpired):
            continue
    return False


class DockerStep(BaseStep):
    title = S.STEP_DOCKER

    def run(self, state: WizardState, console: Console) -> StepResult:
        info = detect_platform()

        if info.docker_running:
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
                        # If it turned out Docker isn't actually installed, handle that case
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

        # Fallback (should not be reached in normal flow)
        return StepResult.NEXT
