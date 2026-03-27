import pytest
import asyncio
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


@pytest.mark.asyncio
async def test_local_embed_returns_vector():
    """LocalEmbeddingClient.embed() wraps llama-cpp Llama.embed()."""
    mock_llama = MagicMock()
    mock_llama.embed.return_value = [[0.4, 0.5, 0.6]]

    with patch("embedding_client.Llama", return_value=mock_llama):
        client = LocalEmbeddingClient(model_path="/fake/model.gguf")
        client._model = mock_llama
        result = await client.embed("hello")
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
