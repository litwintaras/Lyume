"""Embedding abstraction — HTTP endpoint or local llama-cpp fallback."""

import asyncio

import httpx

# Lazy import — llama_cpp тільки для local provider
try:
    from llama_cpp import Llama
except ImportError:
    Llama = None


class HTTPEmbeddingClient:
    """Sends embedding requests to OpenAI-compatible /v1/embeddings endpoint."""

    def __init__(self, url: str, api_key: str = "", model: str = "nomic-embed-text", timeout: int = 60):
        self.url = url.rstrip("/").removesuffix("/v1")
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
                f"{self.url}/v1/embeddings",
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
            if Llama is None:
                raise ImportError(
                    "llama-cpp-python is required for local embeddings. "
                    "Install with: uv pip install llama-cpp-python"
                )
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
        return LocalEmbeddingClient(
            model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, dimensions=dimensions,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
