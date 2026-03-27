# Memory Consolidation Design Spec

**Date:** 2026-03-25
**Goal:** Automatically consolidate similar memories and lessons at night, prevent spam and circular recall, maintain optimal memory signal-to-noise ratio.

## Problem

1. **Information overload:** Lyume stores 5 nearly identical memories instead of 1 consolidated version with full context.
2. **Recall spam:** Same memory triggered repeatedly over weeks, degrading from nostalgia to noise.
3. **Unweighted lessons:** A lesson with 50 triggers and one with 1 trigger are treated equally in scoring.
4. **Stale data cluttering:** Old unused memories persist, diluting search quality.

## Solution

Two-part approach:

1. **Night consolidation (03:00):** Merge similar semantic memories and aggregate lessons. Run once per day via systemd timer.
2. **Recall cooldown:** Skip recently accessed memories in automatic recall. Explicit recall (user says "remind me...") bypasses cooldown.

**Design principle:** "Nostalgia, not spam" — memories appear rarely and naturally, like human forgetting. Refractory period + habituation.

## Architecture: Night Consolidation (`memory_consolidator.py`)

New module, runs via systemd timer at 03:00 UTC.

### Pass 1 — Semantic Merge

1. Select all `memories_semantic` where `archived = false`
2. For each memory, find neighbors via pgvector cosine similarity > 0.85 (vectorized SQL, NOT pairwise O(n²))
3. Group into clusters (connected components)
4. In each cluster:
   - Most recent record = base
   - LLM (Qwen via LM Studio) synthesizes content from all records
   - Merge redundant facts, keep highest-precision versions, note repeated themes
   - Base record updated with synthesized content + new embedding
   - Other records → `archived = true`, `merged_into = base.id`

### Pass 2 — Lesson Aggregation

1. Select all `lessons` where `active = true`
2. Cluster by embedding similarity > 0.85
3. In each cluster:
   - Lesson with highest `trigger_count` = base
   - `trigger_count` of base = sum of all in cluster
   - Other lessons → `active = false`, `merged_into = base.id`

### Pass 3 — Stale Archive

The consolidator becomes the single source of stale archival. Existing `archive_stale()` calls in proxy are removed.

- Memories with `last_updated` > 365 days ago → `archived = true`
- Exception: category `general` can have configurable threshold (default same)
- Soft-deleted (never recalled, not forced)

### Fallback

If LM Studio unavailable:
- Skip LLM merge (Pass 1, step 5)
- Still run Passes 2 and 3 (no LLM needed)
- Log warning, mark consolidation as partial

## Architecture: Recall Cooldown

Implemented in `memory_manager.py`.

### Filter Logic

**`search_semantic()`:**
```python
WHERE (last_accessed < now() - interval '180 days'
   OR :is_explicit_recall = true)
```

**`search_lessons_balanced()`:**
```python
WHERE (last_triggered < now() - interval '180 days'
   OR :is_explicit_recall = true)
```

Cooldown applies to both automatic recall functions: `search_semantic()` and `search_lessons_balanced()`. Explicit recall (user-initiated) bypasses the cooldown.

### Explicit vs Automatic Recall

- **Explicit:** User says "remind me...", "what do you know about...", "recall...". `intent_classifier.py` already detects via `RECALL_INTENT`. Proxy passes `explicit=True` → cooldown ignored.
- **Automatic:** Contextual recall before each response (background enrichment). Passed as `explicit=False` → cooldown applies.

### Edge Cases

- **New memory** (no `last_accessed` or just created) → no cooldown, available immediately
- **Archived memory matched by explicit recall** → restored to use, `last_accessed` updated, cooldown reset
- **Uniform cooldown:** 180 days for all memories/lessons. High-trigger lessons already prioritized in scoring, no need for per-item cooldown

## DB Changes

```sql
ALTER TABLE memories_semantic
ADD merged_into UUID NULL REFERENCES memories_semantic(id) ON DELETE SET NULL;

ALTER TABLE lessons
ADD merged_into UUID NULL REFERENCES lessons(id) ON DELETE SET NULL;
```

Both columns nullable, no defaults, zero downtime. ON DELETE SET NULL ensures referential integrity if merged record is deleted.

## Config (config.yaml)

```yaml
consolidation:
  enabled: true
  schedule: "03:00"                  # UTC, systemd OnCalendar format
  semantic_threshold: 0.85           # cosine similarity for clustering
  lesson_threshold: 0.85
  cooldown_days: 180                 # automatic recall exclusion period (6 months)
  stale_days: 365                    # archive untouched memories after this (based on last_updated)
  stale_general_days: 365            # configurable for 'general' category
  log_file: "consolidation.log"
```

## Logging

Python `logging` module, INFO level. Output to file + stdout (captured by systemd journal).

Format:
```
[2026-03-26 03:00:15] Consolidation started
[2026-03-26 03:00:16] Semantic: found 4 clusters (12 memories → 4 merged)
[2026-03-26 03:00:18] LLM synthesis: OK (4 summaries generated)
[2026-03-26 03:00:18] Lessons: found 2 clusters (5 lessons → 2 aggregated)
[2026-03-26 03:00:19] Stale: archived 3 memories (>365 days since last_updated)
[2026-03-26 03:00:19] Consolidation complete. Duration: 4.2s
```

## Systemd Timer

Create user-level timer and service:

**`~/.config/systemd/user/memory-consolidation.timer`:**
```ini
[Unit]
Description=Lyume Memory Consolidation

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Note: Removed `After=network-online.target` since DB is on localhost and timer does not need to wait for network.

**`~/.config/systemd/user/memory-consolidation.service`:**
```ini
[Unit]
Description=Lyume Memory Consolidation Service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /home/tarik/.openclaw/workspace-lyume/python/memory_consolidator.py
WorkingDirectory=/home/tarik/.openclaw/workspace-lyume/python
StandardOutput=journal
StandardError=journal
```

Note: Removed `[Install]` section (oneshot service is started by timer, does not need WantedBy). Updated path to actual location.

Enable: `systemctl --user enable memory-consolidation.timer`

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `python/memory_consolidator.py` | **Create** | Clustering, LLM synthesis, stale archive, logging |
| `python/memory_manager.py` | **Modify** | Add cooldown filter to `search_semantic` and `search_lessons_balanced`, init DB columns |
| `python/memory_proxy.py` | **Modify** | Pass `explicit_recall` flag to memory manager; use `search_lessons_balanced()` with explicit_recall param |
| `python/intent_classifier.py` | **No change** | RECALL_INTENT already exported, classify_user_intent() already returns recall: True/False |
| `python/config.yaml` | **Modify** | Add consolidation section |
| `python/config.py` | **No change** | Already supports new sections via `__getattr__` |
| `python/tests/test_memory_consolidator.py` | **Create** | Unit tests for clustering, cooldown, LLM synthesis |

## LLM Synthesis Prompt

Used in Pass 1 to merge semantically similar memories.

**System prompt:**
```
You are consolidating memories. Merge these related facts into one concise record.
Keep the most recent and precise information. Note chronological changes.
```

**User prompt:**
```
Consolidate these related memories into one record:

1. [Memory 1 text]
2. [Memory 2 text]
...

Output a single, concise merged record. Max 300 tokens.
```

**Parameters:**
- Model: Qwen (via LM Studio)
- Max tokens: 300
- Temperature: 0.3 (deterministic, consistent merging)

## Clustering Algorithm

Union-Find (disjoint set) for connected components detection.

**Approach:**
1. For each memory, find all neighbors via vectorized SQL (cosine similarity > 0.85)
2. For each pair of neighbors, union them in the disjoint set
3. Extract connected components as final clusters

**Complexity:** O(n·α(n)) where α is the inverse Ackermann function ≈ O(n) in practice.

**Advantages:**
- Simple, no external dependencies
- Fast even for 1000+ memories
- Idempotent: re-running gives same clusters

## Testing Strategy

### Unit Tests

- **Clustering:** Mock embeddings, verify connected components algorithm
- **Cooldown filter:** Verify explicit=True bypasses, explicit=False applies, new records excluded
- **LLM synthesis prompt:** Verify format and token limits

### Integration Tests

- Real PostgreSQL test DB, pre-seed with memories and lessons
- Verify consolidation: clusters formed correctly, merged_into pointers set, archived flag flipped
- Verify cooldown: search with explicit=False returns only non-cooled memories
- Verify LM Studio fallback: if unavailable, Passes 2–3 still complete

## Integration Points

### In memory_proxy.py

**Automatic recall (lines ~639-648):**
- When calling `search_semantic()` and `search_lessons_balanced()` via `asyncio.gather`, pass `explicit_recall=False`
- Both functions apply cooldown: exclude memories/lessons accessed/triggered within 180 days

**Explicit recall (when `user_intent["recall"] == True`):**
- Pass `explicit_recall=True` to bypass cooldown
- Note: Currently proxy does not use `user_intent["recall"]` for this purpose—this is new logic to be added

### In memory_manager.py

1. **search_semantic():** Add cooldown WHERE clause (conditional on `explicit_recall`)
2. **search_lessons_balanced():** Add cooldown WHERE clause (conditional on `explicit_recall`)
3. **__init__():** Run migration to add `merged_into` columns on startup

### In memory_consolidator.py

1. **Connect to DB, LM Studio**
2. **Run 3 passes** (semantic merge, lesson aggregation, stale archive)
3. **Log each step**, handle errors gracefully
4. **Exit codes:** 0 = success/partial, 1 = fatal (no DB connection)

## Edge Cases and Fallbacks

| Case | Behavior |
|------|----------|
| LM Studio unavailable | Skip Pass 1, complete Passes 2–3, log warning, exit 0 |
| Cluster with < 2 members | Skip merge (single memory, no consolidation needed) |
| Stale memory explicitly recalled | Reactivate (update last_accessed, bypass cooldown for this request) |
| DB has < 3 total active memories | Skip consolidation (not enough data to cluster) |
| DB connection error | Log error, exit 1, systemd will retry next night |
| Partial consolidation (DB error mid-run) | Log which pass failed, log partial status to file, exit 0 (success/partial), don't undo completed passes (idempotent on retry) |

## Relationship with Session Summary

- **Session summary** (`session_tracker.py`) → stores what happened per session
- **Memory consolidation** → cleans up and weights semantic memory over time

No overlap. Session summaries are never consolidated (they are chronological records). Only `memories_semantic` and `lessons` are affected.

## Monitoring

Check consolidation completion:
```bash
# Last 10 consolidation logs
journalctl --user -u memory-consolidation.service -n 10

# Check merged records
SELECT COUNT(*), COUNT(merged_into) FROM memories_semantic;
SELECT COUNT(*), COUNT(merged_into) FROM lessons;
```

## Success Criteria

1. ✓ No more than 1 memory per semantic cluster (after consolidation)
2. ✓ Same memory recalled no more than once per 180 days (except explicit)
3. ✓ Lessons aggregated by topic, trigger counts summed
4. ✓ Stale memories archived without user intervention
5. ✓ Consolidation completes in < 10s (even with 1000+ memories)
6. ✓ LM Studio unavailable → graceful degradation, partial consolidation
7. ✓ Systemd timer runs consistently (check journalctl)
