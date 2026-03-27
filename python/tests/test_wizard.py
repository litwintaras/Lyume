import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


def test_generate_config_all_fields():
    """generate_config() produces dict with all required sections."""
    from wizard import generate_config

    config = generate_config(
        agent_name="TestBot",
        user_name="Taras",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
        llm_api_key="",
        embed_provider="http",
        embed_url="http://localhost:11434/v1",
        embed_model="nomic-embed-text",
        db_provider="docker",
        db_host="127.0.0.1",
        db_port=5432,
        db_user="postgres",
        db_password="lyume",
        db_name="ai_memory_testbot",
    )
    assert config["first_run"] is False
    assert config["llm"]["url"] == "http://localhost:11434/v1"
    assert config["llm"]["model"] == "llama3"
    assert config["llm"]["api_key"] == ""
    assert config["embedding"]["provider"] == "http"
    assert config["embedding"]["url"] == "http://localhost:11434/v1"
    assert config["embedding"]["model"] == "nomic-embed-text"
    assert config["database"]["provider"] == "docker"
    assert config["database"]["host"] == "127.0.0.1"
    assert config["database"]["port"] == 5432
    assert config["database"]["name"] == "ai_memory_testbot"
    assert config["_agent_name"] == "TestBot"
    assert config["_user_name"] == "Taras"


def test_generate_config_defaults():
    """generate_config() fills defaults for optional params."""
    from wizard import generate_config

    config = generate_config(
        agent_name="Lyume",
        user_name="User",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
    )
    assert config["embedding"]["provider"] == "http"
    assert config["database"]["provider"] == "docker"
    assert config["database"]["password"] == "lyume"
    assert config["memory"]["search_limit"] == 3
    assert config["lessons"]["elo_start"] == 50
    assert config["consolidation"]["enabled"] is True


def test_generate_config_local_embedding():
    """generate_config() with local embedding sets model_path."""
    from wizard import generate_config

    config = generate_config(
        agent_name="Lyume",
        user_name="User",
        llm_url="http://localhost:1234",
        llm_model="qwen",
        embed_provider="local",
        embed_model_path="/path/to/model.gguf",
    )
    assert config["embedding"]["provider"] == "local"
    assert config["embedding"]["model_path"] == "/path/to/model.gguf"


def test_detect_known_memory_paths_finds_claude():
    """detect_known_memory_paths() finds Claude Code memory directories."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        claude_dir = Path(d) / ".claude" / "projects" / "myproject" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "MEMORY.md").write_text("# Memory\n- test")

        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert len(paths) >= 1
            assert any("claude" in str(p).lower() for p in paths)


def test_detect_known_memory_paths_empty():
    """detect_known_memory_paths() returns empty list when nothing found."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert paths == []


def test_detect_known_memory_paths_finds_cursor():
    """detect_known_memory_paths() finds Cursor rules."""
    from wizard import detect_known_memory_paths

    with tempfile.TemporaryDirectory() as d:
        cursor_dir = Path(d) / ".cursor" / "rules"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "memory.mdc").write_text("rule: test")

        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert any("cursor" in str(p).lower() for p in paths)


def test_save_config():
    """save_config() writes valid YAML without internal keys."""
    import yaml
    from wizard import generate_config, save_config

    with tempfile.TemporaryDirectory() as d:
        config = generate_config(
            agent_name="Luna",
            user_name="Alex",
            llm_url="http://localhost:11434/v1",
            llm_model="llama3",
        )
        config_path = Path(d) / "config.yaml"
        save_config(config, str(config_path))

        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["llm"]["model"] == "llama3"
        assert loaded["first_run"] is False
        assert "_agent_name" not in loaded
        assert "_user_name" not in loaded


def test_save_identity():
    """save_identity() writes IDENTITY.md and USER.md."""
    from wizard import save_identity

    with tempfile.TemporaryDirectory() as d:
        save_identity("Luna", "Alex", d)

        identity = (Path(d) / "IDENTITY.md").read_text()
        assert "Luna" in identity

        user = (Path(d) / "USER.md").read_text()
        assert "Alex" in user


def test_wizard_triggers_on_first_run():
    """Wizard should be called when config doesn't exist."""
    from wizard import should_run_wizard

    assert should_run_wizard(config_path="/nonexistent/config.yaml") is True


def test_wizard_skips_when_configured():
    """Wizard should NOT run when config exists and first_run is False."""
    from wizard import should_run_wizard
    import yaml

    with tempfile.TemporaryDirectory() as d:
        config_path = Path(d) / "config.yaml"
        config_path.write_text("first_run: false\nllm:\n  url: http://localhost:1234\n")
        assert should_run_wizard(config_path=str(config_path)) is False


def test_wizard_triggers_when_first_run_true():
    """Wizard should run when config has first_run: true."""
    from wizard import should_run_wizard

    with tempfile.TemporaryDirectory() as d:
        config_path = Path(d) / "config.yaml"
        config_path.write_text("first_run: true\nllm:\n  url: http://localhost:1234\n")
        assert should_run_wizard(config_path=str(config_path)) is True
