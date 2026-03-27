import os
from pathlib import Path

import yaml


class _Section:
    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, _Section(v) if isinstance(v, dict) else v)

    def __getattr__(self, name):
        return _Section({})

    def __bool__(self):
        return bool(self.__dict__)

    def __repr__(self):
        return repr(self.__dict__)


def _migrate_config(data: dict) -> dict:
    """Migrate old config format to new generic format."""
    # lm_studio: → llm: (create llm from lm_studio)
    if "lm_studio" in data and "llm" not in data:
        old = data["lm_studio"]
        data["llm"] = {
            "url": old.get("url", ""),
            "api_key": old.get("api_key", ""),
            "model": old.get("model_name", ""),
            "request_timeout": old.get("request_timeout", 300),
        }
        # Keep lm_studio as-is for backward compat

    # If llm: exists but lm_studio: doesn't — create lm_studio alias
    if "llm" in data and "lm_studio" not in data:
        llm = data["llm"]
        data["lm_studio"] = {
            "url": llm.get("url", ""),
            "api_key": llm.get("api_key", ""),
            "model_name": llm.get("model", ""),
            "request_timeout": llm.get("request_timeout", 300),
            "reflection_timeout": llm.get("reflection_timeout", 120),
            "reflection_max_messages": llm.get("reflection_max_messages", 30),
        }

    # embedding: auto-detect provider
    emb = data.get("embedding", {})
    if "provider" not in emb:
        if emb.get("url"):
            emb["provider"] = "http"
        elif emb.get("model_path"):
            emb["provider"] = "local"

    # database: default provider
    db = data.get("database", {})
    if "provider" not in db:
        db["provider"] = "docker"

    # first_run default
    if "first_run" not in data:
        data["first_run"] = False

    return data


def _env_override(config: dict) -> dict:
    flat = {
        "LYUME_SERVER_HOST": ("server", "host"),
        "LYUME_SERVER_PORT": ("server", "port", int),
        "LYUME_SERVER_LOG_LEVEL": ("server", "log_level"),
        # New generic LLM keys
        "LYUME_LLM_URL": ("llm", "url"),
        "LYUME_LLM_API_KEY": ("llm", "api_key"),
        "LYUME_LLM_MODEL": ("llm", "model"),
        "LYUME_LLM_TIMEOUT": ("llm", "request_timeout", int),
        # Legacy keys (map to new llm section)
        "LYUME_LM_URL": ("llm", "url"),
        "LYUME_LM_API_KEY": ("llm", "api_key"),
        "LYUME_LM_MODEL": ("llm", "model"),
        "LYUME_LM_TIMEOUT": ("llm", "request_timeout", int),
        # Database
        "LYUME_DB_HOST": ("database", "host"),
        "LYUME_DB_PORT": ("database", "port", int),
        "LYUME_DB_USER": ("database", "user"),
        "LYUME_DB_PASSWORD": ("database", "password"),
        "LYUME_DB_NAME": ("database", "name"),
        # Embedding
        "LYUME_EMBED_PROVIDER": ("embedding", "provider"),
        "LYUME_EMBED_URL": ("embedding", "url"),
        "LYUME_EMBED_MODEL": ("embedding", "model"),
        "LYUME_EMBED_MODEL_PATH": ("embedding", "model_path"),
        "LYUME_EMBED_CTX": ("embedding", "n_ctx", int),
        "LYUME_EMBED_GPU": ("embedding", "n_gpu_layers", int),
    }
    for env_key, path in flat.items():
        val = os.environ.get(env_key)
        if val is not None:
            *keys, last = path if not callable(path[-1]) else path[:-1]
            cast = path[-1] if callable(path[-1]) else str
            d = config
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            section = keys[-1] if keys else last
            if keys:
                d.setdefault(section, {})[last] = cast(val)
            else:
                config[section] = cast(val)
    return config


def load_config() -> _Section:
    config_path = os.environ.get(
        "LYUME_CONFIG",
        str(Path(__file__).parent / "config.yaml"),
    )
    with open(config_path) as f:
        data = yaml.safe_load(f)
    data = _migrate_config(data)
    data = _env_override(data)
    return _Section(data)


cfg = load_config()
