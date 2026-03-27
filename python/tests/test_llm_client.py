import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from llm_client import LLMClient


@pytest.mark.asyncio
async def test_complete_returns_content():
    """LLMClient.complete() returns assistant message content."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "choices": [{"message": {"content": "Hello world"}}]
    })

    with patch("llm_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
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
