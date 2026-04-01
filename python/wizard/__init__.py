"""LyuMemory wizard — first-run setup."""
from pathlib import Path
from wizard.engine import WizardEngine
from wizard.state import WizardState, should_run_wizard


def run_wizard() -> dict:
    """Run interactive setup wizard. Returns generated config."""
    engine = WizardEngine()
    return engine.run()


def detect_known_memory_paths() -> list[dict]:
    """Scan home directory for known AI agent memory locations."""
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

    home = Path.home()
    found = []
    for name, pattern in KNOWN_MEMORY_PATHS:
        matches = list(home.glob(pattern))
        for m in matches:
            if m.is_dir():
                has_files = any(m.glob("*.md")) or any(m.glob("*.mdc"))
                if has_files:
                    found.append({"name": name, "path": m})
            elif m.is_file() and m.stat().st_size > 0:
                found.append({"name": name, "path": m.parent})
    return found


__all__ = ["run_wizard", "should_run_wizard", "detect_known_memory_paths"]
