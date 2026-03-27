# Hybrid Search Design Spec

**Date:** 2026-03-26
**Goal:** Combine vector search (cosine similarity) with BM25 full-text search to improve recall for exact terms — names, dates, numbers, keywords that lack semantic neighbors.

## Problem

Pure vector search misses exact matches:
- User stores memory: "API key is sk-abc123"
- User asks: "what is sk-abc123" → low cosine similarity, memory not found
- BM25 would find it instantly via exact token match

## Solution

Hybrid search: vector + BM25 merged via Reciprocal Rank Fusion (RRF).

**Why RRF over weighted sum:**
- Scores from different scales (cosine 0–1 vs BM25 0–50+) don't add reliably
- RRF uses ranks, not scores → stable across corpus sizes
- No tuning parameters beyond k (default k=60, standard)
- Formula: `score = 1/(k + rank_vector) + 1/(k + rank_bm25)`

**Why PostgreSQL tsvector over external library:**
- Already in DB, no new dependencies
- `simple` config (no stemming) → handles Ukrainian/mixed language correctly
- Trigger-based auto-update → index stays fresh on INSERT/UPDATE

## Architecture

### DB Changes

```sql
-- Add tsvector column to memories_semantic
ALTER TABLE memories_semantic
ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Populate existing rows
UPDATE memories_semantic
SET search_vector = to_tsvector('simple', coalesce(content, ''));

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER memories_search_vector_update
BEFORE INSERT OR UPDATE ON memories_semantic
FOR EACH ROW EXECUTE FUNCTION update_search_vector();

-- GIN index for fast full-text search
CREATE INDEX IF NOT EXISTS memories_search_vector_idx
ON memories_semantic USING GIN(search_vector);
```

### Search Flow

```
search_hybrid(query, limit, explicit_recall)
├── vector_results = search_semantic_raw(query, limit*2)     # top-N with ranks
├── bm25_results = search_bm25_raw(query, limit*2)           # top-N with ranks
├── merged = rrf_merge(vector_results, bm25_results, k=60)   # RRF fusion
└── return merged[:limit]                                     # top-N final
```

### RRF Implementation

```python
def rrf_merge(vector_results, bm25_results, k=60):
    scores = {}
    for rank, row in enumerate(vector_results):
        scores[row['id']] = scores.get(row['id'], 0) + 1/(k + rank + 1)
    for rank, row in enumerate(bm25_results):
        scores[row['id']] = scores.get(row['id'], 0) + 1/(k + rank + 1)
    sorted_ids = sorted(scores, key=scores.get, reverse=True)
    # return full rows in merged order
```

### Config

```yaml
memory:
  hybrid_search: true        # enable/disable hybrid (fallback to pure vector if false)
  hybrid_rrf_k: 60           # RRF k parameter
  hybrid_bm25_limit: 10      # candidates per source before merge
```

### Proxy Integration

- `memory_proxy.py` calls `search_hybrid()` instead of `search_semantic()` when `cfg.memory.hybrid_search = true`
- Fallback: if hybrid disabled or tsvector column missing → `search_semantic()` as before
- `explicit_recall` flag passes through unchanged

## Files Changed

- `python/memory_manager.py` — add `search_bm25_raw()`, `search_hybrid()`, `rrf_merge()`
- `python/memory_proxy.py` — route to `search_hybrid()` when enabled
- `python/config.py` — add hybrid_search, hybrid_rrf_k, hybrid_bm25_limit fields
- `python/config.yaml` — add hybrid search defaults
- `python/tests/test_hybrid_search.py` — new test file (TDD)

## Not in Scope

- Hybrid search for lessons (lessons use `search_lessons_balanced()`, separate path — Week 3)
- Multilingual stemming (simple config handles mixed language well enough)
- Tunable alpha weights (RRF eliminates the need)
