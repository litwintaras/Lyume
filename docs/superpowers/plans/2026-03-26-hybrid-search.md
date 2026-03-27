# Hybrid Search Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add BM25 + Vector hybrid search via RRF to memory_manager.py
**Spec:** `docs/superpowers/specs/2026-03-26-hybrid-search-design.md`
**Tech:** Python 3.12, asyncpg, PostgreSQL tsvector, pgvector

---

### Task 1: DB Migration — tsvector column + trigger + index

**Files:**
- Modify: `python/memory_manager.py` — `connect()` method

- [ ] **Step 1: Write failing test**

Create `python/tests/test_hybrid_search.py`:

```python
import asyncio
import asyncpg
import pytest

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
async def test_search_vector_column_exists():
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'memories_semantic' AND column_name = 'search_vector'"
        )
        assert row is not None, "search_vector column missing from memories_semantic"
    finally:
        await conn.close()

@pytest.mark.asyncio
async def test_search_vector_trigger_exists():
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE trigger_name = 'memories_search_vector_update'"
        )
        assert row is not None, "memories_search_vector_update trigger missing"
    finally:
        await conn.close()
```

- [ ] **Step 2: Run test — expect FAIL**

`cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_hybrid_search.py -v`

- [ ] **Step 3: Add migration to MemoryManager.connect()**

After the `merged_into` migration in `connect()`, add:

```python
await conn.execute("""
    DO $$ BEGIN
        -- Add search_vector column
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='memories_semantic' AND column_name='search_vector'
        ) THEN
            ALTER TABLE memories_semantic ADD COLUMN search_vector tsvector;
            UPDATE memories_semantic SET search_vector = to_tsvector('simple', coalesce(content, ''));
        END IF;

        -- Create trigger function
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS trigger AS $fn$
        BEGIN
            NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
            RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;

        -- Create trigger if not exists
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.triggers
            WHERE trigger_name = 'memories_search_vector_update'
        ) THEN
            CREATE TRIGGER memories_search_vector_update
            BEFORE INSERT OR UPDATE ON memories_semantic
            FOR EACH ROW EXECUTE FUNCTION update_search_vector();
        END IF;

        -- Create GIN index if not exists
        IF NOT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'memories_semantic' AND indexname = 'memories_search_vector_idx'
        ) THEN
            CREATE INDEX memories_search_vector_idx ON memories_semantic USING GIN(search_vector);
        END IF;
    END $$;
""")
```

- [ ] **Step 4: Run test — expect PASS**

---

### Task 2: Config fields

**Files:**
- Modify: `python/config.py` — MemoryConfig dataclass
- Modify: `python/config.yaml` — memory section

- [ ] **Step 1: Write failing test**

Add to `tests/test_hybrid_search.py`:

```python
from config import cfg

def test_hybrid_search_config_defaults():
    assert hasattr(cfg.memory, 'hybrid_search')
    assert hasattr(cfg.memory, 'hybrid_rrf_k')
    assert hasattr(cfg.memory, 'hybrid_bm25_limit')
    assert cfg.memory.hybrid_rrf_k == 60
    assert cfg.memory.hybrid_bm25_limit == 10
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add fields to config.py MemoryConfig dataclass**

```python
hybrid_search: bool = True
hybrid_rrf_k: int = 60
hybrid_bm25_limit: int = 10
```

- [ ] **Step 4: Add to config.yaml memory section**

```yaml
hybrid_search: true
hybrid_rrf_k: 60
hybrid_bm25_limit: 10
```

- [ ] **Step 5: Run test — expect PASS**

---

### Task 3: search_bm25_raw() method

**Files:**
- Modify: `python/memory_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_hybrid_search.py`:

```python
@pytest.mark.asyncio
async def test_search_bm25_raw_returns_list():
    from memory_manager import MemoryManager
    mm = MemoryManager()
    await mm.connect()
    try:
        results = await mm.search_bm25_raw("test", limit=5)
        assert isinstance(results, list)
        # each result has id and content
        for r in results:
            assert 'id' in r
            assert 'content' in r
    finally:
        await mm.pool.close()
        mm.pool = None

@pytest.mark.asyncio
async def test_search_bm25_raw_empty_query():
    from memory_manager import MemoryManager
    mm = MemoryManager()
    await mm.connect()
    try:
        results = await mm.search_bm25_raw("", limit=5)
        assert results == []
    finally:
        await mm.pool.close()
        mm.pool = None
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement search_bm25_raw()**

```python
async def search_bm25_raw(self, query: str, limit: int = 10) -> list[dict]:
    """BM25 full-text search via tsvector. Returns rows ordered by ts_rank."""
    if not query.strip():
        return []
    await self.connect()
    async with self.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, ts_rank(search_vector, query) AS bm25_score
            FROM memories_semantic,
                 to_tsquery('simple', $1) query
            WHERE archived = false
              AND search_vector @@ query
            ORDER BY bm25_score DESC
            LIMIT $2
            """,
            self._to_tsquery_safe(query),
            limit,
        )
    return [dict(r) for r in rows]

@staticmethod
def _to_tsquery_safe(query: str) -> str:
    """Convert raw query string to tsquery-safe format (AND of tokens)."""
    tokens = [t.strip() for t in query.split() if t.strip()]
    return ' & '.join(tokens) if tokens else ''
```

- [ ] **Step 4: Run test — expect PASS**

---

### Task 4: rrf_merge() function

**Files:**
- Modify: `python/memory_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_hybrid_search.py`:

```python
def test_rrf_merge_combines_results():
    from memory_manager import rrf_merge
    vec = [{'id': 'a', 'content': 'foo'}, {'id': 'b', 'content': 'bar'}]
    bm25 = [{'id': 'b', 'content': 'bar'}, {'id': 'c', 'content': 'baz'}]
    merged = rrf_merge(vec, bm25, k=60)
    ids = [r['id'] for r in merged]
    assert 'b' in ids  # appears in both → highest RRF score
    assert ids[0] == 'b'

def test_rrf_merge_empty_inputs():
    from memory_manager import rrf_merge
    assert rrf_merge([], [], k=60) == []
    assert rrf_merge([{'id': 'a', 'content': 'x'}], [], k=60) == [{'id': 'a', 'content': 'x'}]
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement rrf_merge() as module-level function**

```python
def rrf_merge(vector_results: list[dict], bm25_results: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: merge two ranked lists by id."""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}

    for rank, row in enumerate(vector_results):
        rid = str(row['id'])
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
        rows[rid] = row

    for rank, row in enumerate(bm25_results):
        rid = str(row['id'])
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
        if rid not in rows:
            rows[rid] = row

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [rows[rid] for rid in sorted_ids]
```

- [ ] **Step 4: Run test — expect PASS**

---

### Task 5: search_hybrid() method

**Files:**
- Modify: `python/memory_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_hybrid_search.py`:

```python
@pytest.mark.asyncio
async def test_search_hybrid_returns_list():
    from memory_manager import MemoryManager
    mm = MemoryManager()
    await mm.connect()
    try:
        results = await mm.search_hybrid("test memory", limit=3, explicit_recall=False)
        assert isinstance(results, list)
        assert len(results) <= 3
    finally:
        await mm.pool.close()
        mm.pool = None

@pytest.mark.asyncio
async def test_search_hybrid_respects_cooldown():
    from memory_manager import MemoryManager
    mm = MemoryManager()
    await mm.connect()
    try:
        # explicit=False should apply cooldown (same as search_semantic)
        r1 = await mm.search_hybrid("test", limit=5, explicit_recall=False)
        r2 = await mm.search_hybrid("test", limit=5, explicit_recall=True)
        # explicit should return >= implicit (cooldown may filter some)
        assert len(r2) >= len(r1)
    finally:
        await mm.pool.close()
        mm.pool = None
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement search_hybrid()**

```python
async def search_hybrid(self, query: str, limit: int = None, explicit_recall: bool = False) -> list[dict]:
    """Hybrid search: vector + BM25 merged via RRF."""
    if limit is None:
        limit = cfg.memory.search_limit
    candidate_limit = cfg.memory.hybrid_bm25_limit
    k = cfg.memory.hybrid_rrf_k

    # Get candidates from both sources
    vector_results = await self.search_semantic_raw(query, limit=candidate_limit, explicit_recall=explicit_recall)
    bm25_results = await self.search_bm25_raw(query, limit=candidate_limit)

    # BM25 results also need cooldown filter if not explicit
    if not explicit_recall:
        bm25_results = await self._apply_cooldown_filter(bm25_results)

    merged = rrf_merge(vector_results, bm25_results, k=k)
    return merged[:limit]
```

Note: `search_semantic_raw()` is a new internal method — extract the SQL query part from `search_semantic()` without the final formatting. `_apply_cooldown_filter()` filters rows where `last_accessed` is within cooldown window.

- [ ] **Step 4: Run test — expect PASS**

---

### Task 6: Proxy integration

**Files:**
- Modify: `python/memory_proxy.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_hybrid_search.py`:

```python
def test_hybrid_search_config_enabled_by_default():
    from config import cfg
    assert cfg.memory.hybrid_search is True
```

- [ ] **Step 2: In memory_proxy.py**, find where `search_semantic()` is called for automatic context recall, replace with:

```python
if cfg.memory.hybrid_search:
    memories = await mm.search_hybrid(user_text, explicit_recall=is_explicit)
else:
    memories = await mm.search_semantic(user_text, explicit_recall=is_explicit)
```

- [ ] **Step 3: Run full test suite**

`cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/ -v`

All tests must pass.

---

### Summary

| Task | What | Files |
|------|------|-------|
| 1 | DB migration: tsvector column + trigger + GIN index | memory_manager.py |
| 2 | Config: hybrid_search, hybrid_rrf_k, hybrid_bm25_limit | config.py, config.yaml |
| 3 | search_bm25_raw() | memory_manager.py |
| 4 | rrf_merge() | memory_manager.py |
| 5 | search_hybrid() | memory_manager.py |
| 6 | Proxy routing | memory_proxy.py |
