"""Step 0: OpenClaw agent selection."""
import json
import shutil
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from wizard.engine import BaseStep, StepResult
from wizard.state import WizardState
from wizard import strings as S


def parse_agents_json(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


class OpenClawAgentStep(BaseStep):
    title = S.STEP_OPENCLAW

    def run(self, state: WizardState, console: Console) -> StepResult:
        console.print(Panel(
            S.t("openclaw_prerequisite"),
            border_style="yellow",
        ))

        openclaw = shutil.which("openclaw")
        if not openclaw:
            console.print(f"[red]{S.t('openclaw_cli_missing')}[/red]")
            return StepResult.RESTART

        console.print(S.t("openclaw_scanning"))
        try:
            result = subprocess.run(
                [openclaw, "agents", "list", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            agents = parse_agents_json(result.stdout)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            console.print(f"[red]{S.t('openclaw_list_fail', err=str(e))}[/red]")
            return StepResult.RESTART

        if not agents:
            console.print(f"[red]{S.t('openclaw_no_agents')}[/red]")
            return StepResult.RESTART

        console.print(f"\n[bold]{S.t('openclaw_agents_found')}[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="bold", width=3)
        table.add_column("ID")
        table.add_column("Workspace")
        table.add_column("Model")
        for i, agent in enumerate(agents, 1):
            default_marker = " ★" if agent.get("isDefault") else ""
            table.add_row(
                str(i),
                f"{agent['id']}{default_marker}",
                agent.get("workspace", "—"),
                agent.get("model", "—"),
            )
        console.print(table)

        choice = Prompt.ask(S.t("openclaw_pick_agent", n=len(agents)))

        if choice.lower() == "q":
            return StepResult.RESTART

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                selected = agents[idx]
                state.openclaw_agent_id = selected["id"]
                state.openclaw_workspace = selected.get("workspace", "")
                state.openclaw_identity_name = selected.get("identityName", "")
                state.agent_name = selected.get("identityName", "") or selected["id"]
                state.user_name = state.user_name or "User"
                console.print(f"[green]✓ {S.t('openclaw_selected', name=selected['id'], workspace=state.openclaw_workspace)}[/green]")
                return StepResult.NEXT
        except (ValueError, IndexError):
            pass

        console.print("[red]Invalid choice[/red]")
        return StepResult.BACK
