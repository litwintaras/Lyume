"""
ConversationBuffer — short-term memory with Ebbinghaus power-law decay.
In-memory ring buffer. Recent messages have high weight, old ones fade.
Weight formula: w = (1 + t_minutes) ** (-decay_power)
"""

import json
import time
from pathlib import Path

from intent_classifier import is_noise


class ConversationBuffer:
    def __init__(
        self,
        max_entries: int = 200,
        weight_cutoff: float = 0.05,
        max_inject: int = 15,
        max_chars: int = 500,
        decay_power: float = 0.5,
    ):
        self.max_entries = max_entries
        self.weight_cutoff = weight_cutoff
        self.max_inject = max_inject
        self.max_chars = max_chars
        self.decay_power = decay_power
        self._entries: list[dict] = []

    def _weight(self, entry_ts: float, now: float) -> float:
        """Compute power-law weight: w = (1 + t_minutes) ** (-decay_power)"""
        t_minutes = max(0, (now - entry_ts)) / 60.0
        return (1 + t_minutes) ** (-self.decay_power)

    def add(self, role: str, content: str) -> None:
        """Add message to buffer. Filter noise and short assistant responses."""
        content = content.strip()
        if role == "user" and is_noise(content):
            return
        if role == "assistant" and len(content) < 10:
            return
        self._entries.append({
            "role": role,
            "content": content,
            "ts": time.time(),
        })
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

    def get_weighted(self) -> list[dict]:
        """Return weighted entries: filter by cutoff, truncate, limit to max_inject."""
        now = time.time()
        result = []
        for entry in self._entries:
            w = self._weight(entry["ts"], now)
            if w >= self.weight_cutoff:
                content = entry["content"]
                if len(content) > self.max_chars:
                    content = content[:self.max_chars] + "..."
                result.append({
                    "role": entry["role"],
                    "content": content,
                    "ts": entry["ts"],
                    "weight": w,
                })
        result = result[-self.max_inject:]
        return result

    def format_block(self) -> str:
        """Format entries as XML block with time labels."""
        entries = self.get_weighted()
        if not entries:
            return ""
        now = time.time()
        lines = ["<recent_conversation>"]
        for e in entries:
            delta = now - e["ts"]
            label = _format_time_ago(delta)
            lines.append(f"[{label}] {e['role']}: {e['content']}")
        lines.append("</recent_conversation>")
        return "\n".join(lines)

    def dump(self, path: Path) -> None:
        """Save buffer to JSON file."""
        try:
            path.write_text(json.dumps(self._entries, ensure_ascii=False))
            print(f"[buffer] Saved {len(self._entries)} entries to {path}", flush=True)
        except Exception as e:
            print(f"[buffer] Failed to save: {e}", flush=True)

    def load(self, path: Path) -> None:
        """Load buffer from JSON file, filtering by weight_cutoff."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            now = time.time()
            self._entries = [
                e for e in data
                if self._weight(e["ts"], now) >= self.weight_cutoff
            ]
            print(f"[buffer] Loaded {len(self._entries)} entries from {path}", flush=True)
        except Exception as e:
            print(f"[buffer] Failed to load: {e}", flush=True)

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()


def _format_time_ago(seconds: float) -> str:
    """Format time delta as Ukrainian label."""
    minutes = seconds / 60
    if minutes < 1:
        return "щойно"
    if minutes < 60:
        m = int(minutes)
        return f"{m} хв тому"
    hours = minutes / 60
    if hours < 24:
        h = int(hours)
        return f"{h} год тому"
    d = int(hours / 24)
    return f"{d} дн тому"
