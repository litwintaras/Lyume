import pytest
import yaml
import tempfile
import os
from config import load_config, _migrate_config


def _write_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f)


def test_migrate_old_lm_studio_to_llm():
    """Old lm_studio: section should create llm: with new keys."""
    old_config = {
        "lm_studio": {"url": "http://localhost:1234", "api_key": "sk-test", "model_name": "qwen"},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
        "embedding": {"model_path": "/fake", "n_ctx": 512, "n_gpu_layers": 0, "dimensions": 768},
    }
    migrated = _migrate_config(old_config)
    assert "llm" in migrated
    assert migrated["llm"]["url"] == "http://localhost:1234"
    assert migrated["llm"]["model"] == "qwen"


def test_migrate_keeps_lm_studio_as_alias():
    """After migration, lm_studio still accessible for backward compat."""
    old_config = {
        "lm_studio": {"url": "http://localhost:1234", "api_key": "sk-test", "model_name": "qwen", "request_timeout": 300, "reflection_timeout": 120, "reflection_max_messages": 30},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
        "embedding": {"model_path": "/fake", "n_ctx": 512, "n_gpu_layers": 0, "dimensions": 768},
    }
    migrated = _migrate_config(old_config)
    # lm_studio still present as alias
    assert "lm_studio" in migrated
    assert migrated["lm_studio"]["url"] == "http://localhost:1234"
    assert migrated["lm_studio"]["model_name"] == "qwen"


def test_new_llm_section_untouched():
    """New llm: section should pass through without changes."""
    new_config = {
        "llm": {"url": "http://localhost:11434/v1", "model": "llama3"},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
        "embedding": {"provider": "http", "url": "http://localhost:11434/v1", "model": "nomic"},
    }
    migrated = _migrate_config(new_config)
    assert migrated["llm"]["url"] == "http://localhost:11434/v1"
    assert migrated["llm"]["model"] == "llama3"


def test_new_llm_creates_lm_studio_alias():
    """If llm: exists but lm_studio: doesn't, create lm_studio alias."""
    new_config = {
        "llm": {"url": "http://localhost:11434/v1", "api_key": "sk-123", "model": "llama3", "request_timeout": 300},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
        "embedding": {"provider": "http", "url": "http://localhost:11434/v1", "model": "nomic"},
    }
    migrated = _migrate_config(new_config)
    assert "lm_studio" in migrated
    assert migrated["lm_studio"]["url"] == "http://localhost:11434/v1"
    assert migrated["lm_studio"]["model_name"] == "llama3"


def test_embedding_provider_defaults_to_local_if_model_path():
    """If embedding has model_path but no provider, default to 'local'."""
    config = {
        "llm": {"url": "http://localhost:1234/v1", "model": "test"},
        "embedding": {"model_path": "/some/model.gguf", "n_ctx": 512, "dimensions": 768},
    }
    migrated = _migrate_config(config)
    assert migrated["embedding"]["provider"] == "local"


def test_embedding_provider_defaults_to_http_if_url():
    """If embedding has url but no provider, default to 'http'."""
    config = {
        "llm": {"url": "http://localhost:1234/v1", "model": "test"},
        "embedding": {"url": "http://localhost:1234/v1", "model": "nomic"},
    }
    migrated = _migrate_config(config)
    assert migrated["embedding"]["provider"] == "http"


def test_env_override_new_keys():
    """ENV vars LYUME_LLM_URL and LYUME_LLM_MODEL override new config."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        yaml.dump({
            "llm": {"url": "http://old:1234/v1", "model": "old-model"},
            "server": {"host": "127.0.0.1", "port": 1235},
            "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
            "embedding": {"provider": "http", "url": "http://localhost:1234/v1", "model": "nomic"},
        }, f)
        path = f.name

    try:
        os.environ["LYUME_CONFIG"] = path
        os.environ["LYUME_LLM_URL"] = "http://new:5678/v1"
        os.environ["LYUME_LLM_MODEL"] = "new-model"
        cfg = load_config()
        assert cfg.llm.url == "http://new:5678/v1"
        assert cfg.llm.model == "new-model"
    finally:
        os.environ.pop("LYUME_CONFIG", None)
        os.environ.pop("LYUME_LLM_URL", None)
        os.environ.pop("LYUME_LLM_MODEL", None)
        os.unlink(path)
