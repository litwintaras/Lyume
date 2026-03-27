import asyncio
import asyncpg
import pytest
from config import cfg

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "user": "postgres",
    "database": "ai_memory",
}


@pytest.mark.asyncio
async def test_search_vector_column_exists():
    """Перевірити що колонка search_vector існує у memories_semantic."""
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'memories_semantic' AND column_name = 'search_vector'"
        )
        assert row is not None, "search_vector column missing"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_search_vector_trigger_exists():
    """Перевірити що тригер для оновлення search_vector існує."""
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE trigger_name = 'memories_search_vector_update'"
        )
        assert row is not None, "trigger memories_search_vector_update missing"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_search_vector_gin_index_exists():
    """Перевірити що GIN індекс для search_vector існує."""
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'memories_semantic' AND indexname = 'memories_search_vector_idx'"
        )
        assert row is not None, "GIN index memories_search_vector_idx missing"
    finally:
        await conn.close()


def test_hybrid_search_config_values():
    """Перевірити що конфіг має значення для гібридного пошуку."""
    assert cfg.memory.hybrid_search is True
    assert cfg.memory.hybrid_rrf_k == 60
    assert cfg.memory.hybrid_bm25_limit == 10


@pytest.mark.asyncio
async def test_search_bm25_raw_returns_list():
    """Перевірити що search_bm25_raw повертає список."""
    from memory_manager import MemoryManager
    mm = MemoryManager()
    try:
        # Просто перевіримо що метод повертає список
        # Навіть якщо результатів немає
        results = await mm.search_bm25_raw("test query that definitely does not exist", limit=5)
        assert isinstance(results, list)
    finally:
        if mm.pool:
            await mm.pool.close()
            mm.pool = None


@pytest.mark.asyncio
async def test_search_bm25_raw_empty_query():
    """Перевірити що search_bm25_raw обробляє пусту query."""
    from memory_manager import MemoryManager
    mm = MemoryManager()
    try:
        results = await mm.search_bm25_raw("", limit=5)
        assert results == []
        results = await mm.search_bm25_raw("   ", limit=5)
        assert results == []
    finally:
        if mm.pool:
            await mm.pool.close()
            mm.pool = None


def test_rrf_merge_combines_results():
    """Перевірити що RRF об'єднує результати правильно."""
    from memory_manager import rrf_merge
    vec = [{'id': 'a', 'content': 'foo'}, {'id': 'b', 'content': 'bar'}]
    bm25 = [{'id': 'b', 'content': 'bar'}, {'id': 'c', 'content': 'baz'}]
    merged = rrf_merge(vec, bm25, k=60)
    ids = [r['id'] for r in merged]
    assert ids[0] == 'b', f"Expected 'b' first (in both lists), got {ids[0]}"
    assert 'a' in ids
    assert 'c' in ids


def test_rrf_merge_empty():
    """Перевірити RRF з порожніми списками."""
    from memory_manager import rrf_merge
    assert rrf_merge([], [], k=60) == []
    result = rrf_merge([{'id': 'a', 'content': 'x'}], [], k=60)
    assert len(result) == 1
    assert result[0]['id'] == 'a'


@pytest.mark.asyncio
async def test_search_hybrid_returns_list():
    """Перевірити що search_hybrid повертає список і дотримується limit."""
    from memory_manager import MemoryManager
    mm = MemoryManager()
    try:
        results = await mm.search_hybrid("test memory", limit=3, explicit_recall=False)
        assert isinstance(results, list)
        assert len(results) <= 3
    finally:
        if mm.pool:
            await mm.pool.close()
            mm.pool = None
