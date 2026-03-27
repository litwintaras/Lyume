import httpx
from typing import AsyncIterator, List, Optional


class LLMClient:
    def __init__(self, url: str, api_key: str = "", model: str = "", timeout: int = 300):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()

            response = await client.post(
                f"{self.url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or choice.get("text", "")
            return content

    async def complete_stream(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()

            async with client.stream("POST", f"{self.url}/chat/completions", json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    yield line

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = self._get_headers()
                response = await client.get(f"{self.url}/models", headers=headers)
                return response.status_code == 200
        except httpx.ConnectError:
            return False
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()
            response = await client.get(f"{self.url}/models", headers=headers)
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
