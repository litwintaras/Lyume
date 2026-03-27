# Lyume Bugfix Batch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 known bugs from Step B code review in memory_consolidator.py and memory_manager.py.

**Architecture:** All changes are in the `python/` directory. Bugs are independent — each task is self-contained. Tests run with `pytest` from `python/tests/`.

**Tech Stack:** Python 3.11+, asyncpg, asyncio, pytest, pytest-asyncio

**Working directory:** `/home/tarik/.openclaw/workspace-lyume`

---

### Task 1: I2 — Normalize embedding type once on input

**Bug:** `find_semantic_clusters()` and `find_lesson_clusters()` both have a fragile `isinstance` check on every row: `row["embedding"] if isinstance(row["embedding"], str) else json.dumps(list(row["embedding"]))`. This is duplicated and brittle.

**Files:**
- Modify: `python/memory_consolidator.py:83` and `python/memory_consolidator.py:200`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test for embedding normalization**

```python
# In python/tests/test_memory_consolidator.py

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_normalize_embedding -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_embedding'`

- [ ] **Step 3: Write _normalize_embedding helper and use it**

In `python/memory_consolidator.py`, add after the imports (line 20):

```python
def _normalize_embedding(emb) -> str:
    """Convert embedding to JSON string regardless of input type."""
    if isinstance(emb, str):
        return emb
    return json.dumps(list(emb))
```

Replace line 83:
```python
# OLD: row["embedding"] if isinstance(row["embedding"], str) else json.dumps(list(row["embedding"])),
# NEW:
_normalize_embedding(row["embedding"]),
```

Replace line 200:
```python
# OLD: row["embedding"] if isinstance(row["embedding"], str) else json.dumps(list(row["embedding"])),
# NEW:
_normalize_embedding(row["embedding"]),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_normalize_embedding -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "fix: normalize embedding type with helper instead of inline isinstance"
```

---

### Task 2: S4 — Add cooldown filter to search_lessons()

**Bug:** `search_lessons()` doesn't have a cooldown filter, unlike `search_lessons_balanced()`. Auto-recall can return lessons that were just triggered.

**Files:**
- Modify: `python/memory_manager.py:520-572`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test**

```python
# In python/tests/test_memory_consolidator.py

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_search_lessons_cooldown -v`
Expected: FAIL — `search_lessons()` doesn't accept `embedding` or `explicit_recall` params

- [ ] **Step 3: Add cooldown filter and embedding param to search_lessons()**

In `python/memory_manager.py`, modify `search_lessons()` (line 520):

```python
    async def search_lessons(
        self,
        query: str,
        limit: int = 3,
        threshold: float = None,
        embedding: list[float] | None = None,
        explicit_recall: bool = True,
    ) -> list[dict]:
        """Search lessons by situation similarity. Updates trigger tracking."""
        await self.connect()
        if embedding is None:
            embedding = get_embedding(query)
        if threshold is None:
            threshold = cfg.lessons.similarity_threshold
        elo_floor = getattr(cfg.lessons, 'elo_floor', 20)
        emb_json = json.dumps(embedding)

        cooldown_filter = ""
        params = [emb_json, threshold, limit, elo_floor]
        if not explicit_recall:
            cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
            cooldown_filter = f"AND (last_triggered IS NULL OR last_triggered < now() - make_interval(days => ${len(params) + 1}))"
            params.append(cooldown_days)

        rows = await self.pool.fetch(
            f"""
            SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM lessons
            WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true AND elo_rating >= $4 {cooldown_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            *params,
        )

        if rows:
            ids = [row["id"] for row in rows]
            await self.pool.execute(
                """
                UPDATE lessons
                SET last_triggered = $1, trigger_count = trigger_count + 1
                WHERE id = ANY($2)
                """,
                datetime.now(timezone.utc),
                ids,
            )

        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "trigger_context": row["trigger_context"],
                "category": row["category"],
                "similarity": round(float(row["similarity"]), 4),
                "mood": row["mood"],
                "lyume_mood": row["lyume_mood"],
                "summary": row["summary"],
            }
            for row in rows
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_search_lessons_cooldown python/tests/test_memory_consolidator.py::test_search_lessons_explicit_no_cooldown -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_manager.py python/tests/test_memory_consolidator.py
git commit -m "fix: add cooldown filter to search_lessons() matching search_lessons_balanced()"
```

---

### Task 3: I1 — Replace O(n) SQL queries in find_semantic_clusters() with self-join

**Bug:** `find_semantic_clusters()` runs one query per row (O(n) queries). For 100 memories = 100 queries. Replace with a single self-join.

**Files:**
- Modify: `python/memory_consolidator.py:60-90`
- Modify: `python/memory_consolidator.py:177-206` (same fix for `find_lesson_clusters`)
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test that verifies single query**

```python
# In python/tests/test_memory_consolidator.py

@pytest.mark.asyncio
async def test_find_semantic_clusters_single_query():
    """find_semantic_clusters should use ONE query, not O(n)."""
    from memory_consolidator import find_semantic_clusters

    mock_pool = AsyncMock()

    id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    id_b = "aaaaaaaa-0000-0000-0000-000000000002"

    # Self-join returns pairs directly
    mock_pool.fetch = AsyncMock(return_value=[
        {"id_a": id_a, "id_b": id_b, "similarity": 0.95},
    ])

    clusters = await find_semantic_clusters(mock_pool, threshold=0.85)
    # Should call fetch exactly ONCE (not 1 + N times)
    assert mock_pool.fetch.call_count == 1
    multi = [c for c in clusters if len(c) > 1]
    assert len(multi) == 1
    assert set(multi[0]) == {id_a, id_b}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_find_semantic_clusters_single_query -v`
Expected: FAIL — current implementation calls fetch N+1 times

- [ ] **Step 3: Rewrite find_semantic_clusters() with self-join**

In `python/memory_consolidator.py`, replace `find_semantic_clusters()` (lines 60-90):

```python
async def find_semantic_clusters(
    pool: asyncpg.Pool,
    threshold: float = 0.85,
) -> list[list[str]]:
    """Find clusters of similar memories using self-join + Union-Find."""
    rows = await pool.fetch(
        """
        SELECT a.id AS id_a, b.id AS id_b,
               1 - (a.embedding <=> b.embedding) AS similarity
        FROM memories_semantic a
        JOIN memories_semantic b ON a.id < b.id
        WHERE a.archived = false AND b.archived = false
          AND 1 - (a.embedding <=> b.embedding) > $1
        """,
        threshold,
    )
    if not rows:
        return []

    uf = UnionFind()
    for row in rows:
        uf.union(str(row["id_a"]), str(row["id_b"]))

    return [c for c in uf.clusters() if len(c) > 1]
```

- [ ] **Step 4: Apply same fix to find_lesson_clusters()**

Replace `find_lesson_clusters()` (lines 177-206):

```python
async def find_lesson_clusters(
    pool: asyncpg.Pool,
    threshold: float = 0.85,
) -> list[list[str]]:
    """Find clusters of similar lessons using self-join + Union-Find."""
    rows = await pool.fetch(
        """
        SELECT a.id AS id_a, b.id AS id_b,
               1 - (a.embedding <=> b.embedding) AS similarity
        FROM lessons a
        JOIN lessons b ON a.id < b.id
        WHERE a.active = true AND b.active = true
          AND 1 - (a.embedding <=> b.embedding) > $1
        """,
        threshold,
    )
    if not rows:
        return []

    uf = UnionFind()
    for row in rows:
        uf.union(str(row["id_a"]), str(row["id_b"]))

    return [c for c in uf.clusters() if len(c) > 1]
```

- [ ] **Step 5: Update old test to match new interface**

The existing `test_find_semantic_clusters` (line 161) uses `side_effect` with N+1 responses. Replace it:

```python
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
```

- [ ] **Step 6: Run all consolidator tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "perf: replace O(n) queries in cluster detection with single self-join"
```

---

### Task 4: I4 — Wrap get_embedding() in asyncio.to_thread()

**Bug:** `get_embedding()` is a synchronous CPU-bound call (llama-cpp). Every call blocks the event loop. Wrap it for async callers.

**Files:**
- Modify: `python/memory_manager.py:46-52` (add async wrapper)
- Modify: `python/memory_manager.py` (all `await` sites that call `get_embedding` in async methods)
- Modify: `python/memory_consolidator.py:146` (same)
- Modify: `python/memory_proxy.py:669,802` (same)
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test**

```python
# In python/tests/test_memory_consolidator.py

@pytest.mark.asyncio
async def test_get_embedding_async_exists():
    """get_embedding_async should exist and be a coroutine."""
    from memory_manager import get_embedding_async
    import inspect
    assert inspect.iscoroutinefunction(get_embedding_async)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_get_embedding_async_exists -v`
Expected: FAIL with `ImportError: cannot import name 'get_embedding_async'`

- [ ] **Step 3: Add get_embedding_async() wrapper**

In `python/memory_manager.py`, after `get_embedding()` (after line 52):

```python
async def get_embedding_async(text: str) -> list[float]:
    """Async wrapper — runs CPU-bound embedding in a thread."""
    return await asyncio.to_thread(get_embedding, text)
```

Add `import asyncio` at top if not already there (it's not in memory_manager.py imports).

- [ ] **Step 4: Replace get_embedding() calls in async functions**

In `python/memory_manager.py`, replace every `get_embedding(...)` call inside `async def` methods with `await get_embedding_async(...)`:

- Line 160: `embedding = await get_embedding_async(content)`
- Line 229: `embedding = await get_embedding_async(query)`
- Line 364: `embedding = await get_embedding_async(query)`
- Line 442: `embedding = await get_embedding_async(trigger_context)`
- Line 528: `embedding = await get_embedding_async(query)`
- Line 585: `embedding = await get_embedding_async(query)`
- Line 876: `embedding = await get_embedding_async(content)`
- Line 931: `embedding = await get_embedding_async(content)`

In `python/memory_consolidator.py`:
- Line 146: `new_embedding = await get_embedding_async(synthesized)`
- Update import line 18: `from memory_manager import get_embedding, get_embedding_async, DB_CONFIG`

In `python/memory_proxy.py`:
- Line 669: `query_embedding = await get_embedding_async(user_query)`
- Line 802: `query_embedding = await get_embedding_async(user_input)`
- Update import line 22: `from memory_manager import MemoryManager, get_embedding, get_embedding_async`

Keep `get_embedding()` (sync) for non-async callers like `memory_tui.py`.

- [ ] **Step 5: Run test**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_get_embedding_async_exists -v`
Expected: PASS

- [ ] **Step 6: Run all tests to check nothing broke**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/memory_manager.py python/memory_consolidator.py python/memory_proxy.py python/tests/test_memory_consolidator.py
git commit -m "fix: wrap get_embedding() in asyncio.to_thread() to unblock event loop"
```

---

### Task 5: S1-S3 — Add missing tests

**Bug:** Missing tests for: merge_semantic_cluster (LLM fallback), minimum data threshold, and single-element cluster handling.

**Files:**
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write test for merge_semantic_cluster LLM fallback**

```python
# In python/tests/test_memory_consolidator.py

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

    # Patch llm_synthesize to return None (failure)
    with patch("memory_consolidator.llm_synthesize", AsyncMock(return_value=None)):
        result = await merge_semantic_cluster(
            mock_pool,
            [str(id_a), str(id_b)],
            "http://fake:1234",
            "fake-model",
        )
    assert result is False
```

- [ ] **Step 2: Write test for minimum data threshold in consolidation**

```python
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
```

- [ ] **Step 3: Write test for merge_semantic_cluster with single element**

```python
@pytest.mark.asyncio
async def test_merge_semantic_cluster_single_row():
    """merge_semantic_cluster should return False for < 2 rows."""
    from memory_consolidator import merge_semantic_cluster
    import uuid as uuid_mod

    mock_pool = AsyncMock()
    id_a = uuid_mod.UUID("aaaaaaaa-0000-0000-0000-000000000001")

    # Only one row returned (maybe other was already archived)
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
```

- [ ] **Step 4: Run all new tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/test_memory_consolidator.py::test_merge_semantic_cluster_llm_failure python/tests/test_memory_consolidator.py::test_consolidation_skips_with_few_memories python/tests/test_memory_consolidator.py::test_merge_semantic_cluster_single_row -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/tarik/.openclaw/workspace-lyume && python -m pytest python/tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /home/tarik/.openclaw/workspace-lyume
git add python/tests/test_memory_consolidator.py
git commit -m "test: add missing tests for LLM fallback, min data, and single cluster"
```
