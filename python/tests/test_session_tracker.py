"""Tests for session summary feature."""
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intent_classifier import classify_user_intent

# Mock heavy dependencies before importing memory_manager
_llama_mock = MagicMock()
sys.modules.setdefault("llama_cpp", _llama_mock)

# Mock config module
_cfg_mock = MagicMock()
_cfg_mock.cfg = MagicMock()
_cfg_mock.cfg.memory.similarity_threshold = 0.3
_cfg_mock.cfg.memory.dedup_similarity = 0.9
_cfg_mock.cfg.memory.archive_similarity = 0.8
_cfg_mock.cfg.embedding.model_path = "/fake"
_cfg_mock.cfg.embedding.n_ctx = 512
_cfg_mock.cfg.embedding.n_gpu_layers = 0
_cfg_mock.cfg.database.host = "localhost"
_cfg_mock.cfg.database.port = 5432
_cfg_mock.cfg.database.user = "test"
_cfg_mock.cfg.database.name = "test"
_cfg_mock.cfg.database.pool_min = 1
_cfg_mock.cfg.database.pool_max = 2
sys.modules.setdefault("config", _cfg_mock)


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


@pytest.fixture
def tracker():
    with patch("session_tracker.cfg") as mock_cfg:
        mock_cfg.features.session_summary = True
        mock_cfg.features.summary_interval = 20
        mock_cfg.features.summary_max_context = 30
        mock_cfg.features.summary_buffer_cap = 60
        mock_cfg.features.session_timeout = 1800
        mock_cfg.llm.url = "http://localhost:1234"
        mock_cfg.llm.model = "test-model"
        mock_cfg.llm.reflection_timeout = 120

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


def test_should_summarize_always_false(tracker):
    """Session summary is disabled — should never trigger."""
    tracker._summary_interval = 3
    tracker.track_message("user", "1")
    tracker.track_message("user", "2")
    tracker.track_message("user", "3")
    assert tracker.should_summarize() is False


def test_check_timeout_false_when_recent(tracker):
    tracker.track_message("user", "msg")
    assert tracker.check_timeout() is False


def test_check_timeout_true_after_expiry(tracker):
    tracker.track_message("user", "msg")
    tracker._last_message_time = time.monotonic() - 2000
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
async def test_generate_summary_is_noop(tracker):
    """generate_summary no longer calls LLM — returns None immediately."""
    for i in range(5):
        tracker.track_message("user", f"msg{i}")
        tracker.track_message("assistant", f"resp{i}")

    result = await tracker.generate_summary("periodic")
    assert result is None
    tracker._memory_manager.save_semantic.assert_not_called()
