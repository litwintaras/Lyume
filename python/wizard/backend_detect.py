"""Auto-detect running LLM backends."""
import asyncio
from dataclasses import dataclass

import httpx


KNOWN_BACKENDS = [
    ("LM Studio", "http://127.0.0.1:1234/v1"),
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("llama.cpp", "http://127.0.0.1:8080/v1"),
]

EMBEDDING_PATTERNS = ("embed", "nomic", "bge", "e5", "gte", "minilm")


@dataclass
class BackendInfo:
    name: str
    url: str
    models: list[str]


async def _check_backend(name: str, base_url: str, timeout: float) -> BackendInfo | None:
    """Check if a backend is running and list its models."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/models")
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return BackendInfo(name=name, url=base_url, models=models)
    except Exception:
        pass
    return None


async def scan_backends(timeout: float = 2.0) -> list[BackendInfo]:
    """Scan known ports for running LLM backends."""
    tasks = [_check_backend(name, url, timeout) for name, url in KNOWN_BACKENDS]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def filter_embedding_models(models: list[str]) -> list[str]:
    """Filter model list to likely embedding models."""
    return [m for m in models if any(p in m.lower() for p in EMBEDDING_PATTERNS)]


def filter_llm_models(models: list[str]) -> list[str]:
    """Filter model list to likely LLM models (exclude embedding)."""
    return [m for m in models if not any(p in m.lower() for p in EMBEDDING_PATTERNS)]
