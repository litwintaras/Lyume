# Session Summary Design Spec

**Date:** 2026-03-25
**Goal:** Proxy automatically generates and stores conversation summaries so the AI remembers what happened in previous sessions — zero config, no file-based memory needed.

## Problem

When a user asks "what did we do yesterday?" in a new session, the AI has no chronological context. Semantic memory stores individual facts but not session narratives. File-based memory (MEMORY.md, daily notes) requires manual maintenance and is always empty or stale.

## Solution

A `session_tracker.py` module that:
1. Tracks messages per session
2. Generates summaries via LLM at key moments
3. Stores summaries in the existing PostgreSQL database as memories with category `session_summary`

## Assumptions

- **Single-user proxy.** One SessionTracker instance per process. No multi-user session isolation.
- **Stateless HTTP proxy.** Session boundaries detected by inactivity timeout, not persistent connections.

## Session Boundary Detection

Timeout-based: if 30+ minutes pass between user messages, the current session is considered ended and a new one begins.

```
Message arrives
  → Check last_message_time
  → If now - last_message_time > session_timeout (30min):
    1. Generate farewell summary for OLD session (from buffer)
    2. Clear buffer
    3. Start new session
  → Update last_message_time
```

Config: `session_timeout: 1800` (seconds, default 30 min)

## Triggers

| Trigger | When | summary_type |
|---------|------|-------------|
| Farewell | User says goodbye (already detected by proxy) | `farewell` |
| Periodic | Every 20 user messages | `periodic` |
| Timeout | 30min inactivity, next message arrives | `timeout` |

## Data Flow

```
User message arrives
  → session_tracker.track_message("user", query)
  → Check timeout → if expired, summarize old session + start new
  → Increment user_msg_count
  → If count % 20 == 0 OR farewell detected:
    1. Collect last N messages from buffer (sliding window, max 60)
    2. Send last 30 to LLM with summary prompt
    3. Prefix summary with "[session YYYY-MM-DD HH:MM]" for unique embedding
    4. Save to DB: category="session_summary", metadata={date, time, msg_count, summary_type}
    5. Reset counter (for periodic only)
```

## Summary Prompt

```
Summarize this conversation in 3-5 sentences.
Focus 80% on what was discussed and accomplished, 20% on emotional tone.
Be specific: mention file names, features, decisions made.
Include the timestamp of the last action discussed.
Do not include greetings or filler.
Respond in the same language as the conversation.
```

## Dedup Prevention

Session summaries are prefixed with `[session YYYY-MM-DD HH:MM]` before saving. This makes embeddings unique even if two summaries cover similar topics. The existing dedup logic (cosine > 0.9 → update) won't collide because the prefix differentiates them.

## Recall Logic

Two layers:

### Layer 1: Explicit triggers (regex in intent_classifier.py)
Pattern detects queries about previous sessions:
- Ukrainian: "минулий чат", "що ми робили", "що ми обговорювали", "минулу сесію", "попередній чат", "вчора робили", "нагадай що було", "про що говорили", "що було в минулому"
- English: "last session", "what did we do", "previous chat", "what we discussed", "yesterday", "last time", "what happened"

When detected: search memories with `category="session_summary"` filter. Sort by date descending. Return top 3.

### Layer 2: Semantic search (already exists)
Even without explicit triggers, if user asks "tell me about the Docker setup we did" — semantic search will find session summaries that mention Docker. No special handling needed.

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `python/session_tracker.py` | **Create** | Session message buffer, summary generation, DB storage |
| `python/intent_classifier.py` | **Modify** | Add SESSION_RECALL_INTENT pattern + update classify_user_intent |
| `python/memory_proxy.py` | **Modify** | Wire session_tracker into request flow |
| `python/memory_manager.py` | **Modify** | Add optional `category` filter to `search_semantic` |
| `python/config.yaml` | **Modify** | Add session_summary settings to features section |
| `python/config.py` | **No change** | Already supports new config sections via __getattr__ |
| `python/tests/test_session_tracker.py` | **Create** | Unit tests |
| `AGENTS.md` | **Modify** | Remove file-based memory instructions |
| `MEMORY.md` | **Modify** | Replace with single line about automatic memory |

## Config Changes

```yaml
features:
  strip_think_tags: true
  marker_fallback: true
  session_summary: true
  summary_interval: 20        # every N user messages
  summary_max_context: 30     # max messages to send to LLM for summary
  summary_buffer_cap: 60      # max messages kept in buffer (sliding window)
  session_timeout: 1800       # seconds of inactivity before new session (30 min)
```

## memory_manager.py Changes

Add optional `category` parameter to `search_semantic`:

```python
async def search_semantic(self, query, ..., category: str | None = None):
    # Existing logic...
    # If category specified, add WHERE clause:
    # AND category = $N
```

## Session Tracker API

```python
class SessionTracker:
    def __init__(self, memory_manager, lm_studio_url, headers):
        self._buffer: list[dict] = []      # {role, content, timestamp}
        self._user_msg_count: int = 0
        self._last_message_time: float = 0  # monotonic
        self._session_start: str = ""       # ISO datetime

    def track_message(self, role: str, content: str):
        """Add message to buffer (sliding window), increment counters, update timestamp."""

    def check_timeout(self) -> bool:
        """True if session timed out. Caller should trigger summary + reset."""

    def should_summarize(self) -> bool:
        """True if user_msg_count % summary_interval == 0."""

    async def generate_summary(self, summary_type: str = "periodic") -> str | None:
        """Send last N messages to LLM, get summary, prefix with timestamp, save to DB."""

    def start_new_session(self):
        """Clear buffer, reset counters, update session_start."""
```

## Integration Points in memory_proxy.py

1. **On every request:** `session_tracker.track_message("user", user_query)`
2. **Check timeout:** if `session_tracker.check_timeout()` → `generate_summary("timeout")` + `start_new_session()`
3. **On every response:** `session_tracker.track_message("assistant", response_text)`
4. **After response processing:** if `session_tracker.should_summarize()` → `generate_summary("periodic")`
5. **On farewell:** `generate_summary("farewell")` + `start_new_session()`

## Relationship with existing reflection

Both work in parallel with different purposes:
- **Reflection** (`run_reflection`) → generates **lessons** (what went wrong, what to improve). Stored as `lesson` type.
- **Session summary** → generates **chronological narrative** (what happened). Stored as `session_summary` memory.

They complement each other. No changes to `run_reflection`.

## AGENTS.md Changes

Remove:
- File-based memory instructions ("Write It Down", MEMORY.md loading, daily notes)
- References to `memory/YYYY-MM-DD.md`

Keep:
- "### Semantic Memory (automatic)" section — update to mention session summaries
- "### Memory is Automatic" section (already added)

Add to "Memory is Automatic":
- "Session summaries are saved automatically — ask about any previous conversation"

## MEMORY.md Changes

Replace entire content with:
```markdown
# Memory

All memory is managed automatically by the proxy.
- Facts, preferences, and corrections are saved when detected
- Session summaries are generated at the end of each conversation
- Ask about any previous session and the AI will recall it

No manual memory management needed.
```

## Error Handling

- LLM timeout during summary generation → log warning, skip summary (non-blocking)
- Empty session buffer (< 3 messages) → skip summary
- DB save failure → log error, don't crash proxy
- Session timeout detection failure → next farewell catches it

## Testing

- Unit tests for SessionTracker: track_message, should_summarize, check_timeout, buffer cap
- Unit tests for SESSION_RECALL_INTENT pattern matching
- Integration: mock LLM response, verify summary saved to DB with correct metadata and timestamp prefix
