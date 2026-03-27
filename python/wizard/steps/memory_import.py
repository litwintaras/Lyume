from wizard.engine import BaseStep, StepResult
from rich.console import Console
from rich.prompt import Prompt
from wizard.state import WizardState
from wizard import strings as S
from pathlib import Path
import glob
import os

KNOWN_MEMORY_PATHS = [
    ("Claude Code", ".claude/projects/*/memory/"),
    ("Cursor", ".cursor/rules/"),
    ("Cursor (legacy)", ".cursorrules"),
    ("Windsurf", ".windsurfrules.md"),
    ("Cline", ".clinerules/memory/"),
    ("GitHub Copilot", ".github/copilot-instructions.md"),
    ("OpenAI Codex", "AGENTS.md"),
    ("Gemini CLI", "GEMINI.md"),
    ("Aider", "CONVENTIONS.md"),
]


def detect_known_memory_paths(home_dir):
    results = []
    for name, pattern in KNOWN_MEMORY_PATHS:
        full_pattern = str(Path(home_dir) / pattern)
        matching_paths = glob.glob(full_pattern, recursive=True)
        if matching_paths:
            # Add the first match
            results.append((name, matching_paths[0]))
    return results


class MemoryImportStep(BaseStep):
    title = S.STEP_IMPORT

    def run(self, state: WizardState, console: Console) -> StepResult:
        home = Path.home()
        found_paths = detect_known_memory_paths(str(home))

        # Show options
        console.print(S.t("import_auto_scan"))
        console.print(S.t("import_enter_path"))
        console.print(S.t("import_skip"))

        choice = Prompt.ask(S.t("import_choose"), choices=["1", "2", "3", "b"], show_choices=False)

        if choice == "b":
            return StepResult.BACK

        if choice == "1":  # auto-scan
            if not found_paths:
                console.print(S.t("import_not_found"))
                state.import_paths = []
            else:
                console.print(S.t("import_found"))
                for name, path in found_paths:
                    console.print(f"  - {name}: {path}")
                state.import_paths = [path for name, path in found_paths]

        elif choice == "2":  # manual
            path_input = Prompt.ask(S.t("import_enter"))
            p = Path(path_input).expanduser()
            if p.exists():
                state.import_paths = [str(p)]
            else:
                console.print(f"[red]{S.t('import_path_missing')}[/red]")
                state.import_paths = []

        elif choice == "3":  # skip
            state.import_paths = []

        return StepResult.NEXT
