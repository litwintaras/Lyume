# Phase 2: Generic Agent Pack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lyume Memory Proxy model-agnostic with one-click first start, memory import, and no hard dependency on LM Studio or llama-cpp-python.

**Architecture:** Config-driven with auto-detection. Single `config.yaml` as source of truth. TUI wizard fills it on first run. Two new abstraction layers: `LLMClient` (chat completions) and `EmbeddingClient` (HTTP + local fallback). Existing proxy, manager, consolidator refactored to use these clients.

**Tech Stack:** Python 3.12, FastAPI, httpx, asyncpg, pgvector, textual (TUI), uv (package manager)

**Spec:** `docs/superpowers/specs/2026-03-26-generic-agent-pack-design.md`

---

## Task 1: LLMClient — Generic LLM Abstraction

**Files:**
- Create: `python/llm_client.py`
- Create: `python/tests/test_llm_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_llm_client.py
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from llm_client import LLMClient


@pytest.mark.asyncio
async def test_complete_returns_content():
    """LLMClient.complete() returns assistant message content."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello world"}}]
    }

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:1234/v1", model="test-model")
        result = await client.complete([{"role": "user", "content": "Hi"}])
        assert result == "Hello world"


@pytest.mark.asyncio
async def test_complete_uses_correct_url():
    """LLMClient posts to {url}/chat/completions."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:1234/v1", model="test-model")
        await client.complete([{"role": "user", "content": "Hi"}])

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:1234/v1/chat/completions"


@pytest.mark.asyncio
async def test_complete_with_api_key():
    """LLMClient includes Authorization header when api_key provided."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:1234/v1", api_key="sk-test", model="test-model")
        await client.complete([{"role": "user", "content": "Hi"}])

        call_args = mock_client.post.call_args
        headers = call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer sk-test"


@pytest.mark.asyncio
async def test_is_available_true():
    """is_available() returns True when endpoint responds."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:1234/v1", model="test-model")
        assert await client.is_available() is True


@pytest.mark.asyncio
async def test_is_available_false():
    """is_available() returns False when endpoint unreachable."""
    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:9999/v1", model="test-model")
        assert await client.is_available() is False


@pytest.mark.asyncio
async def test_list_models():
    """list_models() returns model IDs from /models endpoint."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"id": "model-a"}, {"id": "model-b"}]
    }

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = LLMClient(url="http://localhost:1234/v1", model="test-model")
        models = await client.list_models()
        assert models == ["model-a", "model-b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_llm_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm_client'`

- [ ] **Step 3: Write LLMClient implementation**

```python
# python/llm_client.py
"""Generic LLM client — works with any OpenAI-compatible endpoint."""

import httpx


class LLMClient:
    """Async client for OpenAI-compatible /v1/chat/completions."""

    def __init__(self, url: str, api_key: str = "", model: str = "", timeout: int = 300):
        # Normalize: strip trailing slash
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> str:
        """Send chat completion request, return assistant content."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def complete_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        """Streaming chat completion — yields raw SSE lines."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    yield line

    async def is_available(self) -> bool:
        """Check if LLM endpoint is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.url}/models", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Get list of available model IDs."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.url}/models", headers=self._headers())
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_llm_client.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/llm_client.py python/tests/test_llm_client.py
git commit -m "feat: add LLMClient — generic OpenAI-compatible LLM abstraction"
```

---

## Task 2: EmbeddingClient — HTTP + Local Fallback

**Files:**
- Create: `python/embedding_client.py`
- Create: `python/tests/test_embedding_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_embedding_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from embedding_client import HTTPEmbeddingClient, LocalEmbeddingClient, create_embedding_client


@pytest.mark.asyncio
async def test_http_embed_returns_vector():
    """HTTPEmbeddingClient.embed() returns float list from /v1/embeddings."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }

    with patch("embedding_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = HTTPEmbeddingClient(url="http://localhost:1234/v1", model="nomic-embed-text")
        result = await client.embed("hello")
        assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_http_embed_sends_correct_payload():
    """HTTPEmbeddingClient sends model and input in request body."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1]}]
    }

    with patch("embedding_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        client = HTTPEmbeddingClient(url="http://localhost:1234/v1", model="nomic-embed-text")
        await client.embed("test text")

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["model"] == "nomic-embed-text"
        assert payload["input"] == "test text"


def test_local_embed_returns_vector():
    """LocalEmbeddingClient.embed() wraps llama-cpp Llama.embed()."""
    mock_llama = MagicMock()
    mock_llama.embed.return_value = [[0.4, 0.5, 0.6]]

    with patch("embedding_client.Llama", return_value=mock_llama):
        client = LocalEmbeddingClient(model_path="/fake/model.gguf")
        # Force init
        client._model = mock_llama
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(client.embed("hello"))
        assert result == [0.4, 0.5, 0.6]


def test_create_embedding_client_http():
    """create_embedding_client('http', ...) returns HTTPEmbeddingClient."""
    client = create_embedding_client(provider="http", url="http://localhost:1234/v1", model="nomic")
    assert isinstance(client, HTTPEmbeddingClient)


def test_create_embedding_client_local():
    """create_embedding_client('local', ...) returns LocalEmbeddingClient."""
    with patch("embedding_client.Llama"):
        client = create_embedding_client(provider="local", model_path="/fake/model.gguf")
        assert isinstance(client, LocalEmbeddingClient)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_embedding_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'embedding_client'`

- [ ] **Step 3: Write EmbeddingClient implementation**

```python
# python/embedding_client.py
"""Embedding abstraction — HTTP endpoint or local llama-cpp fallback."""

import asyncio

import httpx


class HTTPEmbeddingClient:
    """Sends embedding requests to OpenAI-compatible /v1/embeddings endpoint."""

    def __init__(self, url: str, api_key: str = "", model: str = "nomic-embed-text", timeout: int = 60):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def embed(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.url}/embeddings",
                headers=self._headers(),
                json={"model": self.model, "input": text},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]


class LocalEmbeddingClient:
    """Local embedding via llama-cpp-python (CPU). Fallback when no HTTP endpoint."""

    def __init__(self, model_path: str, n_ctx: int = 512, n_gpu_layers: int = 0, dimensions: int = 768):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.dimensions = dimensions
        self._model = None

    def _get_model(self):
        if self._model is None:
            from llama_cpp import Llama
            self._model = Llama(
                model_path=self.model_path,
                embedding=True,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False,
            )
        return self._model

    def _embed_sync(self, text: str) -> list[float]:
        model = self._get_model()
        result = model.embed(text)
        if isinstance(result[0], list):
            return result[0]
        return result

    async def embed(self, text: str) -> list[float]:
        """Get embedding — runs CPU-bound work in thread."""
        return await asyncio.to_thread(self._embed_sync, text)


# Lazy import guard — llama_cpp only needed for local provider
try:
    from llama_cpp import Llama
except ImportError:
    Llama = None


def create_embedding_client(
    provider: str = "http",
    url: str = "",
    api_key: str = "",
    model: str = "nomic-embed-text",
    model_path: str = "",
    n_ctx: int = 512,
    n_gpu_layers: int = 0,
    dimensions: int = 768,
):
    """Factory: create embedding client based on provider type."""
    if provider == "http":
        return HTTPEmbeddingClient(url=url, api_key=api_key, model=model)
    elif provider == "local":
        if Llama is None:
            raise ImportError(
                "llama-cpp-python is required for local embeddings. "
                "Install with: uv pip install llama-cpp-python"
            )
        return LocalEmbeddingClient(
            model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, dimensions=dimensions,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_embedding_client.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/embedding_client.py python/tests/test_embedding_client.py
git commit -m "feat: add EmbeddingClient — HTTP + local llama-cpp fallback"
```

---

## Task 3: Config Migration — `lm_studio:` → `llm:`

**Files:**
- Modify: `python/config.py`
- Modify: `python/config.yaml`
- Create: `python/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_config.py
import pytest
import yaml
import tempfile
import os
from config import load_config, _migrate_config


def _write_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f)


def test_migrate_old_lm_studio_to_llm():
    """Old lm_studio: section should be renamed to llm: on load."""
    old_config = {
        "lm_studio": {"url": "http://localhost:1234", "api_key": "sk-test", "model_name": "qwen"},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
        "embedding": {"model_path": "/fake", "n_ctx": 512, "n_gpu_layers": 0, "dimensions": 768},
    }
    migrated = _migrate_config(old_config)
    assert "llm" in migrated
    assert "lm_studio" not in migrated
    assert migrated["llm"]["url"] == "http://localhost:1234"
    assert migrated["llm"]["model"] == "qwen"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name '_migrate_config'`

- [ ] **Step 3: Update config.py**

```python
# python/config.py
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
    # lm_studio: → llm:
    if "lm_studio" in data and "llm" not in data:
        old = data.pop("lm_studio")
        data["llm"] = {
            "url": old.get("url", ""),
            "api_key": old.get("api_key", ""),
            "model": old.get("model_name", ""),
            "request_timeout": old.get("request_timeout", 300),
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
        data["first_run"] = False  # existing installs skip wizard

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
        # Legacy keys (map to new)
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
```

- [ ] **Step 4: Update config.yaml to new format**

```yaml
# python/config.yaml
first_run: false

server:
  host: "127.0.0.1"
  port: 1235
  log_level: "info"

llm:
  url: "http://127.0.0.1:1234"
  api_key: "sk-lm-5tKh17ku:8qr1BzyIhHjH5HYBHy7N"
  model: "qwen3.5-35b-a3b"
  request_timeout: 300
  reflection_timeout: 120
  reflection_max_messages: 30

database:
  provider: "external"
  host: "127.0.0.1"
  port: 5432
  user: "postgres"
  name: "ai_memory"
  pool_min: 1
  pool_max: 5

embedding:
  provider: "local"
  model_path: "/home/tarik/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf"
  n_ctx: 512
  n_gpu_layers: 0
  dimensions: 768

memory:
  search_limit: 3
  similarity_threshold: 0.3
  dedup_similarity: 0.9
  save_max_chars: 300
  dedup_ttl: 5
  proactive_high_similarity: 0.85
  proactive_dormant_days: 7
  summary_similarity: 0.8
  dormant_hint_similarity: 0.5
  overlap_threshold: 0.4
  happy_search_threshold: 0.2
  archive_similarity: 0.7
  hybrid_search: true
  hybrid_rrf_k: 60
  hybrid_bm25_limit: 10

lessons:
  search_limit: 3
  similarity_threshold: 0.70
  active_similarity: 0.85
  elo_start: 50
  elo_implicit_delta: 5
  elo_explicit_delta: 10
  elo_floor: 20
  elo_deactivate_days: 30

features:
  strip_think_tags: true
  marker_fallback: true
  session_summary: true
  summary_interval: 20
  summary_max_context: 30
  summary_buffer_cap: 60
  session_timeout: 1800

consolidation:
  enabled: true
  schedule: "03:00"
  semantic_threshold: 0.85
  lesson_threshold: 0.85
  cooldown_days: 180
  stale_days: 365
  log_file: "consolidation.log"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 6: Run ALL existing tests to check backward compat**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/ -v`
Expected: All tests pass (some may need `cfg.lm_studio` → `cfg.llm` fixes — handle in Task 5)

- [ ] **Step 7: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/config.py python/config.yaml python/tests/test_config.py
git commit -m "feat: migrate config from lm_studio to generic llm section"
```

---

## Task 4: Database Init — `init.sql`

**Files:**
- Create: `python/migrations/init.sql`
- Modify: `python/memory_manager.py:81-146` (connect method)

- [ ] **Step 1: Write init.sql**

```sql
-- python/migrations/init.sql
-- First-run schema creation. Runs once if tables don't exist.

CREATE EXTENSION IF NOT EXISTS vector;

-- Semantic memories
CREATE TABLE IF NOT EXISTS memories_semantic (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    concept_name TEXT DEFAULT '',
    category TEXT DEFAULT 'general',
    keywords TEXT[] DEFAULT '{}',
    embedding vector(768),
    source_info JSONB DEFAULT '{}',
    emotional_context TEXT DEFAULT '',
    archived BOOLEAN DEFAULT FALSE,
    recall_count INTEGER DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    merged_into UUID REFERENCES memories_semantic(id) ON DELETE SET NULL,
    search_vector tsvector,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_updated TIMESTAMPTZ DEFAULT now()
);

-- Lessons (procedural memory)
CREATE TABLE IF NOT EXISTS lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_context TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    is_active BOOLEAN DEFAULT TRUE,
    recall_count INTEGER DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    merged_into UUID REFERENCES lessons(id) ON DELETE SET NULL,
    elo_rating REAL DEFAULT 50.0,
    last_elo_change TIMESTAMPTZ DEFAULT now(),
    elo_floor_since TIMESTAMPTZ,
    search_vector tsvector,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_updated TIMESTAMPTZ DEFAULT now()
);

-- Full-text search triggers
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.triggers WHERE trigger_name = 'memories_search_vector_update') THEN
        CREATE TRIGGER memories_search_vector_update
        BEFORE INSERT OR UPDATE ON memories_semantic
        FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.triggers WHERE trigger_name = 'lessons_search_vector_update') THEN
        CREATE TRIGGER lessons_search_vector_update
        BEFORE INSERT OR UPDATE ON lessons
        FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories_semantic USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS memories_search_vector_idx ON memories_semantic USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS lessons_embedding_idx ON lessons USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS lessons_search_vector_idx ON lessons USING GIN(search_vector);
```

- [ ] **Step 2: Update memory_manager.py connect() to use init.sql**

Replace `memory_manager.py:81-146` (the entire `connect` method body after pool creation) with:

```python
    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(**DB_CONFIG, min_size=cfg.database.pool_min, max_size=cfg.database.pool_max)
            async with self.pool.acquire() as conn:
                # Check if tables exist — if not, run init.sql
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'memories_semantic')"
                )
                if not exists:
                    init_sql = (pathlib.Path(__file__).parent / "migrations" / "init.sql").read_text()
                    await conn.execute(init_sql)
                else:
                    # Run incremental migrations for existing DBs
                    # Migration: merged_into columns
                    await conn.execute("""
                        DO $$ BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'memories_semantic' AND column_name = 'merged_into'
                            ) THEN
                                ALTER TABLE memories_semantic
                                ADD merged_into UUID NULL REFERENCES memories_semantic(id) ON DELETE SET NULL;
                            END IF;
                        END $$;
                    """)
                    await conn.execute("""
                        DO $$ BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'lessons' AND column_name = 'merged_into'
                            ) THEN
                                ALTER TABLE lessons
                                ADD merged_into UUID NULL REFERENCES lessons(id) ON DELETE SET NULL;
                            END IF;
                        END $$;
                    """)
                    # Migration: search_vector
                    await conn.execute("""
                        DO $$ BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name='memories_semantic' AND column_name='search_vector'
                            ) THEN
                                ALTER TABLE memories_semantic ADD COLUMN search_vector tsvector;
                                UPDATE memories_semantic SET search_vector = to_tsvector('simple', coalesce(content, ''));
                            END IF;

                            CREATE OR REPLACE FUNCTION update_search_vector()
                            RETURNS trigger AS $fn$
                            BEGIN
                                NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
                                RETURN NEW;
                            END;
                            $fn$ LANGUAGE plpgsql;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.triggers
                                WHERE trigger_name = 'memories_search_vector_update'
                            ) THEN
                                CREATE TRIGGER memories_search_vector_update
                                BEFORE INSERT OR UPDATE ON memories_semantic
                                FOR EACH ROW EXECUTE FUNCTION update_search_vector();
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM pg_indexes
                                WHERE tablename = 'memories_semantic' AND indexname = 'memories_search_vector_idx'
                            ) THEN
                                CREATE INDEX memories_search_vector_idx ON memories_semantic USING GIN(search_vector);
                            END IF;
                        END $$;
                    """)
                    # Migration 004: ELO
                    migration_004 = (pathlib.Path(__file__).parent / "migrations" / "004_elo_rating.sql").read_text()
                    await self.pool.execute(migration_004)
```

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/migrations/init.sql python/memory_manager.py
git commit -m "feat: add init.sql for first-run DB schema creation"
```

---

## Task 5: Refactor Proxy, Manager, Consolidator to Use Clients

**Files:**
- Modify: `python/memory_proxy.py:22,29-34,185,864-867,967-969,1050-1052,1157-1169,1178`
- Modify: `python/memory_manager.py:15-57` (replace llama_cpp with embedding_client)
- Modify: `python/memory_consolidator.py:18,93-121,284-297`
- Modify: `python/session_tracker.py:23-26,75-85`
- Modify: `python/lyume_status.py:27,39,41,176,259`
- Modify: `python/tests/test_session_tracker.py:101-102`

This is the largest task — refactoring all LM Studio references to use the new clients.

- [ ] **Step 1: Refactor memory_manager.py — replace llama-cpp with EmbeddingClient**

Replace `memory_manager.py:1-57` (imports through `get_embedding_async`) with:

```python
"""
MemoryManager — PostgreSQL + pgvector memory for Lyume.
Embeddings via configurable client (HTTP or local llama-cpp).
Supports: save, search, archive, recall from archive.
"""

import asyncio
import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from config import cfg
from embedding_client import create_embedding_client

DB_CONFIG = {
    "host": cfg.database.host,
    "port": cfg.database.port,
    "user": cfg.database.user,
    "database": cfg.database.name,
}

# Singleton embedding client
_embed_client = None


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        emb = cfg.embedding
        _embed_client = create_embedding_client(
            provider=getattr(emb, "provider", "local"),
            url=getattr(emb, "url", ""),
            api_key=getattr(emb, "api_key", ""),
            model=getattr(emb, "model", "nomic-embed-text"),
            model_path=getattr(emb, "model_path", ""),
            n_ctx=getattr(emb, "n_ctx", 512),
            n_gpu_layers=getattr(emb, "n_gpu_layers", 0),
            dimensions=getattr(emb, "dimensions", 768),
        )
    return _embed_client


def get_embedding(text: str) -> list[float]:
    """Sync wrapper for embedding (for backward compat)."""
    client = _get_embed_client()
    loop = asyncio.get_event_loop()
    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, client.embed(text)).result()
    return asyncio.run(client.embed(text))


async def get_embedding_async(text: str) -> list[float]:
    """Async embedding — delegates to configured client."""
    client = _get_embed_client()
    return await client.embed(text)
```

- [ ] **Step 2: Refactor memory_proxy.py — replace LM_STUDIO globals with LLMClient**

Replace `memory_proxy.py:29-34` with:

```python
from llm_client import LLMClient

_llm_client = LLMClient(
    url=cfg.llm.url,
    api_key=getattr(cfg.llm, "api_key", ""),
    model=cfg.llm.model,
    timeout=getattr(cfg.llm, "request_timeout", 300),
)

# Backward compat aliases used throughout the file
LM_STUDIO_URL = cfg.llm.url
LM_STUDIO_API_KEY = getattr(cfg.llm, "api_key", "")
LM_STUDIO_HEADERS = {
    "Content-Type": "application/json",
}
if LM_STUDIO_API_KEY:
    LM_STUDIO_HEADERS["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"
```

Also replace `cfg.lm_studio.model_name` → `cfg.llm.model` at lines 867, and any other occurrence.

- [ ] **Step 3: Refactor memory_consolidator.py**

Replace lines 284-285:
```python
        lm_url = cfg.llm.url
        model = cfg.llm.model
```

Replace lines 293-294 (availability check):
```python
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(f"{lm_url}/v1/models")
```

- [ ] **Step 4: Refactor session_tracker.py**

Replace line 80:
```python
                        "model": cfg.llm.model,
```

- [ ] **Step 5: Refactor lyume_status.py**

Replace lines 39,41:
```python
LM_STUDIO_URL    = cfg.llm.url
LM_STUDIO_API_KEY = getattr(cfg.llm, "api_key", "")
```

- [ ] **Step 6: Fix test references**

In `python/tests/test_session_tracker.py:101-102`:
```python
        mock_cfg.llm.url = "http://localhost:1234"
        mock_cfg.llm.model = "test-model"
```

- [ ] **Step 7: Run ALL tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_proxy.py python/memory_manager.py python/memory_consolidator.py python/session_tracker.py python/lyume_status.py python/tests/test_session_tracker.py
git commit -m "refactor: replace LM Studio hardcodes with generic LLMClient and EmbeddingClient"
```

---

## Task 6: pyproject.toml — Make llama-cpp-python Optional

**Files:**
- Modify: `python/pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

```toml
[project]
name = "lyume-memory-proxy"
version = "0.2.0"
description = "Drop-in memory proxy for local LLMs. Private. Learns from feedback."
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.135.0",
    "uvicorn>=0.42.0",
    "httpx>=0.28.0",
    "asyncpg>=0.31.0",
    "pyyaml>=6.0",
    "numpy>=2.0",
    "rich>=14.0",
    "textual>=8.0",
]

[project.optional-dependencies]
local-embedding = [
    "llama-cpp-python>=0.3.0",
]
dev = [
    "pytest>=9.0",
    "ruff>=0.9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["python"]
```

- [ ] **Step 2: Run `uv sync` to verify deps resolve**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv sync`
Expected: Resolves without llama-cpp-python in base deps

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add pyproject.toml
git commit -m "feat: make llama-cpp-python optional (local-embedding extra)"
```

---

## Task 7: Docker Compose — Generic Config

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`

- [ ] **Step 1: Update docker-compose.yml**

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-lyume}
      POSTGRES_DB: ${POSTGRES_DB:-ai_memory}
    volumes:
      - lyume_pgdata:/var/lib/postgresql/data
    ports:
      - "${DB_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  proxy:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      LYUME_LLM_URL: ${LLM_URL:-http://host.docker.internal:11434/v1}
      LYUME_LLM_MODEL: ${LLM_MODEL:-}
      LYUME_LLM_API_KEY: ${LLM_API_KEY:-}
      LYUME_EMBED_PROVIDER: ${EMBED_PROVIDER:-http}
      LYUME_EMBED_URL: ${EMBED_URL:-http://host.docker.internal:11434/v1}
      LYUME_EMBED_MODEL: ${EMBED_MODEL:-nomic-embed-text}
      LYUME_DB_HOST: db
      LYUME_DB_PORT: "5432"
      LYUME_DB_USER: ${POSTGRES_USER:-postgres}
      LYUME_DB_PASSWORD: ${POSTGRES_PASSWORD:-lyume}
      LYUME_DB_NAME: ${POSTGRES_DB:-ai_memory}
    ports:
      - "${PROXY_PORT:-1235}:1235"

volumes:
  lyume_pgdata:
```

- [ ] **Step 2: Update Dockerfile — remove hardcoded embedding model mount**

Remove the volume mount for embedding model from Dockerfile. The embedding model is now handled via HTTP endpoint or installed separately.

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add docker-compose.yml Dockerfile
git commit -m "feat: make docker-compose generic — no hardcoded model paths"
```

---

## Task 8: Memory Import Pipeline

**Files:**
- Create: `python/memory_import.py`
- Create: `python/tests/test_memory_import.py`

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_memory_import.py
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from memory_import import scan_markdown_files, parse_blocks, ImportPipeline


def test_scan_finds_md_files():
    """scan_markdown_files() finds .md and .mdc files."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.md").write_text("# Hello")
        (Path(d) / "rules.mdc").write_text("---\nrule: test\n---")
        (Path(d) / "readme.txt").write_text("ignore me")
        (Path(d) / "sub").mkdir()
        (Path(d) / "sub" / "deep.md").write_text("# Deep")

        files = scan_markdown_files(d)
        assert len(files) == 3
        names = {f.name for f in files}
        assert "notes.md" in names
        assert "rules.mdc" in names
        assert "deep.md" in names


def test_parse_blocks_by_headers():
    """parse_blocks() splits markdown by ## headers."""
    content = """# Main Title

Some intro text.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
    blocks = parse_blocks(content)
    assert len(blocks) == 3  # intro + section one + section two
    assert "intro text" in blocks[0]
    assert "section one" in blocks[1].lower()
    assert "section two" in blocks[2].lower()


def test_parse_blocks_by_separator():
    """parse_blocks() splits by --- if no headers found."""
    content = """First block of text.

---

Second block of text.

---

Third block of text.
"""
    blocks = parse_blocks(content)
    assert len(blocks) == 3


def test_parse_blocks_single():
    """parse_blocks() returns whole content if no separators."""
    content = "Just a single paragraph of memory."
    blocks = parse_blocks(content)
    assert len(blocks) == 1
    assert blocks[0] == content


def test_parse_blocks_skips_empty():
    """parse_blocks() skips empty blocks."""
    content = """## Header

Content here.

##

## Another

More content.
"""
    blocks = parse_blocks(content)
    assert all(b.strip() for b in blocks)


@pytest.mark.asyncio
async def test_import_pipeline_dedup():
    """ImportPipeline skips blocks with similarity > 0.9 to existing memories."""
    mock_mm = AsyncMock()
    mock_mm.search_semantic = AsyncMock(return_value=[{"similarity": 0.95, "content": "existing"}])

    mock_embed = AsyncMock()
    mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

    pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)

    result = await pipeline.import_block("duplicate content", source="test.md")
    assert result == "duplicate"


@pytest.mark.asyncio
async def test_import_pipeline_saves_new():
    """ImportPipeline saves blocks with no similar existing memories."""
    mock_mm = AsyncMock()
    mock_mm.search_semantic = AsyncMock(return_value=[])
    mock_mm.save_semantic = AsyncMock()

    mock_embed = AsyncMock()
    mock_embed.embed = AsyncMock(return_value=[0.1] * 768)

    pipeline = ImportPipeline(memory_manager=mock_mm, embedding_client=mock_embed)

    result = await pipeline.import_block("brand new memory", source="test.md")
    assert result == "imported"
    mock_mm.save_semantic.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_memory_import.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory_import'`

- [ ] **Step 3: Write memory_import.py**

```python
# python/memory_import.py
"""Import memory from external AI agent markdown files into Lyume DB."""

import re
from pathlib import Path


def scan_markdown_files(directory: str) -> list[Path]:
    """Recursively find all .md and .mdc files in directory."""
    root = Path(directory)
    files = []
    for pattern in ("**/*.md", "**/*.mdc"):
        files.extend(root.glob(pattern))
    return sorted(set(files))


def parse_blocks(content: str) -> list[str]:
    """Split markdown content into logical blocks."""
    # Try splitting by ## headers first
    header_parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    if len(header_parts) > 1:
        blocks = [p.strip() for p in header_parts if p.strip()]
        return [b for b in blocks if b]

    # Try splitting by --- separators
    sep_parts = re.split(r"^---+$", content, flags=re.MULTILINE)
    if len(sep_parts) > 1:
        blocks = [p.strip() for p in sep_parts if p.strip()]
        return [b for b in blocks if b]

    # Return whole content as single block
    stripped = content.strip()
    return [stripped] if stripped else []


class ImportPipeline:
    """Import parsed memory blocks into Lyume database."""

    def __init__(self, memory_manager, embedding_client, dedup_threshold: float = 0.9):
        self._mm = memory_manager
        self._embed = embedding_client
        self._threshold = dedup_threshold

    async def import_block(self, text: str, source: str = "") -> str:
        """Import a single block. Returns 'imported', 'duplicate', or 'error'."""
        try:
            embedding = await self._embed.embed(text)

            # Check for duplicates
            existing = await self._mm.search_semantic(
                query=text, limit=1, embedding=embedding
            )
            if existing and existing[0].get("similarity", 0) > self._threshold:
                return "duplicate"

            # Save as semantic memory
            await self._mm.save_semantic(
                content=text,
                category="imported",
                source_info={"file": source, "type": "import"},
            )
            return "imported"
        except Exception:
            return "error"

    async def import_file(self, file_path: Path) -> dict:
        """Import all blocks from a single file. Returns stats."""
        content = file_path.read_text(encoding="utf-8", errors="replace")
        blocks = parse_blocks(content)
        stats = {"imported": 0, "duplicate": 0, "error": 0, "total": len(blocks)}

        for block in blocks:
            if len(block.strip()) < 10:  # skip tiny blocks
                stats["total"] -= 1
                continue
            result = await self.import_block(block, source=str(file_path))
            stats[result] += 1

        return stats

    async def import_directory(self, directory: str) -> dict:
        """Import all markdown files from directory. Returns aggregate stats."""
        files = scan_markdown_files(directory)
        total = {"files": len(files), "imported": 0, "duplicate": 0, "error": 0, "total": 0}

        for f in files:
            stats = await self.import_file(f)
            for key in ("imported", "duplicate", "error", "total"):
                total[key] += stats[key]

        return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_memory_import.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_import.py python/tests/test_memory_import.py
git commit -m "feat: add memory import pipeline for external AI agent files"
```

---

## Task 9: TUI Wizard

**Files:**
- Create: `python/wizard.py`
- Create: `python/tests/test_wizard.py`

- [ ] **Step 1: Write basic tests**

```python
# python/tests/test_wizard.py
import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from wizard import detect_known_memory_paths, generate_config, KNOWN_MEMORY_PATHS


def test_detect_known_memory_paths_finds_claude():
    """detect_known_memory_paths() finds Claude Code memory if it exists."""
    with tempfile.TemporaryDirectory() as d:
        claude_dir = Path(d) / ".claude" / "projects" / "test" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "MEMORY.md").write_text("# Memory")

        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert any("claude" in str(p).lower() for p in paths)


def test_detect_known_memory_paths_empty():
    """detect_known_memory_paths() returns empty list if nothing found."""
    with tempfile.TemporaryDirectory() as d:
        with patch("wizard.Path.home", return_value=Path(d)):
            paths = detect_known_memory_paths()
            assert paths == []


def test_generate_config():
    """generate_config() produces valid YAML with all required sections."""
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
        db_name="ai_memory",
    )
    assert config["first_run"] is False
    assert config["llm"]["url"] == "http://localhost:11434/v1"
    assert config["llm"]["model"] == "llama3"
    assert config["embedding"]["provider"] == "http"
    assert config["database"]["provider"] == "docker"


def test_generate_config_writes_identity(tmp_path):
    """generate_config() info can be used to write IDENTITY.md and USER.md."""
    identity_path = tmp_path / "IDENTITY.md"
    user_path = tmp_path / "USER.md"

    config = generate_config(
        agent_name="Luna",
        user_name="Alex",
        llm_url="http://localhost:11434/v1",
        llm_model="llama3",
    )

    # Wizard writes these files
    identity_path.write_text(f"Name: {config['_agent_name']}\nRole: Companion\n")
    user_path.write_text(f"{config['_user_name']}\n")

    assert "Luna" in identity_path.read_text()
    assert "Alex" in user_path.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_wizard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wizard'`

- [ ] **Step 3: Write wizard.py**

```python
# python/wizard.py
"""TUI Wizard — first-run setup for Lyume Memory Proxy."""

import asyncio
import subprocess
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress

console = Console()

KNOWN_MEMORY_PATHS = [
    ("Claude Code", "~/.claude/projects/*/memory/"),
    ("Cursor", ".cursor/rules/"),
    ("Cursor (legacy)", ".cursorrules"),
    ("Windsurf", ".windsurfrules.md"),
    ("Cline", ".clinerules/memory/"),
    ("GitHub Copilot", ".github/copilot-instructions.md"),
    ("OpenAI Codex", "AGENTS.md"),
    ("Gemini CLI", "GEMINI.md"),
    ("Aider", "CONVENTIONS.md"),
]


def detect_known_memory_paths() -> list[Path]:
    """Scan known AI agent memory locations on the system."""
    home = Path.home()
    found = []
    for name, pattern in KNOWN_MEMORY_PATHS:
        if pattern.startswith("~"):
            expanded = Path(pattern.replace("~", str(home)))
            # Handle glob patterns
            if "*" in str(expanded):
                parent = expanded.parent
                while "*" in str(parent):
                    parent = parent.parent
                if parent.exists():
                    matches = list(parent.glob(str(expanded).replace(str(parent) + "/", "")))
                    found.extend(matches)
            elif expanded.exists():
                found.append(expanded)
        else:
            # Project-relative paths — check current dir
            p = Path.cwd() / pattern
            if p.exists():
                found.append(p)
    return found


def generate_config(
    agent_name: str = "Lyume",
    user_name: str = "",
    llm_url: str = "http://127.0.0.1:11434/v1",
    llm_model: str = "",
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
    db_name: str = "ai_memory",
) -> dict:
    """Generate config dict from wizard answers."""
    config = {
        "first_run": False,
        "_agent_name": agent_name,
        "_user_name": user_name,
        "server": {"host": "127.0.0.1", "port": 1235, "log_level": "info"},
        "llm": {
            "url": llm_url,
            "api_key": llm_api_key,
            "model": llm_model,
            "request_timeout": 300,
        },
        "embedding": {
            "provider": embed_provider,
            "url": embed_url or llm_url,
            "model": embed_model,
            "dimensions": 768,
        },
        "database": {
            "provider": db_provider,
            "host": db_host,
            "port": db_port,
            "user": db_user,
            "password": db_password,
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
            "summary_max_context": 30,
            "summary_buffer_cap": 60,
            "session_timeout": 1800,
        },
        "consolidation": {
            "enabled": True,
            "schedule": "03:00",
            "semantic_threshold": 0.85,
            "lesson_threshold": 0.85,
            "cooldown_days": 180,
            "stale_days": 365,
            "log_file": "consolidation.log",
        },
    }

    # Add local embedding config if provider is local
    if embed_provider == "local" and embed_model_path:
        config["embedding"]["model_path"] = embed_model_path
        config["embedding"]["n_ctx"] = 512
        config["embedding"]["n_gpu_layers"] = 0

    return config


async def check_llm_endpoint(url: str, api_key: str = "") -> tuple[bool, list[str]]:
    """Test LLM endpoint and return (available, model_list)."""
    import httpx
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{url.rstrip('/')}/models", headers=headers)
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", [])]
                return True, models
    except Exception:
        pass
    return False, []


async def check_embedding_endpoint(url: str, model: str, api_key: str = "") -> bool:
    """Test if embedding endpoint works."""
    import httpx
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{url.rstrip('/')}/embeddings",
                headers=headers,
                json={"model": model, "input": "test"},
            )
            return resp.status_code == 200
    except Exception:
        return False


def check_docker() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def run_wizard(config_path: str | None = None):
    """Interactive first-run wizard."""
    if config_path is None:
        config_path = str(Path(__file__).parent / "config.yaml")

    console.print(Panel("🔧 Lyume Memory Proxy — First Run Setup", style="bold cyan"))
    console.print()

    # Step 0: Agent Identity
    console.print("[bold]Step 0: Agent Identity[/bold]")
    agent_name = Prompt.ask("Agent name", default="Lyume")
    user_name = Prompt.ask("Your name")
    console.print()

    # Step 1: LLM Backend
    console.print("[bold]Step 1: LLM Backend[/bold]")
    llm_url = Prompt.ask("LLM endpoint URL", default="http://127.0.0.1:11434/v1")
    llm_api_key = Prompt.ask("API key (leave empty if none)", default="")

    available, models = asyncio.run(check_llm_endpoint(llm_url, llm_api_key))
    if available and models:
        console.print(f"[green]✓ Connected! Found {len(models)} model(s):[/green]")
        for i, m in enumerate(models, 1):
            console.print(f"  {i}. {m}")
        choice = Prompt.ask("Select model number", default="1")
        llm_model = models[int(choice) - 1]
    elif available:
        console.print("[yellow]⚠ Connected but no models listed.[/yellow]")
        llm_model = Prompt.ask("Enter model name manually")
    else:
        console.print("[red]✗ Cannot connect. Check URL and try again.[/red]")
        llm_model = Prompt.ask("Enter model name manually (or fix URL and restart)")
    console.print()

    # Step 2: Embedding
    console.print("[bold]Step 2: Embedding[/bold]")
    embed_ok = asyncio.run(check_embedding_endpoint(llm_url, "nomic-embed-text", llm_api_key))
    if embed_ok:
        console.print("[green]✓ Embedding endpoint works on same URL![/green]")
        embed_provider = "http"
        embed_url = llm_url
        embed_model = Prompt.ask("Embedding model", default="nomic-embed-text")
        embed_model_path = ""
    else:
        console.print("[yellow]⚠ No embedding endpoint found on LLM URL.[/yellow]")
        choice = Prompt.ask(
            "Options: [1] Different URL  [2] Local (llama-cpp-python)",
            choices=["1", "2"],
            default="1",
        )
        if choice == "1":
            embed_url = Prompt.ask("Embedding endpoint URL")
            embed_model = Prompt.ask("Embedding model", default="nomic-embed-text")
            embed_provider = "http"
            embed_model_path = ""
        else:
            embed_provider = "local"
            embed_url = ""
            embed_model = ""
            embed_model_path = Prompt.ask("Path to GGUF embedding model")
    console.print()

    # Step 3: Database
    console.print("[bold]Step 3: Database[/bold]")
    if check_docker():
        console.print("[green]✓ Docker available[/green]")
        use_docker = Confirm.ask("Use Docker for PostgreSQL?", default=True)
    else:
        console.print("[yellow]⚠ Docker not found[/yellow]")
        use_docker = False

    if use_docker:
        db_provider = "docker"
        db_host = "127.0.0.1"
        db_port = 5432
        db_user = "postgres"
        db_password = Prompt.ask("DB password", default="lyume")
        db_name = "ai_memory"
        console.print("[dim]Starting PostgreSQL container...[/dim]")
        subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
        )
    else:
        db_provider = "external"
        db_host = Prompt.ask("PostgreSQL host", default="127.0.0.1")
        db_port = int(Prompt.ask("PostgreSQL port", default="5432"))
        db_user = Prompt.ask("PostgreSQL user", default="postgres")
        db_password = Prompt.ask("PostgreSQL password", default="lyume")
        db_name = Prompt.ask("Database name", default="ai_memory")
    console.print()

    # Step 4: Memory Import
    console.print("[bold]Step 4: Memory Import (optional)[/bold]")
    console.print(Panel(
        "Many AI agents store memory in text files.\n"
        "Lyume can import them so it knows about you right away.\n\n"
        "Known formats:\n"
        "  Claude Code  →  ~/.claude/projects/*/memory/\n"
        "  Cursor       →  .cursor/rules/*.mdc\n"
        "  Windsurf     →  .windsurfrules.md\n"
        "  Cline        →  .clinerules/memory/\n"
        "  Copilot      →  .github/copilot-instructions.md\n"
        "  Codex        →  AGENTS.md\n"
        "  Gemini       →  GEMINI.md\n"
        "  Aider        →  CONVENTIONS.md\n"
        "  Other        →  any folder with .md files",
        title="Memory Import",
        style="dim",
    ))

    found_paths = detect_known_memory_paths()
    import_path = None
    if found_paths:
        console.print(f"[green]Found {len(found_paths)} existing memory location(s):[/green]")
        for p in found_paths:
            console.print(f"  • {p}")
        if Confirm.ask("Import from these locations?", default=True):
            import_path = [str(p) for p in found_paths]
    else:
        console.print("[dim]No known memory locations found.[/dim]")

    if import_path is None:
        manual = Prompt.ask("Enter path to import from (or 'skip')", default="skip")
        if manual != "skip":
            import_path = [manual]
    console.print()

    # Generate and save config
    config = generate_config(
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

    # Remove internal keys before saving
    agent_name_val = config.pop("_agent_name")
    user_name_val = config.pop("_user_name")

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    console.print(f"[green]✓ Config saved to {config_path}[/green]")

    # Write IDENTITY.md and USER.md
    workspace = Path(__file__).parent.parent
    (workspace / "IDENTITY.md").write_text(f"Name: {agent_name_val}\nGender: \nRole: Companion\n")
    (workspace / "USER.md").write_text(f"{user_name_val}\n")
    console.print(f"[green]✓ IDENTITY.md and USER.md updated[/green]")

    # Memory import
    if import_path:
        console.print("[dim]Importing memories...[/dim]")
        # Import will be run after proxy starts (needs DB connection)
        # Save paths to config for deferred import
        config["_import_paths"] = import_path
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    console.print()
    console.print(Panel("[bold green]Setup complete! Run the proxy with:\n  uv run python memory_proxy.py[/bold green]"))


if __name__ == "__main__":
    run_wizard()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_wizard.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/wizard.py python/tests/test_wizard.py
git commit -m "feat: add TUI wizard for first-run setup"
```

---

## Task 10: Wire Wizard into Proxy Startup

**Files:**
- Modify: `python/memory_proxy.py` (lifespan function)

- [ ] **Step 1: Add wizard check to proxy lifespan**

At the top of the lifespan function in `memory_proxy.py`, before `mm.connect()`, add:

```python
    # Check if first run — launch wizard
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists() or cfg.first_run:
        from wizard import run_wizard
        run_wizard(str(config_path))
        # Reload config after wizard
        import importlib
        import config as config_module
        importlib.reload(config_module)
        from config import cfg as new_cfg
        # Update globals
        global _llm_client, LM_STUDIO_URL, LM_STUDIO_API_KEY, LM_STUDIO_HEADERS
        _llm_client = LLMClient(
            url=new_cfg.llm.url,
            api_key=getattr(new_cfg.llm, "api_key", ""),
            model=new_cfg.llm.model,
            timeout=getattr(new_cfg.llm, "request_timeout", 300),
        )
```

- [ ] **Step 2: Add deferred memory import after DB is ready**

After `mm.connect()` in lifespan, add:

```python
    # Deferred memory import (from wizard)
    if hasattr(cfg, '_import_paths') and cfg._import_paths:
        from memory_import import ImportPipeline
        from embedding_client import create_embedding_client
        embed_client = _get_embed_client()
        pipeline = ImportPipeline(memory_manager=mm, embedding_client=embed_client)
        for path in cfg._import_paths:
            stats = await pipeline.import_directory(path)
            print(f"[import] {path}: {stats['imported']} imported, {stats['duplicate']} duplicates", flush=True)
```

- [ ] **Step 3: Test manually**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run python -m uvicorn memory_proxy:app --host 127.0.0.1 --port 1235`
Expected: Proxy starts normally with existing config (first_run: false)

- [ ] **Step 4: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_proxy.py
git commit -m "feat: wire wizard + deferred memory import into proxy startup"
```

---

## Task 11: Integration Test — Full Flow

**Files:**
- Create: `python/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# python/tests/test_integration.py
"""Integration tests — verify all new components work together."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from llm_client import LLMClient
from embedding_client import HTTPEmbeddingClient, LocalEmbeddingClient, create_embedding_client
from memory_import import scan_markdown_files, parse_blocks, ImportPipeline
from wizard import generate_config, detect_known_memory_paths
from config import _migrate_config


def test_old_config_migrates_and_clients_init():
    """Old lm_studio config migrates correctly and clients can be created."""
    old = {
        "lm_studio": {"url": "http://localhost:1234", "api_key": "sk-test", "model_name": "qwen"},
        "embedding": {"model_path": "/fake/model.gguf", "n_ctx": 512, "dimensions": 768},
        "server": {"host": "127.0.0.1", "port": 1235},
        "database": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "name": "ai_memory"},
    }
    config = _migrate_config(old)

    # LLMClient can be created from migrated config
    llm = LLMClient(url=config["llm"]["url"], api_key=config["llm"]["api_key"], model=config["llm"]["model"])
    assert llm.url == "http://localhost:1234"
    assert llm.model == "qwen"

    # Embedding provider detected as local
    assert config["embedding"]["provider"] == "local"


def test_wizard_config_creates_valid_yaml():
    """Wizard output produces a config that all components can read."""
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
    assert config["llm"]["url"] == "http://localhost:11434/v1"
    assert config["embedding"]["provider"] == "http"
    assert config["database"]["provider"] == "docker"

    # LLMClient can be created
    llm = LLMClient(url=config["llm"]["url"], model=config["llm"]["model"])
    assert llm.model == "llama3"

    # HTTPEmbeddingClient can be created
    embed = HTTPEmbeddingClient(url=config["embedding"]["url"], model=config["embedding"]["model"])
    assert embed.model == "nomic-embed-text"


@pytest.mark.asyncio
async def test_import_pipeline_end_to_end():
    """Full import: scan → parse → classify → embed → dedup → save."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        # Create test memory files
        (Path(d) / "memory.md").write_text(
            "## Preferences\n\nUser prefers dark theme.\n\n## Skills\n\nUser knows Python and TypeScript."
        )

        # Scan
        files = scan_markdown_files(d)
        assert len(files) == 1

        # Parse
        content = files[0].read_text()
        blocks = parse_blocks(content)
        assert len(blocks) == 2

        # Import with mock MM and embed client
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
```

- [ ] **Step 2: Run integration tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/test_integration.py -v`
Expected: 3 passed

- [ ] **Step 3: Run FULL test suite**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run pytest python/tests/ -v`
Expected: All tests pass (87 original + ~25 new = ~112 total)

- [ ] **Step 4: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/tests/test_integration.py
git commit -m "test: add integration tests for Phase 2 generic agent pack"
```

---

## Task 12: Final — Update README and Verify

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with new setup instructions**

Add to README.md after the existing "What is this?" section:

```markdown
## Quick Start

### First Run (interactive wizard)

```bash
uv run python python/wizard.py
```

The wizard will guide you through:
1. Naming your agent
2. Connecting to your LLM (Ollama, LM Studio, llama.cpp, or any OpenAI-compatible endpoint)
3. Setting up embeddings
4. Starting PostgreSQL (Docker or existing)
5. Optionally importing memory from other AI agents

### Manual Setup

1. Copy `python/config.yaml.example` to `python/config.yaml`
2. Edit the config with your LLM endpoint URL and model
3. Start PostgreSQL: `docker compose up -d db`
4. Run the proxy: `uv run python -m uvicorn python.memory_proxy:app --host 127.0.0.1 --port 1235`

### Works With

- **Ollama** — `ollama serve` → URL: `http://127.0.0.1:11434/v1`
- **LM Studio** — Start server → URL: `http://127.0.0.1:1234/v1`
- **llama.cpp** — `./llama-server -m model.gguf` → URL: `http://127.0.0.1:8080/v1`
- **vLLM** — `vllm serve model` → URL: `http://127.0.0.1:8000/v1`
- **Any OpenAI-compatible API**
```

- [ ] **Step 2: Verify proxy starts and works**

Run: `cd /home/tarik/.openclaw/workspace-lyume && uv run python -m uvicorn memory_proxy:app --host 127.0.0.1 --port 1235`
Expected: Proxy starts, connects to DB, ready to serve

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add README.md
git commit -m "docs: update README with generic setup instructions"
```
