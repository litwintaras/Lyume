# Session Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proxy automatically generates and stores conversation summaries so the AI remembers what happened in previous sessions.

**Architecture:** New `session_tracker.py` module tracks messages per session, generates LLM summaries at key moments (farewell, periodic, timeout), stores as `session_summary` category in existing PostgreSQL. Intent classifier gets `session_recall` pattern for explicit recall. `search_semantic` gets optional `category` filter.

**Tech Stack:** Python, asyncio, httpx, asyncpg (existing), FastAPI (existing)

**Spec:** `docs/superpowers/specs/2026-03-25-session-summary-design.md`

---

### Task 1: Add `category` filter to `search_semantic` in memory_manager.py

**Files:**
- Modify: `python/memory_manager.py:135-196` (`search_semantic` method)
- Test: `python/tests/test_session_tracker.py`

- [ ] **Step 1: Write the failing test**

Create `python/tests/test_session_tracker.py` with the first test — verifying `search_semantic` accepts `category` param:

```python
"""Tests for session summary feature."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock()
    return pool


@pytest.fixture
def memory_manager(mock_pool):
    from memory_manager import MemoryManager
    mgr = MemoryManager()
    mgr.pool = mock_pool
    return mgr


@pytest.mark.asyncio
async def test_search_semantic_with_category_filter(memory_manager, mock_pool):
    """search_semantic should add WHERE category=$N when category is passed."""
    mock_pool.fetch = AsyncMock(return_value=[])

    with patch("memory_manager.get_embedding", return_value=[0.1] * 768):
        results = await memory_manager.search_semantic(
            "test query", category="session_summary"
        )

    assert results == []
    # Verify the SQL contains category filter
    call_args = mock_pool.fetch.call_args
    sql = call_args[0][0]
    assert "category" in sql.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py::test_search_semantic_with_category_filter -v`
Expected: FAIL — `search_semantic()` doesn't accept `category` parameter

- [ ] **Step 3: Add `category` parameter to `search_semantic`**

In `python/memory_manager.py`, modify `search_semantic` signature and query:

```python
async def search_semantic(
    self,
    query: str,
    limit: int = 5,
    threshold: float = None,
    include_archived: bool = False,
    embedding: list[float] | None = None,
    category: str | None = None,
) -> list[dict]:
    """Search semantic memories by cosine similarity. Updates access tracking."""
    await self.connect()
    if embedding is None:
        embedding = get_embedding(query)
    if threshold is None:
        threshold = cfg.memory.similarity_threshold

    archive_filter = "" if include_archived else "AND archived = false"
    category_filter = ""
    params = [json.dumps(embedding), threshold, limit]

    if category:
        category_filter = f"AND category = ${len(params) + 1}"
        params.append(category)

    rows = await self.pool.fetch(
        f"""
        SELECT id, concept_name, content, category, keywords, archived, mood, lyume_mood, summary,
               last_accessed, access_count,
               1 - (embedding <=> $1::vector) AS similarity
        FROM memories_semantic
        WHERE 1 - (embedding <=> $1::vector) > $2 {archive_filter} {category_filter}
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        *params,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py::test_search_semantic_with_category_filter -v`
Expected: PASS

- [ ] **Step 5: Add `get_recent_summaries` method to MemoryManager**

This method retrieves session summaries chronologically (most recent first) — used for explicit "what did we do last time?" recall.

In `python/memory_manager.py`, add after `get_recent_lessons`:

```python
async def get_recent_summaries(self, limit: int = 3) -> list[dict]:
    """Get most recent session summaries, chronologically (newest first)."""
    await self.connect()
    rows = await self.pool.fetch(
        """
        SELECT id, concept_name, content, category, keywords,
               last_updated, last_accessed, access_count
        FROM memories_semantic
        WHERE category = 'session_summary' AND archived = false
        ORDER BY last_updated DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        {
            "id": str(row["id"]),
            "concept_name": row["concept_name"],
            "content": row["content"],
            "category": row["category"],
            "keywords": row["keywords"],
            "last_updated": row["last_updated"].isoformat(),
            "access_count": row["access_count"],
        }
        for row in rows
    ]
```

- [ ] **Step 6: Run all tests to verify no regression**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_manager.py python/tests/test_session_tracker.py
git commit -m "feat: add category filter to search_semantic + get_recent_summaries"
```

---

### Task 2: Add SESSION_RECALL patterns to intent_classifier.py

**Files:**
- Modify: `python/intent_classifier.py`
- Test: `python/tests/test_session_tracker.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `python/tests/test_session_tracker.py`:

```python
from intent_classifier import classify_user_intent


@pytest.mark.parametrize("text", [
    "що ми робили минулий раз?",
    "що ми обговорювали?",
    "нагадай що було в минулому чаті",
    "what did we do last session?",
    "what we discussed yesterday",
    "минулу сесію ми щось робили",
    "про що говорили вчора?",
    "previous chat",
    "last time we talked about",
    "what happened in our chat?",
])
def test_session_recall_detected(text):
    result = classify_user_intent(text)
    assert result["session_recall"] is True, f"Failed for: {text}"


@pytest.mark.parametrize("text", [
    "привіт",
    "як справи?",
    "запам'ятай що я люблю каву",
    "що ти знаєш про Python?",
])
def test_session_recall_not_triggered_on_regular(text):
    result = classify_user_intent(text)
    assert result.get("session_recall", False) is False, f"False positive for: {text}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py::test_session_recall_detected -v`
Expected: FAIL — `session_recall` key doesn't exist in result

- [ ] **Step 3: Add SESSION_RECALL_INTENT pattern and update classify_user_intent**

In `python/intent_classifier.py`, add pattern after `FAREWELL_PATTERN`:

```python
SESSION_RECALL_INTENT = re.compile(
    r"минулий (раз|чат|сесі)|що ми робили|що ми обговорювали|минулу сесію|"
    r"попередній чат|вчора робили|нагадай що було|про що говорили|що було в минулому|"
    r"last session|what did we do|previous chat|what we discussed|yesterday|last time|what happened",
    re.IGNORECASE,
)
```

In `classify_user_intent`, add to result dict and detection:

```python
# In result dict initialization:
result = {
    "save": False,
    "save_content": "",
    "forget": False,
    "forget_content": "",
    "recall": False,
    "session_recall": False,
    "feedback": None,
    "farewell": False,
}

# After farewell detection:
if SESSION_RECALL_INTENT.search(text):
    result["session_recall"] = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run existing classifier tests to verify no regression**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_intent_classifier.py -v`
Expected: ALL PASS (20/20)

- [ ] **Step 6: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/intent_classifier.py python/tests/test_session_tracker.py
git commit -m "feat: add session_recall intent pattern"
```

---

### Task 3: Add session_summary config to config.yaml

**Files:**
- Modify: `python/config.yaml`

- [ ] **Step 1: Add session summary settings to features section**

In `python/config.yaml`, append to `features:`:

```yaml
features:
  strip_think_tags: true
  marker_fallback: true
  session_summary: true
  summary_interval: 20
  summary_max_context: 30
  summary_buffer_cap: 60
  session_timeout: 1800
```

- [ ] **Step 2: Verify config loads correctly**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -c "from config import cfg; print(cfg.features.session_summary, cfg.features.summary_interval, cfg.features.session_timeout)"`
Expected: `True 20 1800`

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/config.yaml
git commit -m "feat: add session_summary config settings"
```

---

### Task 4: Create session_tracker.py

**Files:**
- Create: `python/session_tracker.py`
- Test: `python/tests/test_session_tracker.py` (append)

- [ ] **Step 1: Write failing tests for SessionTracker**

Append to `python/tests/test_session_tracker.py`:

```python
import time
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def tracker():
    with patch("session_tracker.cfg") as mock_cfg:
        mock_cfg.features.session_summary = True
        mock_cfg.features.summary_interval = 20
        mock_cfg.features.summary_max_context = 30
        mock_cfg.features.summary_buffer_cap = 60
        mock_cfg.features.session_timeout = 1800
        mock_cfg.lm_studio.url = "http://localhost:1234"
        mock_cfg.lm_studio.model_name = "test-model"
        mock_cfg.lm_studio.reflection_timeout = 120

        from session_tracker import SessionTracker
        mm_mock = AsyncMock()
        mm_mock.save_semantic = AsyncMock(return_value="test-id")
        headers = {"Authorization": "Bearer test"}
        t = SessionTracker(mm_mock, "http://localhost:1234", headers)
        yield t


def test_track_message_adds_to_buffer(tracker):
    tracker.track_message("user", "привіт")
    assert len(tracker._buffer) == 1
    assert tracker._buffer[0]["role"] == "user"
    assert tracker._buffer[0]["content"] == "привіт"


def test_track_message_increments_user_count(tracker):
    tracker.track_message("user", "msg1")
    tracker.track_message("assistant", "resp1")
    tracker.track_message("user", "msg2")
    assert tracker._user_msg_count == 2


def test_buffer_cap_sliding_window(tracker):
    tracker._buffer_cap = 5
    for i in range(8):
        tracker.track_message("user", f"msg{i}")
    assert len(tracker._buffer) == 5
    assert tracker._buffer[0]["content"] == "msg3"


def test_should_summarize_at_interval(tracker):
    tracker._summary_interval = 3
    tracker.track_message("user", "1")
    assert tracker.should_summarize() is False
    tracker.track_message("user", "2")
    assert tracker.should_summarize() is False
    tracker.track_message("user", "3")
    assert tracker.should_summarize() is True


def test_check_timeout_false_when_recent(tracker):
    tracker.track_message("user", "msg")
    assert tracker.check_timeout() is False


def test_check_timeout_true_after_expiry(tracker):
    tracker.track_message("user", "msg")
    tracker._last_message_time = time.monotonic() - 2000  # simulate 2000s ago
    assert tracker.check_timeout() is True


def test_check_timeout_false_on_first_message(tracker):
    """First message ever — no timeout (no previous session)."""
    assert tracker.check_timeout() is False


def test_start_new_session_clears_state(tracker):
    tracker.track_message("user", "1")
    tracker.track_message("user", "2")
    tracker.start_new_session()
    assert len(tracker._buffer) == 0
    assert tracker._user_msg_count == 0


@pytest.mark.asyncio
async def test_generate_summary_skips_short_sessions(tracker):
    """Sessions with < 3 messages should not generate summaries."""
    tracker.track_message("user", "hi")
    result = await tracker.generate_summary("periodic")
    assert result is None


@pytest.mark.asyncio
async def test_generate_summary_calls_llm_and_saves(tracker):
    """With enough messages, should call LLM and save to DB."""
    for i in range(5):
        tracker.track_message("user", f"msg{i}")
        tracker.track_message("assistant", f"resp{i}")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Summary of session"}}]
    }
    mock_response.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tracker.generate_summary("periodic")

    assert result is not None
    assert "Summary of session" in result
    tracker._memory_manager.save_semantic.assert_called_once()
    call_kwargs = tracker._memory_manager.save_semantic.call_args
    assert call_kwargs[1]["category"] == "session_summary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py::test_track_message_adds_to_buffer -v`
Expected: FAIL — `session_tracker` module doesn't exist

- [ ] **Step 3: Implement session_tracker.py**

Create `python/session_tracker.py`:

```python
"""
SessionTracker — tracks messages per session, generates LLM summaries.
Summaries stored as category='session_summary' in existing PostgreSQL.
"""

import time
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
            async with httpx.AsyncClient(timeout=cfg.lm_studio.reflection_timeout) as client:
                resp = await client.post(
                    f"{self._lm_studio_url}/v1/chat/completions",
                    headers=self._headers,
                    json={
                        "model": cfg.lm_studio.model_name,
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
                import re
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
```

- [ ] **Step 4: Run all session tracker tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_session_tracker.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/session_tracker.py python/tests/test_session_tracker.py
git commit -m "feat: add SessionTracker module with LLM summary generation"
```

---

### Task 5: Wire SessionTracker into memory_proxy.py

**Files:**
- Modify: `python/memory_proxy.py`

This task integrates session_tracker into the proxy request flow per spec:
1. On every request: `track_message("user", ...)` + check timeout
2. On every response: `track_message("assistant", ...)`
3. After response: check `should_summarize()`
4. On farewell: `generate_summary("farewell")` + `start_new_session()`
5. On session_recall: search with `category="session_summary"`

- [ ] **Step 1: Add imports and initialize SessionTracker**

At the top of `memory_proxy.py`, add import:

```python
from session_tracker import SessionTracker
```

After `mm = MemoryManager()` (line 143), add:

```python
session_tracker: SessionTracker | None = None
```

In `lifespan()` (after `await mm.connect()`, line 179), add:

```python
global session_tracker
if cfg.features.session_summary:
    session_tracker = SessionTracker(mm, LM_STUDIO_URL, LM_STUDIO_HEADERS)
    print("[session] Session tracker enabled", flush=True)
```

- [ ] **Step 2: Wire into chat_completions — user tracking + timeout**

In `chat_completions()` function, after `user_query = extract_user_query(messages)` (line 811), add:

```python
# Session tracking
if session_tracker and user_query:
    if session_tracker.check_timeout():
        print("[session] Timeout detected, summarizing old session...", flush=True)
        asyncio.create_task(session_tracker.generate_summary("timeout"))
        session_tracker.start_new_session()
    session_tracker.track_message("user", user_query)
```

- [ ] **Step 3: Wire session_recall intent into inject_memories**

In `inject_memories()` function, after computing `user_query` (line 597), add session recall logic:

```python
# Session recall — explicit "what did we do last time?"
user_intent = classify_user_intent(user_query)
if user_intent.get("session_recall") and session_tracker:
    session_memories = await mm.get_recent_summaries(limit=3)
    if session_memories:
        # Format as session history block
        lines = [
            "\n\n<session_history>",
            "Previous session summaries (chronological):",
            "",
        ]
        for s in reversed(session_memories):
            lines.append(f"- {s['content']}")
        lines.append("</session_history>")
        session_block = "\n".join(lines)
        # Inject into system prompt
        if messages and messages[0].get("role") == "system":
            messages[0] = {
                **messages[0],
                "content": messages[0]["content"] + session_block,
            }
        else:
            messages.insert(0, {"role": "system", "content": session_block.strip()})
        print(f"[session] Recalled {len(session_memories)} session summaries", flush=True)
```

- [ ] **Step 4: Wire response tracking + periodic summary**

In `chat_completions()` streaming path — inside `generate()`, before `yield "data: [DONE]\n\n"` (around line 906), add:

```python
# Track assistant response
if session_tracker:
    session_tracker.track_message("assistant", full_response[:500])
    if session_tracker.should_summarize():
        asyncio.create_task(session_tracker.generate_summary("periodic"))
```

In the non-streaming path, after `await process_response(raw, ...)` (around line 970), add same logic:

```python
# Track assistant response
if session_tracker:
    session_tracker.track_message("assistant", full_response[:500])
    if session_tracker.should_summarize():
        asyncio.create_task(session_tracker.generate_summary("periodic"))
```

- [ ] **Step 5: Wire farewell summary**

In streaming path, after the existing farewell reflection block (around line 905), add:

```python
if is_farewell and session_tracker:
    asyncio.create_task(session_tracker.generate_summary("farewell"))
    session_tracker.start_new_session()
```

In non-streaming path, after the existing farewell reflection block (around line 976), add same:

```python
if is_farewell and session_tracker:
    asyncio.create_task(session_tracker.generate_summary("farewell"))
    session_tracker.start_new_session()
```

- [ ] **Step 6: Add session_tracker to health check**

In `health_check()`, add module check:

```python
# Session tracker
if session_tracker:
    modules["session_tracker"] = {
        "status": "OK",
        "detail": f"buffer={len(session_tracker._buffer)}, msgs={session_tracker._user_msg_count}",
    }
```

- [ ] **Step 7: Manual smoke test**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -c "from memory_proxy import app; print('Import OK')"`
Expected: `Import OK` (no import errors)

- [ ] **Step 8: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_proxy.py
git commit -m "feat: wire SessionTracker into proxy request flow"
```

---

### Task 6: Update AGENTS.md and MEMORY.md

**Files:**
- Modify: `AGENTS.md`
- Modify: `MEMORY.md` (in workspace-lyume root, if it exists — check first)

- [ ] **Step 1: Update AGENTS.md**

In `AGENTS.md`, under "### Memory is Automatic" section, add:

```
- **Session summaries** are saved automatically — ask about any previous conversation
```

Remove references to `memory/YYYY-MM-DD.md` from "## Session Start" — replace steps 3-4 with:

```
3. Memory is automatic — the proxy handles recall, saving, and session summaries
```

Remove from "## Memory" section:
- "Daily notes" bullet point
- "Long-term: MEMORY.md" bullet point
- The "### MEMORY.md — Long-Term Memory" subsection

- [ ] **Step 2: Update or create MEMORY.md in workspace root**

If `MEMORY.md` exists in workspace root, replace content. If not, create with:

```markdown
# Memory

All memory is managed automatically by the proxy.
- Facts, preferences, and corrections are saved when detected
- Session summaries are generated at the end of each conversation
- Ask about any previous session and the AI will recall it

No manual memory management needed.
```

- [ ] **Step 3: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add AGENTS.md
git add MEMORY.md 2>/dev/null  # may not exist yet
git commit -m "docs: update AGENTS.md for automatic session summaries"
```

---

### Task 7: Integration test — full flow

- [ ] **Step 1: Run all tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS — both `test_intent_classifier.py` and `test_session_tracker.py`

- [ ] **Step 2: Start proxy and verify health**

Run: `cd /home/tarik/.openclaw/workspace-lyume && timeout 5 python -c "import uvicorn; from memory_proxy import app; print('Proxy starts OK')" || true`
Expected: No import errors

- [ ] **Step 3: Verify config**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -c "from config import cfg; assert cfg.features.session_summary == True; assert cfg.features.summary_interval == 20; print('Config OK')"`
Expected: `Config OK`
