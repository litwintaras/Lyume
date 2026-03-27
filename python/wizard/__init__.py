"""Lyume wizard — first-run setup."""
from pathlib import Path
from wizard.engine import WizardEngine
from wizard.state import WizardState, should_run_wizard


def run_wizard(config_path: str) -> dict:
    """Run interactive setup wizard. Returns generated config."""
    engine = WizardEngine(config_path=config_path)
    return engine.run()


def generate_config(
    agent_name: str,
    user_name: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str = "",
    embed_provider: str = "http",
    embed_url: str = "",
    embed_model: str = "nomic-embed-text",
    embed_model_path: str = "",
    db_provider: str = "docker",
    db_host: str = "127.0.0.1",
    db_port: int = 5432,
    db_user: str = "postgres",
    db_password: str = "lyume",
    db_name: str = "",
) -> dict:
    """Generate a complete config.yaml dict from wizard inputs."""
    state = WizardState(
        agent_name=agent_name,
        user_name=user_name,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        embed_provider=embed_provider,
        embed_url=embed_url,
        embed_model=embed_model,
        embed_model_path=embed_model_path,
        db_provider=db_provider,
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
    )
    return state.generate_config()


def save_config(config: dict, path: str) -> None:
    """Write config dict to YAML file, stripping internal keys."""
    WizardState.save_config(config, path)


def save_identity(agent_name: str, user_name: str, directory: str) -> None:
    """Write IDENTITY.md and USER.md files."""
    WizardState.save_identity(agent_name, user_name, directory)


def detect_known_memory_paths() -> list[dict]:
    """Scan home directory for known AI agent memory locations.

    Returns list of dicts: {"name": "Claude Code", "path": Path(...)}
    """
    from pathlib import Path

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


__all__ = ["run_wizard", "should_run_wizard", "generate_config", "save_config", "save_identity", "detect_known_memory_paths", "Path"]
