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


_DEFAULTS = {
    "memory": {
        "search_limit": 3,
        "similarity_threshold": 0.3,
        "dedup_similarity": 0.9,
        "save_max_chars": 300,
        "dedup_ttl": 5,
        "hybrid_search": True,
        "hybrid_rrf_k": 60,
        "hybrid_bm25_limit": 10,
        "proactive_high_similarity": 0.85,
        "proactive_dormant_days": 30,
        "summary_similarity": 0.8,
        "dormant_hint_similarity": 0.6,
        "overlap_threshold": 0.5,
        "happy_search_threshold": 0.4,
        "archive_similarity": 0.85,
    },
    "lessons": {
        "search_limit": 3,
        "similarity_threshold": 0.7,
        "elo_start": 50,
        "elo_implicit_delta": 5,
        "elo_explicit_delta": 10,
        "elo_floor": 20,
        "elo_deactivate_days": 30,
        "active_similarity": 0.85,
    },
    "features": {
        "strip_think_tags": True,
        "marker_fallback": True,
        "session_summary": True,
        "summary_interval": 20,
        "session_timeout": 1800,
        "summary_buffer_cap": 60,
        "summary_max_context": 30,
        "conversation_buffer": True,
        "buffer_max_entries": 200,
        "buffer_weight_cutoff": 0.05,
        "buffer_max_inject": 15,
        "buffer_max_chars": 500,
        "buffer_decay_power": 0.5,
    },
    "consolidation": {
        "enabled": True,
        "schedule": "03:00",
        "semantic_threshold": 0.85,
        "lesson_threshold": 0.85,
        "cooldown_days": 180,
        "stale_days": 365,
    },
}


def _apply_defaults(data: dict) -> dict:
    """Merge defaults into config — only fills missing keys."""
    for section, defaults in _DEFAULTS.items():
        if section not in data:
            data[section] = {}
        for key, value in defaults.items():
            if key not in data[section]:
                data[section][key] = value
    return data


def load_config() -> _Section:
    config_path = os.environ.get(
        "LYUME_CONFIG",
        str(Path(__file__).parent / "config.yaml"),
    )
    with open(config_path) as f:
        data = yaml.safe_load(f)
    data = _migrate_config(data)
    data = _env_override(data)
    data = _apply_defaults(data)
    return _Section(data)


cfg = load_config()
