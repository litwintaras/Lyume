import asyncio
import asyncpg
import pytest
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import json

# Add python directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from memory_manager import MemoryManager

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "user": "postgres",
    "database": "ai_memory",
}


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_merged_into_column_exists():
    # Initialize MemoryManager to trigger migrations
    mm = MemoryManager()
    await mm.connect()
    await mm.close()

    # Now verify columns exist
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'memories_semantic' AND column_name = 'merged_into'"
        )
        assert row is not None, "merged_into column missing from memories_semantic"

        row = await conn.fetchrow(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'lessons' AND column_name = 'merged_into'"
        )
        assert row is not None, "merged_into column missing from lessons"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_search_semantic_cooldown_filters_recent():
    """Auto recall should exclude memories accessed within 180 days."""
    from memory_manager import MemoryManager

    mgr = MemoryManager()
    mgr.pool = AsyncMock()

    # Mock: return one memory that was accessed 10 days ago (within cooldown)
    mock_row = {
        "id": "aaaaaaaa-1111-1111-1111-111111111111",
        "concept_name": "test",
        "content": "recently accessed memory",
        "category": "general",
        "keywords": [],
        "archived": False,
        "mood": None,
        "lyume_mood": None,
        "summary": None,
        "last_accessed": datetime.now(timezone.utc) - timedelta(days=10),
        "access_count": 5,
        "similarity": 0.9,
    }
    mgr.pool.fetch = AsyncMock(return_value=[mock_row])
    mgr.pool.execute = AsyncMock()

    # explicit_recall=False → cooldown applies → SQL should include cooldown filter
    results = await mgr.search_semantic(
        "test query",
        embedding=[0.1] * 768,
        explicit_recall=False,
    )
    # Check that the SQL query contains the cooldown filter
    sql_call = mgr.pool.fetch.call_args[0][0]
    assert "last_accessed" in sql_call or "cooldown" in sql_call.lower() or "180 days" in sql_call


@pytest.mark.asyncio
async def test_search_semantic_explicit_bypasses_cooldown():
    """Explicit recall should NOT filter by cooldown."""
    from memory_manager import MemoryManager

    mgr = MemoryManager()
    mgr.pool = AsyncMock()
    mgr.pool.fetch = AsyncMock(return_value=[])
    mgr.pool.execute = AsyncMock()

    await mgr.search_semantic(
        "test query",
        embedding=[0.1] * 768,
        explicit_recall=True,
    )
    sql_call = mgr.pool.fetch.call_args[0][0]
    # Explicit recall — no cooldown filter in WHERE
    assert "180 days" not in sql_call


@pytest.mark.asyncio
async def test_search_lessons_cooldown():
    """search_lessons with explicit_recall=False should include cooldown filter."""
    from memory_manager import MemoryManager

    mgr = MemoryManager()
    mgr.pool = AsyncMock()
    mgr.pool.fetch = AsyncMock(return_value=[])
    mgr.pool.execute = AsyncMock()

    await mgr.search_lessons(
        "test query",
        embedding=[0.1] * 768,
        explicit_recall=False,
    )
    sql_call = mgr.pool.fetch.call_args[0][0]
    assert "last_triggered" in sql_call and "make_interval" in sql_call, \
        f"Missing cooldown filter in search_lessons SQL: {sql_call[:100]}"


@pytest.mark.asyncio
async def test_search_lessons_explicit_no_cooldown():
    """search_lessons with explicit_recall=True should NOT have cooldown filter."""
    from memory_manager import MemoryManager

    mgr = MemoryManager()
    mgr.pool = AsyncMock()
    mgr.pool.fetch = AsyncMock(return_value=[])
    mgr.pool.execute = AsyncMock()

    await mgr.search_lessons(
        "test query",
        embedding=[0.1] * 768,
        explicit_recall=True,
    )
    sql_call = mgr.pool.fetch.call_args[0][0]
    assert "last_triggered" not in sql_call


@pytest.mark.asyncio
async def test_search_lessons_balanced_cooldown():
    """Auto recall should exclude lessons triggered within 180 days."""
    from memory_manager import MemoryManager

    mgr = MemoryManager()
    mgr.pool = AsyncMock()
    mgr.pool.fetch = AsyncMock(return_value=[])
    mgr.pool.execute = AsyncMock()

    await mgr.search_lessons_balanced(
        "test query",
        embedding=[0.1] * 768,
        explicit_recall=False,
    )
    # Both SQL queries (top-3 and cold) should contain cooldown filter
    calls = mgr.pool.fetch.call_args_list
    for call in calls:
        sql = call[0][0]
        assert "last_triggered" in sql and "make_interval(days" in sql, f"Missing cooldown in: {sql[:80]}"


def test_union_find_basic():
    from memory_consolidator import UnionFind

    uf = UnionFind()
    uf.union("a", "b")
    uf.union("b", "c")
    uf.union("d", "e")

    clusters = uf.clusters()
    assert len(clusters) == 2
    assert {"a", "b", "c"} in [set(c) for c in clusters]
    assert {"d", "e"} in [set(c) for c in clusters]


def test_union_find_single_elements():
    from memory_consolidator import UnionFind

    uf = UnionFind()
    uf.add("a")
    uf.add("b")

    clusters = uf.clusters()
    # Single elements = no clusters (or clusters of size 1)
    assert all(len(c) == 1 for c in clusters)


def test_normalize_embedding():
    """Embedding should be normalized to string regardless of input type."""
    from memory_consolidator import _normalize_embedding

    # String input — returned as-is
    assert _normalize_embedding("[1.0, 2.0]") == "[1.0, 2.0]"

    # List input — converted to JSON string
    assert _normalize_embedding([1.0, 2.0]) == "[1.0, 2.0]"

    # Numpy-like (list of floats from asyncpg) — converted
    import array
    arr = array.array('f', [1.0, 2.0])
    assert isinstance(_normalize_embedding(list(arr)), str)


@pytest.mark.asyncio
async def test_find_semantic_clusters():
    """Should group memories with cosine similarity > threshold."""
    from memory_consolidator import find_semantic_clusters

    mock_pool = AsyncMock()

    id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    id_b = "aaaaaaaa-0000-0000-0000-000000000002"

    # Self-join returns similar pairs
    mock_pool.fetch = AsyncMock(return_value=[
        {"id_a": id_a, "id_b": id_b, "similarity": 0.95},
    ])

    clusters = await find_semantic_clusters(mock_pool, threshold=0.85)
    multi = [c for c in clusters if len(c) > 1]
    assert len(multi) == 1
    assert set(multi[0]) == {id_a, id_b}


@pytest.mark.asyncio
async def test_find_semantic_clusters_single_query():
    """find_semantic_clusters should use ONE query, not O(n)."""
    from memory_consolidator import find_semantic_clusters

    mock_pool = AsyncMock()

    id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    id_b = "aaaaaaaa-0000-0000-0000-000000000002"

    mock_pool.fetch = AsyncMock(return_value=[
        {"id_a": id_a, "id_b": id_b, "similarity": 0.95},
    ])

    clusters = await find_semantic_clusters(mock_pool, threshold=0.85)
    assert mock_pool.fetch.call_count == 1
    multi = [c for c in clusters if len(c) > 1]
    assert len(multi) == 1
    assert set(multi[0]) == {id_a, id_b}


@pytest.mark.asyncio
async def test_aggregate_lesson_cluster():
    from memory_consolidator import aggregate_lesson_cluster
    import uuid as uuid_mod

    mock_pool = AsyncMock()

    id_a = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    id_b = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000002")

    mock_pool.fetch = AsyncMock(return_value=[
        {"id": id_a, "trigger_count": 10},
        {"id": id_b, "trigger_count": 5},
    ])

    # Setup connection mock
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    mock_transaction = AsyncMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_transaction)
    mock_transaction.__aexit__ = AsyncMock(return_value=False)

    mock_conn.transaction = MagicMock(return_value=mock_transaction)
    mock_conn.execute = AsyncMock()

    # pool.acquire returns a context manager (not a coroutine)
    class MockContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    def mock_acquire():
        return MockContextManager()

    mock_pool.acquire = mock_acquire

    result = await aggregate_lesson_cluster(
        mock_pool,
        [str(id_a), str(id_b)],
    )
    assert result is True
    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("15" in c for c in calls), "trigger_count should be summed to 15"


@pytest.mark.asyncio
async def test_archive_stale_uses_last_updated():
    """Stale archive should check last_updated, not last_accessed."""
    from memory_consolidator import archive_stale

    mock_pool = AsyncMock()
    mock_pool.execute = AsyncMock(return_value="UPDATE 5")

    count = await archive_stale(mock_pool, days=365)
    assert count == 5

    sql = mock_pool.execute.call_args[0][0]
    assert "last_updated" in sql, "Should use last_updated, not last_accessed"
    assert "365" in str(mock_pool.execute.call_args) or "days" in sql


@pytest.mark.asyncio
async def test_get_embedding_async_exists():
    """get_embedding_async should exist and be a coroutine."""
    from memory_manager import get_embedding_async
    import inspect
    assert inspect.iscoroutinefunction(get_embedding_async)


@pytest.mark.asyncio
async def test_merge_semantic_cluster_llm_failure():
    """merge_semantic_cluster should return False when LLM synthesis fails."""
    from memory_consolidator import merge_semantic_cluster
    import uuid as uuid_mod

    mock_pool = AsyncMock()

    id_a = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    id_b = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000002")

    mock_pool.fetch = AsyncMock(return_value=[
        {"id": id_a, "content": "memory one", "last_updated": datetime.now(timezone.utc)},
        {"id": id_b, "content": "memory two", "last_updated": datetime.now(timezone.utc)},
    ])

    with patch("memory_consolidator.llm_synthesize", AsyncMock(return_value=None)):
        result = await merge_semantic_cluster(
            mock_pool,
            [str(id_a), str(id_b)],
            "http://fake:1234",
            "fake-model",
        )
    assert result is False


@pytest.mark.asyncio
async def test_consolidation_skips_with_few_memories():
    """run_consolidation should skip when < 3 active memories."""
    from memory_consolidator import run_consolidation

    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"cnt": 2})
    mock_pool.close = AsyncMock()

    with patch("memory_consolidator.asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
        with patch("memory_consolidator.cfg") as mock_cfg:
            mock_cfg.consolidation.enabled = True
            await run_consolidation()

    # Should NOT call find_semantic_clusters (skipped early)
    mock_pool.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_merge_semantic_cluster_single_row():
    """merge_semantic_cluster should return False for < 2 rows."""
    from memory_consolidator import merge_semantic_cluster
    import uuid as uuid_mod

    mock_pool = AsyncMock()
    id_a = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000001")

    mock_pool.fetch = AsyncMock(return_value=[
        {"id": id_a, "content": "only one", "last_updated": datetime.now(timezone.utc)},
    ])

    result = await merge_semantic_cluster(
        mock_pool,
        [str(id_a)],
        "http://fake:1234",
        "fake-model",
    )
    assert result is False
