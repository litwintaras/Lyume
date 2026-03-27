"""
SessionTracker — tracks messages per session, generates LLM summaries.
Summaries stored as category='session_summary' in existing PostgreSQL.
"""

import time
import re
from datetime import datetime, timezone

import httpx

from config import cfg

SUMMARY_PROMPT = """Summarize this conversation in 3-5 sentences.
Focus 80% on what was discussed and accomplished, 20% on emotional tone.
Be specific: mention file names, features, decisions made.
Include the timestamp of the last action discussed.
Do not include greetings or filler.
Respond in the same language as the conversation."""


class SessionTracker:
    def __init__(self, memory_manager, lm_studio_url: str, headers: dict):
        self._memory_manager = memory_manager
        self._lm_studio_url = lm_studio_url
        self._headers = headers
        self._buffer: list[dict] = []
        self._user_msg_count: int = 0
        self._last_message_time: float = 0
        self._session_start: str = datetime.now(timezone.utc).isoformat()
        self._summary_interval: int = cfg.features.summary_interval or 20
        self._buffer_cap: int = cfg.features.summary_buffer_cap or 60
        self._session_timeout: int = cfg.features.session_timeout or 1800
        self._summary_max_context: int = cfg.features.summary_max_context or 30

    def track_message(self, role: str, content: str):
        """Add message to buffer (sliding window), increment counters, update timestamp."""
        self._buffer.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if role == "user":
            self._user_msg_count += 1
        # Sliding window
        if len(self._buffer) > self._buffer_cap:
            self._buffer = self._buffer[-self._buffer_cap:]
        self._last_message_time = time.monotonic()

    def check_timeout(self) -> bool:
        """True if session timed out. Caller should trigger summary + reset."""
        if self._last_message_time == 0:
            return False
        return (time.monotonic() - self._last_message_time) > self._session_timeout

    def should_summarize(self) -> bool:
        """True if user_msg_count is a multiple of summary_interval."""
        return self._user_msg_count > 0 and self._user_msg_count % self._summary_interval == 0

    async def generate_summary(self, summary_type: str = "periodic") -> str | None:
        """Send last N messages to LLM, get summary, prefix with timestamp, save to DB."""
        if len(self._buffer) < 3:
            print(f"[session] Skipping summary — only {len(self._buffer)} messages", flush=True)
            return None

        # Take last N messages for context
        context_msgs = self._buffer[-self._summary_max_context:]
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in context_msgs
        ]
        messages.append({"role": "user", "content": SUMMARY_PROMPT})

        try:
            async with httpx.AsyncClient(timeout=cfg.llm.reflection_timeout) as client:
                resp = await client.post(
                    f"{self._lm_studio_url}/v1/chat/completions",
                    headers=self._headers,
                    json={
                        "model": cfg.llm.model,
                        "messages": messages,
                        "max_tokens": 1024,
                        "stream": False,
                    },
                )
            result = resp.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            if not content:
                print("[session] Empty summary from LLM", flush=True)
                return None

            # Strip think tags if present
            if "<think>" in content:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            # Prefix with timestamp for unique embedding
            now = datetime.now(timezone.utc)
            prefix = now.strftime("[session %Y-%m-%d %H:%M]")
            prefixed = f"{prefix} {content}"

            # Save to DB
            await self._memory_manager.save_semantic(
                content=prefixed,
                concept_name=f"session_{summary_type}",
                category="session_summary",
                keywords=[summary_type, now.strftime("%Y-%m-%d")],
                source_info={
                    "source": "session_tracker",
                    "summary_type": summary_type,
                    "msg_count": len(context_msgs),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M"),
                },
            )
            print(f"[session] {summary_type} summary saved ({len(content)} chars, {len(context_msgs)} msgs)", flush=True)
            return prefixed

        except Exception as e:
            print(f"[session] Summary generation error: {e}", flush=True)
            return None

    def start_new_session(self):
        """Clear buffer, reset counters, update session_start."""
        self._buffer.clear()
        self._user_msg_count = 0
        self._session_start = datetime.now(timezone.utc).isoformat()
        print(f"[session] New session started at {self._session_start}", flush=True)
