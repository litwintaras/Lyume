"""Wizard state management + checkpoint."""
import re
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class WizardState:
    # Identity
    agent_name: str = "Lyume"
    user_name: str = "User"
    # Backend
    backend_name: str = ""
    llm_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    # Embedding
    embed_provider: str = "http"
    embed_url: str = ""
    embed_model: str = ""
    embed_model_path: str = ""
    embed_dimensions: int = 768
    # Docker
    docker_available: bool = False
    # Database
    db_provider: str = "docker"
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "lyume"
    db_name: str = ""
    # Import
    import_paths: list = field(default_factory=list)
    # Engine state
    current_step: int = 0
    # Post-confirm
    proxy_port: int = 1235
    venv_python: str = ""

    def save_checkpoint(self, path: Path):
        path.write_text(yaml.dump(asdict(self), default_flow_style=False))

    @classmethod
    def load_checkpoint(cls, path: Path) -> "WizardState":
        data = yaml.safe_load(path.read_text())
        return cls(**data)

    def generate_config(self) -> dict:
        """Generate config.yaml dict from wizard state."""
        normalized = re.sub(r"[^a-z0-9_]", "_", self.agent_name.lower()).strip("_")
        db_name = self.db_name or f"ai_memory_{normalized}"

        config = {
            "first_run": False,
            "_agent_name": self.agent_name,
            "_user_name": self.user_name,
            "server": {"host": "127.0.0.1", "port": self.proxy_port, "log_level": "info"},
            "llm": {
                "url": self.llm_url,
                "api_key": self.llm_api_key,
                "model": self.llm_model,
                "request_timeout": 300,
                "reflection_timeout": 120,
                "reflection_max_messages": 30,
            },
            "database": {
                "provider": self.db_provider,
                "host": self.db_host,
                "port": self.db_port,
                "user": self.db_user,
                "password": self.db_password,
                "name": db_name,
                "pool_min": 1,
                "pool_max": 5,
            },
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
            },
            "lessons": {
                "search_limit": 3,
                "similarity_threshold": 0.70,
                "elo_start": 50,
                "elo_implicit_delta": 5,
                "elo_explicit_delta": 10,
                "elo_floor": 20,
                "elo_deactivate_days": 30,
            },
            "features": {
                "strip_think_tags": True,
                "marker_fallback": True,
                "session_summary": True,
                "summary_interval": 20,
                "session_timeout": 1800,
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

        if self.embed_provider == "local":
            config["embedding"] = {
                "provider": "local",
                "model_path": self.embed_model_path,
                "n_ctx": 512,
                "n_gpu_layers": 0,
                "dimensions": self.embed_dimensions,
            }
        else:
            config["embedding"] = {
                "provider": "http",
                "url": self.embed_url or self.llm_url,
                "model": self.embed_model,
                "dimensions": self.embed_dimensions,
            }

        return config

    @staticmethod
    def save_config(config: dict, path: str):
        """Write config dict to YAML file, stripping internal keys."""
        clean = {k: v for k, v in config.items() if not k.startswith("_")}
        Path(path).write_text(yaml.dump(clean, default_flow_style=False, sort_keys=False))

    @staticmethod
    def save_identity(agent_name: str, user_name: str, directory: str):
        """Write IDENTITY.md and USER.md files."""
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / "IDENTITY.md").write_text(f"Name: {agent_name}\nRole: Memory companion\n")
        (d / "USER.md").write_text(f"{user_name}\n")


def should_run_wizard(config_path: str) -> bool:
    """Check if wizard should run: no config file or first_run: true."""
    p = Path(config_path)
    if not p.exists():
        return True
    try:
        data = yaml.safe_load(p.read_text())
        return data.get("first_run", True) is True
    except Exception:
        return True
