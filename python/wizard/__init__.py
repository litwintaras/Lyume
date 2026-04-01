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


def generate_config(agent_name="Lyume", user_name="User", llm_url="http://127.0.0.1:1234/v1",
                    llm_model="qwen", embed_provider="http",
                    embed_url=None, embed_model=None, db_provider="docker", **kwargs):
    """Backward-compatible config generation from wizard."""
    from wizard.state import WizardState
    state = WizardState(
        agent_name=agent_name,
        user_name=user_name,
        llm_url=llm_url,
        llm_model=llm_model,
        embed_provider=embed_provider,
        embed_url=embed_url or llm_url,
        embed_model=embed_model or "nomic-embed-text",
        db_provider=db_provider,
        **kwargs
    )
    return state.generate_config()


def save_config(config, path):
    """Backward-compatible config save."""
    WizardState.save_config(config, path)


def save_identity(agent_name: str, user_name: str, directory: str):
    """Backward-compatible identity save."""
    WizardState.save_identity(agent_name, user_name, directory)


__all__ = ["run_wizard", "should_run_wizard", "detect_known_memory_paths", "generate_config", "save_config", "save_identity"]
