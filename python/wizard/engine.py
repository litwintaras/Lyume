"""Wizard engine — step navigation, checkpoint, progress."""
from pathlib import Path
from enum import Enum
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from wizard.state import WizardState
from wizard import strings as S

console = Console()


class StepResult(Enum):
    NEXT = "next"
    BACK = "back"
    RESTART = "restart"


class BaseStep:
    title: str = ""
    number: int = 0

    def run(self, state: WizardState, console: Console) -> StepResult:
        raise NotImplementedError


class WizardEngine:
    def __init__(self):
        self.state = WizardState()
        self._steps: list[BaseStep] = []
        self._checkpoint_path: Path | None = None

    def _resolve_paths(self):
        """Resolve config and checkpoint paths from openclaw_workspace."""
        if self.state.openclaw_workspace:
            target = Path(self.state.openclaw_workspace) / "lyumemory"
            target.mkdir(parents=True, exist_ok=True)
            self.config_path = str(target / "config.yaml")
            self._checkpoint_path = target / ".wizard_checkpoint.yaml"
        else:
            self.config_path = str(Path.cwd() / "python" / "config.yaml")
            self._checkpoint_path = Path.cwd() / ".wizard_checkpoint.yaml"

    def register_steps(self, steps: list[BaseStep]):
        self._steps = steps
        for i, step in enumerate(self._steps):
            step.number = i

    def run(self) -> dict:
        from wizard.steps import all_steps
        self.register_steps(all_steps())

        # Check for existing checkpoint in default location
        default_cp = Path.home() / ".cache" / "lyumemory" / ".wizard_checkpoint.yaml"
        if default_cp.exists():
            console.print(f"\n{S.t('checkpoint_found')}")
            choice = Prompt.ask(S.t("checkpoint_continue"), choices=["y", "n"], default="y")
            if choice == "y":
                self.state = WizardState.load_checkpoint(default_cp)
                self._resolve_paths()
            else:
                self.state = WizardState()

        # Welcome
        console.print(Panel(
            f"[bold cyan]{S.t('welcome_title')}[/bold cyan]\n\n{S.t('welcome_body')}",
            title="LyuMemory",
            border_style="cyan",
        ))

        total = len(self._steps)
        idx = self.state.current_step

        while idx < total:
            step = self._steps[idx]
            filled = idx
            empty = total - idx
            bar = "■" * filled + "□" * empty
            console.print(f"\n[dim][{bar}] {S.t('step_progress', current=idx+1, total=total, title=step.title)}[/dim]")

            result = step.run(self.state, console)

            if result == StepResult.BACK:
                if self.state.current_step < idx:
                    idx = self.state.current_step
                elif idx > 0:
                    idx -= 1
                continue
            elif result == StepResult.RESTART:
                self.state.current_step = idx
                self._save_checkpoint()
                console.print(f"\n[yellow]{S.t('restart_saved')}[/yellow]")
                raise SystemExit(0)
            else:
                # After step 0 (OpenClaw), resolve paths
                if idx == 0:
                    self._resolve_paths()
                idx += 1
                self.state.current_step = idx
                self._save_checkpoint()

        # Generate and save config
        self._resolve_paths()
        config = self.state.generate_config()
        WizardState.save_config(config, self.config_path)

        # Cleanup checkpoint
        if self._checkpoint_path and self._checkpoint_path.exists():
            self._checkpoint_path.unlink()

        config["_import_paths"] = self.state.import_paths
        return config

    def _save_checkpoint(self):
        """Save checkpoint — use workspace path if available, otherwise cache dir."""
        if self._checkpoint_path:
            self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self.state.save_checkpoint(self._checkpoint_path)
        else:
            cp = Path.home() / ".cache" / "lyumemory" / ".wizard_checkpoint.yaml"
            cp.parent.mkdir(parents=True, exist_ok=True)
            self.state.save_checkpoint(cp)
