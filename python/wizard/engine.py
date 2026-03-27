"""Wizard engine — step navigation, checkpoint, progress."""
from enum import Enum
from pathlib import Path
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
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config_dir = str(Path(config_path).parent)
        self.checkpoint_path = Path(self.config_dir) / ".wizard_checkpoint.yaml"
        self.state = WizardState()
        self._steps: list[BaseStep] = []

    def register_steps(self, steps: list[BaseStep]):
        self._steps = steps
        for i, step in enumerate(self._steps):
            step.number = i

    def run(self) -> dict:
        from wizard.steps import all_steps
        self.register_steps(all_steps())

        # Check checkpoint
        if self.checkpoint_path.exists():
            console.print(f"\n{S.t('checkpoint_found')}")
            choice = Prompt.ask(S.t("checkpoint_continue"), choices=["y", "n"], default="y")
            if choice == "y":
                self.state = WizardState.load_checkpoint(self.checkpoint_path)
            else:
                self.state = WizardState()

        # Welcome
        console.print(Panel(
            f"[bold cyan]{S.t('welcome_title')}[/bold cyan]\n\n{S.t('welcome_body')}",
            title="Lyume",
            border_style="cyan",
        ))

        total = len(self._steps)
        idx = self.state.current_step

        while idx < total:
            step = self._steps[idx]
            # Progress bar
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
                self.state.save_checkpoint(self.checkpoint_path)
                console.print(f"\n[yellow]{S.t('restart_saved')}[/yellow]")
                raise SystemExit(0)
            else:
                idx += 1
                self.state.current_step = idx
                self.state.save_checkpoint(self.checkpoint_path)

        # Generate and save config
        config = self.state.generate_config()
        WizardState.save_config(config, self.config_path)
        WizardState.save_identity(self.state.agent_name, self.state.user_name, self.config_dir)

        # Cleanup checkpoint
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()

        config["_import_paths"] = self.state.import_paths
        return config
