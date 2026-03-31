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
        """Disabled — session summaries killed in Phase 1 async pipeline."""
        return False

    async def generate_summary(self, summary_type: str = "periodic") -> str | None:
        """Disabled — session summaries killed in Phase 1 async pipeline.
        Farewell reflection uses run_reflection() in memory_proxy.py instead."""
        print(f"[session] Summary disabled (type={summary_type})", flush=True)
        return None

    def start_new_session(self):
        """Clear buffer, reset counters, update session_start."""
        self._buffer.clear()
        self._user_msg_count = 0
        self._session_start = datetime.now(timezone.utc).isoformat()
        print(f"[session] New session started at {self._session_start}", flush=True)
