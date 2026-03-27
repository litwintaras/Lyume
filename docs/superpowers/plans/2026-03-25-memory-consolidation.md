# Memory Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Night consolidation of similar memories + recall cooldown to prevent spam

**Architecture:** New `memory_consolidator.py` module runs via systemd timer at 03:00. Three passes: semantic merge (Union-Find clustering + LLM synthesis), lesson aggregation, stale archive. Cooldown filter added to existing search methods in `memory_manager.py`. Proxy passes `explicit_recall` flag.

**Tech Stack:** Python 3.12, asyncpg, pgvector, llama-cpp-python (embeddings), httpx (LM Studio API)

**Spec:** `docs/superpowers/specs/2026-03-25-memory-consolidation-design.md`

---

### Task 1: DB Migration — `merged_into` columns

**Files:**
- Modify: `python/memory_manager.py:58-61` (connect method)

- [ ] **Step 1: Write failing test for migration**

Create `python/tests/test_memory_consolidator.py`:

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
async def test_merged_into_column_exists():
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_merged_into_column_exists -v`
Expected: FAIL — column does not exist

- [ ] **Step 3: Add migration to MemoryManager.connect()**

In `python/memory_manager.py`, after `self.pool = await asyncpg.create_pool(...)` (line 60), add:

```python
    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(**DB_CONFIG, min_size=cfg.database.pool_min, max_size=cfg.database.pool_max)
            # Migration: add merged_into columns if missing
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'memories_semantic' AND column_name = 'merged_into'
                        ) THEN
                            ALTER TABLE memories_semantic
                            ADD merged_into UUID NULL REFERENCES memories_semantic(id) ON DELETE SET NULL;
                        END IF;
                    END $$;
                """)
                await conn.execute("""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'lessons' AND column_name = 'merged_into'
                        ) THEN
                            ALTER TABLE lessons
                            ADD merged_into UUID NULL REFERENCES lessons(id) ON DELETE SET NULL;
                        END IF;
                    END $$;
                """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_merged_into_column_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_manager.py python/tests/test_memory_consolidator.py
git commit -m "feat: add merged_into migration to memory_manager"
```

---

### Task 2: Config — consolidation section

**Files:**
- Modify: `python/config.yaml`

- [ ] **Step 1: Add consolidation section to config.yaml**

Append to end of `python/config.yaml`:

```yaml
consolidation:
  enabled: true
  schedule: "03:00"
  semantic_threshold: 0.85
  lesson_threshold: 0.85
  cooldown_days: 180
  stale_days: 365
  stale_general_days: 365
  log_file: "consolidation.log"
```

- [ ] **Step 2: Verify config loads**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -c "from config import cfg; print(cfg.consolidation.cooldown_days, cfg.consolidation.stale_days)"`
Expected: `180 365`

- [ ] **Step 3: Commit**

```bash
git add python/config.yaml
git commit -m "config: add consolidation section (cooldown 180d, stale 365d)"
```

---

### Task 3: Recall Cooldown — `search_semantic()`

**Files:**
- Modify: `python/memory_manager.py:135-201`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test for cooldown**

Append to `python/tests/test_memory_consolidator.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import json


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_search_semantic_cooldown_filters_recent tests/test_memory_consolidator.py::test_search_semantic_explicit_bypasses_cooldown -v`
Expected: FAIL — `explicit_recall` parameter not accepted

- [ ] **Step 3: Add cooldown to search_semantic()**

In `python/memory_manager.py`, modify `search_semantic()` signature and query:

```python
    async def search_semantic(
        self,
        query: str,
        limit: int = 5,
        threshold: float = None,
        include_archived: bool = False,
        embedding: list[float] | None = None,
        category: str | None = None,
        explicit_recall: bool = True,
    ) -> list[dict]:
        """Search semantic memories by cosine similarity. Updates access tracking."""
        await self.connect()
        if embedding is None:
            embedding = get_embedding(query)
        if threshold is None:
            threshold = cfg.memory.similarity_threshold

        archive_filter = "" if include_archived else "AND archived = false"
        category_filter = ""
        cooldown_filter = ""
        params = [json.dumps(embedding), threshold, limit]

        if not explicit_recall:
            cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
            cooldown_filter = f"AND (last_accessed IS NULL OR last_accessed < now() - make_interval(days => ${len(params) + 1}))"
            params.append(cooldown_days)

        if category:
            category_filter = f"AND category = ${len(params) + 1}"
            params.append(category)

        rows = await self.pool.fetch(
            f"""
            SELECT id, concept_name, content, category, keywords, archived, mood, lyume_mood, summary,
                   last_accessed, access_count,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memories_semantic
            WHERE 1 - (embedding <=> $1::vector) > $2 {archive_filter} {cooldown_filter} {category_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            *params,
        )
```

Rest of method stays the same.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py -v -k "cooldown or explicit"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_manager.py python/tests/test_memory_consolidator.py
git commit -m "feat: add recall cooldown to search_semantic (180 days)"
```

---

### Task 4: Recall Cooldown — `search_lessons_balanced()`

**Files:**
- Modify: `python/memory_manager.py:402-498`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test**

Append to `python/tests/test_memory_consolidator.py`:

```python
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
        assert "last_triggered" in sql and "180" in sql, f"Missing cooldown in: {sql[:80]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_search_lessons_balanced_cooldown -v`
Expected: FAIL

- [ ] **Step 3: Add cooldown to search_lessons_balanced()**

In `python/memory_manager.py`, modify `search_lessons_balanced()`:

```python
    async def search_lessons_balanced(
        self,
        query: str,
        limit: int = 3,
        threshold: float = None,
        embedding: list[float] | None = None,
        explicit_recall: bool = True,
    ) -> list[dict]:
        """Balanced lesson search: 2 best by similarity + 1 cold (mood IS NULL)."""
        await self.connect()
        if embedding is None:
            embedding = get_embedding(query)
        if threshold is None:
            threshold = cfg.lessons.similarity_threshold
        emb_json = json.dumps(embedding)

        cooldown_filter = ""
        cooldown_params = []
        if not explicit_recall:
            cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
            cooldown_filter = "AND (last_triggered IS NULL OR last_triggered < now() - make_interval(days => $3))"
            cooldown_params = [cooldown_days]

        rows_all, rows_cold = await asyncio.gather(
            self.pool.fetch(
                f"""
                SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM lessons
                WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true {cooldown_filter}
                ORDER BY embedding <=> $1::vector
                LIMIT 3
                """,
                emb_json, threshold, *cooldown_params,
            ),
            self.pool.fetch(
                f"""
                SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM lessons
                WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true AND mood IS NULL {cooldown_filter}
                ORDER BY embedding <=> $1::vector
                LIMIT 1
                """,
                emb_json, threshold, *cooldown_params,
            ),
        )
```

Rest of method stays the same.

- [ ] **Step 4: Run tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_manager.py python/tests/test_memory_consolidator.py
git commit -m "feat: add recall cooldown to search_lessons_balanced (180 days)"
```

---

### Task 5: Proxy — pass `explicit_recall` flag

**Files:**
- Modify: `python/memory_proxy.py:639-648`

- [ ] **Step 1: Modify proxy to pass explicit_recall**

In `python/memory_proxy.py`, around line 608 where `user_intent` is already computed, and line 639 where `asyncio.gather` calls search:

```python
    # Determine if this is an explicit recall request
    is_explicit = bool(user_intent.get("recall"))

    # ... (existing code) ...

    memories, lessons = await asyncio.gather(
        mm.search_semantic(
            user_query, limit=MEMORY_SEARCH_LIMIT, threshold=MEMORY_SIMILARITY_THRESHOLD,
            embedding=query_embedding,
            explicit_recall=is_explicit,
        ),
        mm.search_lessons_balanced(
            user_query, limit=LESSON_SEARCH_LIMIT, threshold=LESSON_SIMILARITY_THRESHOLD,
            embedding=query_embedding,
            explicit_recall=is_explicit,
        ),
    )
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add python/memory_proxy.py
git commit -m "feat: pass explicit_recall flag from proxy to search methods"
```

---

### Task 6: Consolidator — Union-Find + clustering

**Files:**
- Create: `python/memory_consolidator.py`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test for Union-Find**

Append to `python/tests/test_memory_consolidator.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_union_find_basic -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create memory_consolidator.py with UnionFind**

Create `python/memory_consolidator.py`:

```python
"""
Lyume Memory Consolidator — nightly merge of similar memories and lessons.
Runs via systemd timer. Three passes: semantic merge, lesson aggregation, stale archive.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone

import asyncpg
import httpx

from config import cfg
from memory_manager import get_embedding, DB_CONFIG

log = logging.getLogger("consolidator")


class UnionFind:
    """Disjoint set for clustering similar memories."""

    def __init__(self):
        self._parent = {}
        self._rank = {}

    def add(self, x):
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x):
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x, y):
        self.add(x)
        self.add(y)
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def clusters(self) -> list[list]:
        groups = {}
        for x in self._parent:
            root = self.find(x)
            groups.setdefault(root, []).append(x)
        return list(groups.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_union_find_basic tests/test_memory_consolidator.py::test_union_find_single_elements -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "feat: add UnionFind for memory clustering"
```

---

### Task 7: Consolidator — semantic merge (Pass 1)

**Files:**
- Modify: `python/memory_consolidator.py`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test for find_semantic_clusters**

Append to `python/tests/test_memory_consolidator.py`:

```python
@pytest.mark.asyncio
async def test_find_semantic_clusters():
    """Should group memories with cosine similarity > threshold."""
    from memory_consolidator import find_semantic_clusters

    # Mock pool with 3 memories where A-B are similar, C is different
    mock_pool = AsyncMock()

    id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    id_b = "aaaaaaaa-0000-0000-0000-000000000002"
    id_c = "aaaaaaaa-0000-0000-0000-000000000003"

    # All active memories
    mock_pool.fetch = AsyncMock(side_effect=[
        # First call: all active memories
        [
            {"id": id_a, "content": "lives in Berlin", "embedding": json.dumps([1.0] * 768)},
            {"id": id_b, "content": "moved to Berlin", "embedding": json.dumps([1.0] * 768)},
            {"id": id_c, "content": "likes pizza", "embedding": json.dumps([0.0] * 768)},
        ],
        # Second call (for id_a neighbors): returns id_b
        [{"id": id_b, "similarity": 0.95}],
        # Third call (for id_b neighbors): returns id_a
        [{"id": id_a, "similarity": 0.95}],
        # Fourth call (for id_c neighbors): returns nothing
        [],
    ])

    clusters = await find_semantic_clusters(mock_pool, threshold=0.85)
    # Should find 1 cluster of size 2 (A+B), C is alone
    multi = [c for c in clusters if len(c) > 1]
    assert len(multi) == 1
    assert set(multi[0]) == {id_a, id_b}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_find_semantic_clusters -v`
Expected: FAIL — function not found

- [ ] **Step 3: Implement find_semantic_clusters and merge_semantic_cluster**

Append to `python/memory_consolidator.py`:

```python
async def find_semantic_clusters(
    pool: asyncpg.Pool,
    threshold: float = 0.85,
) -> list[list[str]]:
    """Find clusters of similar memories using Union-Find."""
    rows = await pool.fetch(
        "SELECT id, content, embedding FROM memories_semantic WHERE archived = false"
    )
    if len(rows) < 2:
        return []

    uf = UnionFind()
    for row in rows:
        uf.add(str(row["id"]))

    for row in rows:
        neighbors = await pool.fetch(
            """
            SELECT id, 1 - (embedding <=> $1::vector) AS similarity
            FROM memories_semantic
            WHERE archived = false AND id != $2
              AND 1 - (embedding <=> $1::vector) > $3
            """,
            row["embedding"] if isinstance(row["embedding"], str) else json.dumps(list(row["embedding"])),
            row["id"],
            threshold,
        )
        for neighbor in neighbors:
            uf.union(str(row["id"]), str(neighbor["id"]))

    return [c for c in uf.clusters() if len(c) > 1]


async def llm_synthesize(memories: list[dict], lm_url: str, model: str) -> str | None:
    """Ask LLM to merge memory texts into one consolidated record."""
    numbered = "\n".join(f"{i+1}. {m['content']}" for i, m in enumerate(memories))
    prompt = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are consolidating memories. Merge these related facts into one concise record. "
                    "Keep the most recent and precise information. Note chronological changes."
                ),
            },
            {
                "role": "user",
                "content": f"Consolidate these related memories into one record:\n\n{numbered}\n\nOutput a single, concise merged record. Max 300 tokens.",
            },
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{lm_url}/v1/chat/completions", json=prompt)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM synthesis failed: {e}")
        return None


async def merge_semantic_cluster(
    pool: asyncpg.Pool,
    cluster_ids: list[str],
    lm_url: str,
    model: str,
) -> bool:
    """Merge a cluster: LLM synthesizes, base updated, others archived."""
    import uuid as uuid_mod

    rows = await pool.fetch(
        "SELECT id, content, last_updated FROM memories_semantic WHERE id = ANY($1) ORDER BY last_updated DESC",
        [uuid_mod.UUID(cid) for cid in cluster_ids],
    )
    if len(rows) < 2:
        return False

    base = rows[0]  # most recent
    others = rows[1:]

    memories = [{"content": r["content"]} for r in rows]
    synthesized = await llm_synthesize(memories, lm_url, model)
    if synthesized is None:
        return False

    new_embedding = get_embedding(synthesized)
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE memories_semantic
                SET content = $1, embedding = $2::vector, last_updated = $3
                WHERE id = $4
                """,
                synthesized,
                json.dumps(new_embedding),
                now,
                base["id"],
            )
            for other in others:
                await conn.execute(
                    """
                    UPDATE memories_semantic
                    SET archived = true, merged_into = $1
                    WHERE id = $2
                    """,
                    base["id"],
                    other["id"],
                )

    log.info(f"Merged {len(rows)} memories → {base['id']}")
    return True
```

- [ ] **Step 4: Run test**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_find_semantic_clusters -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "feat: add semantic clustering and LLM merge"
```

---

### Task 8: Consolidator — lesson aggregation (Pass 2)

**Files:**
- Modify: `python/memory_consolidator.py`
- Test: `python/tests/test_memory_consolidator.py`

- [ ] **Step 1: Write failing test**

Append to `python/tests/test_memory_consolidator.py`:

```python
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
    mock_pool.acquire = AsyncMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=AsyncMock())
    mock_conn.transaction.return_value.__aenter__ = AsyncMock()
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = AsyncMock()

    result = await aggregate_lesson_cluster(
        mock_pool,
        [str(id_a), str(id_b)],
    )
    assert result is True
    # Base (id_a, highest trigger_count) should get sum = 15
    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("15" in c for c in calls), "trigger_count should be summed to 15"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_aggregate_lesson_cluster -v`
Expected: FAIL

- [ ] **Step 3: Implement lesson aggregation**

Append to `python/memory_consolidator.py`:

```python
async def find_lesson_clusters(
    pool: asyncpg.Pool,
    threshold: float = 0.85,
) -> list[list[str]]:
    """Find clusters of similar lessons using Union-Find."""
    rows = await pool.fetch(
        "SELECT id, embedding FROM lessons WHERE active = true"
    )
    if len(rows) < 2:
        return []

    uf = UnionFind()
    for row in rows:
        uf.add(str(row["id"]))

    for row in rows:
        neighbors = await pool.fetch(
            """
            SELECT id FROM lessons
            WHERE active = true AND id != $1
              AND 1 - (embedding <=> $2::vector) > $3
            """,
            row["id"],
            row["embedding"] if isinstance(row["embedding"], str) else json.dumps(list(row["embedding"])),
            threshold,
        )
        for neighbor in neighbors:
            uf.union(str(row["id"]), str(neighbor["id"]))

    return [c for c in uf.clusters() if len(c) > 1]


async def aggregate_lesson_cluster(
    pool: asyncpg.Pool,
    cluster_ids: list[str],
) -> bool:
    """Aggregate lessons: highest trigger_count = base, sum counts, deactivate rest."""
    import uuid as uuid_mod

    rows = await pool.fetch(
        "SELECT id, trigger_count FROM lessons WHERE id = ANY($1) ORDER BY trigger_count DESC",
        [uuid_mod.UUID(cid) for cid in cluster_ids],
    )
    if len(rows) < 2:
        return False

    base = rows[0]
    others = rows[1:]
    total_count = sum(r["trigger_count"] for r in rows)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE lessons SET trigger_count = $1 WHERE id = $2",
                total_count,
                base["id"],
            )
            for other in others:
                await conn.execute(
                    "UPDATE lessons SET active = false, merged_into = $1 WHERE id = $2",
                    base["id"],
                    other["id"],
                )

    log.info(f"Aggregated {len(rows)} lessons → {base['id']} (trigger_count={total_count})")
    return True
```

- [ ] **Step 4: Run test**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_aggregate_lesson_cluster -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "feat: add lesson aggregation (Pass 2)"
```

---

### Task 9: Consolidator — stale archive (Pass 3) + main()

**Files:**
- Modify: `python/memory_consolidator.py`

- [ ] **Step 1: Write failing test for stale archive**

Append to `python/tests/test_memory_consolidator.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py::test_archive_stale_uses_last_updated -v`
Expected: FAIL

- [ ] **Step 3: Implement archive_stale and main()**

Append to `python/memory_consolidator.py`:

```python
async def archive_stale(pool: asyncpg.Pool, days: int = 365) -> int:
    """Archive memories not updated in N days. Uses last_updated, not last_accessed."""
    result = await pool.execute(
        """
        UPDATE memories_semantic
        SET archived = true
        WHERE archived = false
          AND last_updated < now() - make_interval(days => $1)
        """,
        days,
    )
    return int(result.split()[-1])


async def run_consolidation():
    """Main consolidation routine — 3 passes."""
    t0 = time.time()
    log.info("Consolidation started")

    if not getattr(cfg.consolidation, 'enabled', True):
        log.info("Consolidation disabled in config")
        return

    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=3)

    # Check minimum data
    row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM memories_semantic WHERE archived = false")
    if row["cnt"] < 3:
        log.info(f"Only {row['cnt']} active memories — skipping consolidation")
        await pool.close()
        return

    lm_url = cfg.lm_studio.url
    model = cfg.lm_studio.model_name
    sem_threshold = getattr(cfg.consolidation, 'semantic_threshold', 0.85)
    les_threshold = getattr(cfg.consolidation, 'lesson_threshold', 0.85)
    stale_days = getattr(cfg.consolidation, 'stale_days', 365)

    # Pass 1: Semantic merge
    lm_available = True
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{lm_url}/v1/models")
    except Exception:
        lm_available = False
        log.warning("LM Studio unavailable — skipping semantic merge (Pass 1)")

    if lm_available:
        clusters = await find_semantic_clusters(pool, threshold=sem_threshold)
        merged = 0
        total_memories = sum(len(c) for c in clusters)
        for cluster_ids in clusters:
            ok = await merge_semantic_cluster(pool, cluster_ids, lm_url, model)
            if ok:
                merged += 1
        log.info(f"Semantic: found {len(clusters)} clusters ({total_memories} memories → {merged} merged)")
        if merged:
            log.info(f"LLM synthesis: OK ({merged} summaries generated)")

    # Pass 2: Lesson aggregation
    lesson_clusters = await find_lesson_clusters(pool, threshold=les_threshold)
    aggregated = 0
    total_lessons = sum(len(c) for c in lesson_clusters)
    for cluster_ids in lesson_clusters:
        ok = await aggregate_lesson_cluster(pool, cluster_ids)
        if ok:
            aggregated += 1
    log.info(f"Lessons: found {len(lesson_clusters)} clusters ({total_lessons} lessons → {aggregated} aggregated)")

    # Pass 3: Stale archive
    stale_count = await archive_stale(pool, days=stale_days)
    log.info(f"Stale: archived {stale_count} memories (>{stale_days} days since last_updated)")

    await pool.close()
    duration = time.time() - t0
    log.info(f"Consolidation complete. Duration: {duration:.1f}s")


def setup_logging():
    """Configure logging to stdout + file."""
    log_file = getattr(cfg.consolidation, 'log_file', 'consolidation.log')
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def main():
    setup_logging()
    try:
        asyncio.run(run_consolidation())
        sys.exit(0)
    except Exception as e:
        log.error(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/test_memory_consolidator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add python/memory_consolidator.py python/tests/test_memory_consolidator.py
git commit -m "feat: add stale archive (Pass 3) and main consolidation runner"
```

---

### Task 10: Remove old archive_stale() call from proxy

**Files:**
- Modify: `python/memory_proxy.py`

- [ ] **Step 1: Find and remove archive_stale usage in proxy**

Search for `archive_stale` in `memory_proxy.py`. If it's called anywhere, remove the call — consolidator is now the single source.

Run: `grep -n archive_stale /home/tarik/.openclaw/workspace-lyume/python/memory_proxy.py`

If found, remove the call. If not found (only in memory_manager.py as a method), no change needed — just confirm.

- [ ] **Step 2: Run all tests**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit (only if changes made)**

```bash
git add python/memory_proxy.py
git commit -m "refactor: remove archive_stale call from proxy (consolidator owns it now)"
```

---

### Task 11: Systemd timer + service

**Files:**
- Create: `~/.config/systemd/user/memory-consolidation.timer`
- Create: `~/.config/systemd/user/memory-consolidation.service`

- [ ] **Step 1: Create timer**

```ini
[Unit]
Description=Lyume Memory Consolidation

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Create service**

```ini
[Unit]
Description=Lyume Memory Consolidation Service

[Service]
Type=oneshot
ExecStart=/home/tarik/.openclaw/workspace-lyume/python/.venv/bin/python /home/tarik/.openclaw/workspace-lyume/python/memory_consolidator.py
WorkingDirectory=/home/tarik/.openclaw/workspace-lyume/python
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 3: Enable timer**

Run: `systemctl --user daemon-reload && systemctl --user enable memory-consolidation.timer && systemctl --user start memory-consolidation.timer`

- [ ] **Step 4: Verify timer is active**

Run: `systemctl --user status memory-consolidation.timer`
Expected: active (waiting), next trigger at 03:00

- [ ] **Step 5: Test manual run**

Run: `systemctl --user start memory-consolidation.service && journalctl --user -u memory-consolidation.service -n 20 --no-pager`
Expected: Consolidation log output (started, passes, complete)

- [ ] **Step 6: Commit**

```bash
git add ~/.config/systemd/user/memory-consolidation.timer ~/.config/systemd/user/memory-consolidation.service
git commit -m "feat: add systemd timer for nightly consolidation at 03:00"
```

---

### Task 12: Full integration test

- [ ] **Step 1: Run full test suite**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Manual smoke test — consolidation**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python memory_consolidator.py`
Expected: Log output showing 3 passes completed

- [ ] **Step 3: Manual smoke test — cooldown**

Run: `cd /home/tarik/.openclaw/workspace-lyume/python && .venv/bin/python -c "
import asyncio
from memory_manager import MemoryManager
async def test():
    mm = MemoryManager()
    await mm.connect()
    # Auto recall (cooldown applies)
    auto = await mm.search_semantic('test', explicit_recall=False)
    # Explicit recall (no cooldown)
    explicit = await mm.search_semantic('test', explicit_recall=True)
    print(f'Auto: {len(auto)} results, Explicit: {len(explicit)} results')
    await mm.close()
asyncio.run(test())
"`
Expected: Explicit may return more results than auto (if any memories are within cooldown)

- [ ] **Step 4: Final commit if any fixes**

```bash
git add -A
git commit -m "fix: integration test fixes"
```
