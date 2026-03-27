"""Integration tests — verify Phase 2 components work together."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from llm_client import LLMClient
from embedding_client import HTTPEmbeddingClient, create_embedding_client
from memory_import import scan_markdown_files, parse_blocks, ImportPipeline
from wizard import generate_config, detect_known_memory_paths, save_config
from config import _migrate_config


def test_old_config_migrates_and_clients_init():
    """Old lm_studio config migrates and LLMClient can be created from it."""
    old = {
        "lm_studio": {
            "url": "http://localhost:1234",
            "api_key": "sk-test",
            "model_name": "qwen",
        },
        "embedding": {"model_path": "/fake/model.gguf", "n_ctx": 512, "dimensions": 768},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
    }
    config = _migrate_config(old)

    llm = LLMClient(
        url=config["llm"]["url"],
        api_key=config["llm"]["api_key"],
        model=config["llm"]["model"],
    )
    assert llm.url == "http://localhost:1234"
    assert llm.model == "qwen"
    assert config["embedding"]["provider"] == "local"


def test_wizard_config_creates_valid_clients():
    """Wizard-generated config can create LLMClient and HTTPEmbeddingClient."""
    config = generate_config(
        agent_name="TestBot",
        user_name="Tester",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
        embed_provider="http",
        embed_url="http://localhost:11434/v1",
        embed_model="nomic-embed-text",
        db_provider="docker",
    )

    llm = LLMClient(url=config["llm"]["url"], model=config["llm"]["model"])
    assert llm.model == "llama3"

    embed = HTTPEmbeddingClient(url=config["embedding"]["url"], model=config["embedding"]["model"])
    assert embed.model == "nomic-embed-text"


def test_wizard_config_roundtrip(tmp_path):
    """Config survives generate → save → load cycle."""
    import yaml

    config = generate_config(
        agent_name="RoundTrip",
        user_name="Test",
        llm_url="http://localhost:1234",
        llm_model="model-x",
    )
    config_path = tmp_path / "config.yaml"
    save_config(config, str(config_path))

    loaded = yaml.safe_load(config_path.read_text())
    assert loaded["llm"]["model"] == "model-x"
    assert loaded["database"]["name"] == "ai_memory_roundtrip"
    assert loaded["first_run"] is False
    assert "_agent_name" not in loaded


@pytest.mark.asyncio
async def test_import_pipeline_end_to_end():
    """Full import: scan → parse → embed → dedup → save."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "memory.md").write_text(
            "## Preferences\n\nUser prefers dark theme and vim keybindings.\n\n"
            "## Skills\n\nUser knows Python and TypeScript well."
        )

        files = scan_markdown_files(d)
        assert len(files) == 1

        content = files[0].read_text()
        blocks = parse_blocks(content)
        assert len(blocks) == 2

        mock_mm = AsyncMock()
        mock_mm.search_semantic = AsyncMock(return_value=[])
        mock_mm.save_semantic = AsyncMock()

        mock_embed = AsyncMock()
        mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

        pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)
        stats = await pipeline.import_directory(d)

        assert stats["imported"] == 2
        assert stats["duplicate"] == 0
        assert mock_mm.save_semantic.call_count == 2
