# ELO Rating for Lessons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lesson quality rating system — implicit LLM feedback + explicit user override, with auto-deactivation of low-rated lessons.

**Architecture:** Нові стовпці `elo_rating`/`elo_below_since` в таблиці `lessons`. Фільтр по `elo_floor` в search. Нові маркери USEFUL/USELESS/RATE_LESSON в proxy. Consolidation pass для деактивації.

**Tech Stack:** Python 3.12, asyncpg, PostgreSQL + pgvector, pytest

---

## Task 1: DB Migration

**Files:**
- `python/migrations/004_elo_rating.sql` (create)
- `python/memory_manager.py` (lines ~85-100, where other migrations are)

**Steps:**

- [ ] Create migration file `python/migrations/004_elo_rating.sql`:

```sql
-- Migration 004: Add ELO rating columns to lessons table
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_rating INTEGER DEFAULT 50;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_below_since TIMESTAMPTZ DEFAULT NULL;

-- Create index for elo_rating filter (optimization for search queries)
CREATE INDEX IF NOT EXISTS idx_lessons_elo_rating ON lessons (elo_rating) WHERE active = true;
```

- [ ] Locate `ensure_schema()` function in `python/memory_manager.py` (around line 85-100)

- [ ] Add migration call inside `ensure_schema()`:

```python
# After other migration reads (e.g., for other tables)
migration_004 = (pathlib.Path(__file__).parent / "migrations" / "004_elo_rating.sql").read_text()
await self.pool.execute(migration_004)
log.debug("Migration 004: ELO rating columns applied")
```

- [ ] Test: Connect to DB and verify columns exist:

```bash
cd /home/tarik/.openclaw/workspace-lyume
psql -U postgres -d ai_memory -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'lessons' AND column_name IN ('elo_rating', 'elo_below_since')"
```

Expected output:
```
 column_name
---------------
 elo_rating
 elo_below_since
```

- [ ] Commit:

```bash
git add python/migrations/004_elo_rating.sql python/memory_manager.py
git commit -m "feat: Add ELO rating columns to lessons table (Migration 004)"
```

---

## Task 2: Config — Add ELO parameters

**Files:**
- `python/config.yaml` (lines ~45-48, lessons section)

**Steps:**

- [ ] Open `python/config.yaml` and locate `lessons:` section (around line 45)

- [ ] Add 5 new parameters under `lessons:`:

```yaml
lessons:
  # ... existing fields ...
  elo_start: 50              # Starting rating for new lessons
  elo_implicit_delta: 5      # Change on USEFUL marker
  elo_explicit_delta: 10     # Change on RATE_LESSON marker
  elo_floor: 20              # Visibility threshold (lessons below this don't appear in search)
  elo_deactivate_days: 30    # Days below floor before automatic deactivation
```

- [ ] Test: Load config and verify access:

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 -c "
from python.config import cfg
print(f'elo_start: {cfg.lessons.elo_start}')
print(f'elo_implicit_delta: {cfg.lessons.elo_implicit_delta}')
print(f'elo_explicit_delta: {cfg.lessons.elo_explicit_delta}')
print(f'elo_floor: {cfg.lessons.elo_floor}')
print(f'elo_deactivate_days: {cfg.lessons.elo_deactivate_days}')
"
```

Expected output:
```
elo_start: 50
elo_implicit_delta: 5
elo_explicit_delta: 10
elo_floor: 20
elo_deactivate_days: 30
```

- [ ] Commit:

```bash
git add python/config.yaml
git commit -m "config: Add ELO rating parameters"
```

---

## Task 3: Implement update_lesson_elo() method

**Files:**
- `python/memory_manager.py` (new method after `save_lesson()`, around line ~488)

**Steps:**

- [ ] Open `python/memory_manager.py` and find `save_lesson()` method (around line 426)

- [ ] After the `save_lesson()` method, add new method `update_lesson_elo()`:

```python
async def update_lesson_elo(self, lesson_id: str, delta: int) -> int:
    """
    Update ELO rating for a lesson.

    Args:
        lesson_id (str): UUID of the lesson
        delta (int): Change to apply (positive or negative)

    Returns:
        int: New rating [0, 100]

    Side effects:
        - Updates elo_rating: CLAMP(elo_rating + delta, 0, 100)
        - If new rating < elo_floor and elo_below_since IS NULL: SET elo_below_since = NOW()
        - If new rating >= elo_floor: SET elo_below_since = NULL
    """
    elo_floor = getattr(cfg.lessons, 'elo_floor', 20)

    result = await self.pool.fetchval(
        """
        UPDATE lessons
        SET elo_rating = LEAST(100, GREATEST(0, elo_rating + $1)),
            elo_below_since = CASE
                WHEN LEAST(100, GREATEST(0, elo_rating + $1)) < $3 AND elo_below_since IS NULL THEN NOW()
                WHEN LEAST(100, GREATEST(0, elo_rating + $1)) >= $3 THEN NULL
                ELSE elo_below_since
            END
        WHERE id = $2
        RETURNING elo_rating
        """,
        delta,
        uuid.UUID(lesson_id),
        elo_floor,
    )

    if result is None:
        raise ValueError(f"Lesson {lesson_id} not found")

    return int(result)
```

- [ ] Test: Create a test script `test_update_elo.py`:

```python
import asyncio
import uuid
from python.memory_manager import MemoryManager
from python.config import cfg

async def test_elo_update():
    mm = MemoryManager()

    # Create a lesson
    lesson_id = await mm.save_lesson(
        content="Test lesson for ELO",
        trigger_context="test trigger context",
        source="test",
        category="general",
    )

    # Test 1: +5 delta → 55
    new_rating = await mm.update_lesson_elo(lesson_id, delta=5)
    assert new_rating == 55, f"Expected 55, got {new_rating}"
    print("✓ Test 1: +5 delta → 55")

    # Test 2: -40 delta → 15, elo_below_since should be set
    new_rating = await mm.update_lesson_elo(lesson_id, delta=-40)
    assert new_rating == 15, f"Expected 15, got {new_rating}"
    print("✓ Test 2: -40 delta → 15")

    # Verify elo_below_since is set
    elo_below = await mm.pool.fetchval("SELECT elo_below_since FROM lessons WHERE id = $1", uuid.UUID(lesson_id))
    assert elo_below is not None, "elo_below_since should be set"
    print("✓ Test 2b: elo_below_since is set")

    # Test 3: +20 delta → 35, elo_below_since should be cleared
    new_rating = await mm.update_lesson_elo(lesson_id, delta=20)
    assert new_rating == 35, f"Expected 35, got {new_rating}"
    print("✓ Test 3: +20 delta → 35")

    # Verify elo_below_since is cleared
    elo_below = await mm.pool.fetchval("SELECT elo_below_since FROM lessons WHERE id = $1", uuid.UUID(lesson_id))
    assert elo_below is None, f"elo_below_since should be NULL, got {elo_below}"
    print("✓ Test 3b: elo_below_since is cleared")

    # Test 4: Clamping — try to set rating > 100
    new_rating = await mm.update_lesson_elo(lesson_id, delta=100)
    assert new_rating == 100, f"Expected 100 (clamped), got {new_rating}"
    print("✓ Test 4: Clamping upper bound → 100")

    # Test 5: Clamping — try to set rating < 0
    new_rating = await mm.update_lesson_elo(lesson_id, delta=-150)
    assert new_rating == 0, f"Expected 0 (clamped), got {new_rating}"
    print("✓ Test 5: Clamping lower bound → 0")

    print("\n✅ All tests passed!")
    await mm.pool.close()

asyncio.run(test_elo_update())
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_update_elo.py
```

Expected output:
```
✓ Test 1: +5 delta → 55
✓ Test 2: -40 delta → 15
✓ Test 2b: elo_below_since is set
✓ Test 3: +20 delta → 35
✓ Test 3b: elo_below_since is cleared
✓ Test 4: Clamping upper bound → 100
✓ Test 5: Clamping lower bound → 0

✅ All tests passed!
```

- [ ] Commit:

```bash
git add python/memory_manager.py
git commit -m "feat: Add update_lesson_elo() method with ELO tracking"
```

---

## Task 4: Add ELO filter to search_lessons()

**Files:**
- `python/memory_manager.py` (lines ~571-595, `search_lessons()` method)

**Steps:**

- [ ] Find `search_lessons()` method (around line 571)

- [ ] Locate the WHERE clause in the main SELECT query

- [ ] Update to add `AND elo_rating >= $N` to the WHERE condition and add elo_floor parameter:

In the existing `search_lessons()`, add `elo_floor` parameter and filter. The current SQL is:

```sql
SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
       1 - (embedding <=> $1::vector) AS similarity
FROM lessons
WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true
ORDER BY embedding <=> $1::vector
LIMIT $3
```

Change params from `[json.dumps(embedding), threshold, limit]` to include elo_floor:

```python
elo_floor = getattr(cfg.lessons, 'elo_floor', 20)
params = [json.dumps(embedding), threshold, limit, elo_floor]
```

Updated SQL:

```sql
SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
       1 - (embedding <=> $1::vector) AS similarity
FROM lessons
WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true
  AND elo_rating >= $4
ORDER BY embedding <=> $1::vector
LIMIT $3
```

- [ ] Test: Create test script `test_search_elo.py`:

```python
import asyncio
from python.memory_manager import MemoryManager
from python.config import cfg

async def test_search_elo_filter():
    mm = MemoryManager()

    # Create lesson 1 with low ELO (below floor)
    lesson1_id = await mm.save_lesson(
        content="Low rated lesson about testing",
        trigger_context="test trigger 1",
        source="test",
        category="testing",
    )
    # Drop rating to 10 (below floor of 20)
    await mm.update_lesson_elo(lesson1_id, delta=-40)

    # Create lesson 2 with good ELO (above floor)
    lesson2_id = await mm.save_lesson(
        content="Well rated lesson about testing",
        trigger_context="test trigger 2",
        source="test",
        category="testing",
    )
    # Keep default rating of 50 (above floor)

    # Search with query
    results = await mm.search_lessons("test query", limit=10)

    # Only lesson 2 should appear (lesson 1 is below floor)
    result_ids = [str(r['id']) for r in results]

    assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}"
    assert lesson2_id in result_ids, f"Lesson 2 should be in results"
    assert lesson1_id not in result_ids, f"Lesson 1 (low ELO) should NOT be in results"

    print(f"✓ Search returned {len(results)} lessons")
    print(f"✓ Lesson 2 (ELO 50) is included")
    print(f"✓ Lesson 1 (ELO 10, below floor) is excluded")
    print("\n✅ ELO filter works correctly!")

    await mm.pool.close()

asyncio.run(test_search_elo_filter())
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_search_elo.py
```

Expected output:
```
✓ Search returned 1 lessons
✓ Lesson 2 (ELO 50) is included
✓ Lesson 1 (ELO 10, below floor) is excluded

✅ ELO filter works correctly!
```

- [ ] Commit:

```bash
git add python/memory_manager.py
git commit -m "feat: Add ELO floor filter to search_lessons()"
```

---

## Task 5: Add ELO filter to search_lessons_balanced()

**Files:**
- `python/memory_manager.py` (lines ~582-645, `search_lessons_balanced()` method)

**Steps:**

- [ ] Find `search_lessons_balanced()` method (around line 582)

- [ ] Update both SELECT queries to add `AND elo_rating >= $N` to WHERE clause:

In the existing `search_lessons_balanced()`, add `elo_floor` to both queries. Current code has:

```python
emb_json = json.dumps(embedding)

cooldown_filter = ""
cooldown_params = []
if not explicit_recall:
    cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
    cooldown_filter = "AND (last_triggered IS NULL OR last_triggered < now() - make_interval(days => $3))"
    cooldown_params = [cooldown_days]
```

Change to insert elo_floor BEFORE cooldown:

```python
emb_json = json.dumps(embedding)
elo_floor = getattr(cfg.lessons, 'elo_floor', 20)

cooldown_filter = ""
cooldown_params = []
if not explicit_recall:
    cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
    cooldown_filter = "AND (last_triggered IS NULL OR last_triggered < now() - make_interval(days => $4))"
    cooldown_params = [cooldown_days]
```

Both queries change from:
```sql
WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true {cooldown_filter}
```
To:
```sql
WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true AND elo_rating >= $3 {cooldown_filter}
```

And params change from `emb_json, threshold, *cooldown_params` to `emb_json, threshold, elo_floor, *cooldown_params`

- [ ] Test: Create test script `test_balanced_elo.py`:

```python
import asyncio
from python.memory_manager import MemoryManager
from python.config import cfg

async def test_search_balanced_elo():
    mm = MemoryManager()

    # Create 3 lessons: 2 with good ELO, 1 with low ELO
    lesson_ids = []
    for i in range(3):
        lesson_id = await mm.save_lesson(
            content=f"Lesson {i+1} about testing",
            trigger_context=f"test trigger {i+1}",
            source="test",
            category="testing",
        )
        lesson_ids.append(lesson_id)

    # Set lesson 3 to low ELO
    await mm.update_lesson_elo(lesson_ids[2], delta=-40)

    # Search with balanced method
    results = await mm.search_lessons_balanced("test query", limit=5)

    result_ids = [str(r['id']) for r in results]

    # Lessons 1 & 2 should be in results (ELO >= 20)
    # Lesson 3 should NOT be in results (ELO < 20)
    assert lesson_ids[0] in result_ids, "Lesson 1 (ELO 50) should be included"
    assert lesson_ids[1] in result_ids, "Lesson 2 (ELO 50) should be included"
    assert lesson_ids[2] not in result_ids, "Lesson 3 (ELO 10) should be excluded"

    print(f"✓ Balanced search returned {len(results)} lessons")
    print(f"✓ Lessons 1 & 2 (good ELO) are included")
    print(f"✓ Lesson 3 (low ELO) is excluded")
    print("\n✅ ELO filter in balanced search works correctly!")

    await mm.pool.close()

asyncio.run(test_search_balanced_elo())
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_balanced_elo.py
```

Expected output:
```
✓ Balanced search returned 2 lessons
✓ Lessons 1 & 2 (good ELO) are included
✓ Lesson 3 (low ELO) is excluded

✅ ELO filter in balanced search works correctly!
```

- [ ] Commit:

```bash
git add python/memory_manager.py
git commit -m "feat: Add ELO floor filter to search_lessons_balanced()"
```

---

## Task 6: Update build_intuition_block() to include lesson_id

**Files:**
- `python/memory_proxy.py` (line ~289, `build_intuition_block()` method)

**Steps:**

- [ ] Find `build_intuition_block()` function (around line 289, module-level standalone function)

- [ ] Ensure it's a module-level standalone function (NOT a method with self)

- [ ] Update to include lesson_id and use _mood_hint() helper:

```python
def build_intuition_block(lessons: list[dict]) -> str:
    """Build intuition block with lesson IDs for marker reference."""
    if not lessons:
        return ""

    lines = [
        "\n\n<intuition>",
        "This is your experience from past situations. Consider before responding.",
        "",
    ]

    for l in lessons:
        hint = _mood_hint(l.get("mood"), l.get("lyume_mood"))
        # Include lesson ID so LLM can use it in markers like >>USEFUL:lesson_id
        lines.append(f"- [{l['id']}] {l['content']}{hint}")

    lines.append("</intuition>")
    return "\n".join(lines)
```

- [ ] Test: Create unit test `test_build_intuition.py`:

```python
from python.memory_proxy import build_intuition_block

def test_build_intuition_with_ids():
    lessons = [
        {
            "id": "abc-123",
            "content": "Be specific",
            "mood": "warm",
            "lyume_mood": None,
        },
        {
            "id": "def-456",
            "content": "Stay focused",
            "mood": None,
            "lyume_mood": None,
        },
    ]

    block = build_intuition_block(lessons)

    assert "[abc-123]" in block, "Lesson 1 ID should be in block"
    assert "[def-456]" in block, "Lesson 2 ID should be in block"
    assert "Be specific" in block, "Lesson 1 content should be in block"
    assert "Stay focused" in block, "Lesson 2 content should be in block"
    assert "<intuition>" in block, "Block should have intuition tags"

    print("✓ Block includes lesson IDs")
    print("✓ Block includes content")
    print("✓ Block has correct format")
    print(f"\nGenerated block:\n{block}\n")
    print("✅ build_intuition_block() test passed!")

test_build_intuition_with_ids()
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_build_intuition.py
```

Expected output:
```
✓ Block includes lesson IDs
✓ Block includes content
✓ Block has correct format

Generated block:

<intuition>
This is your experience from past situations. Consider before responding.

- [abc-123] Be specific 🤗
- [def-456] Stay focused
</intuition>

✅ build_intuition_block() test passed!
```

- [ ] Commit:

```bash
git add python/memory_proxy.py
git commit -m "feat: Include lesson_id in intuition block for marker referencing"
```

---

## Task 7: Add marker parsing for USEFUL/USELESS/RATE_LESSON

**Files:**
- `python/memory_proxy.py` (line ~70, MARKER_PATTERN; lines ~389+, marker processing in process_response())

**Steps:**

- [ ] Find MARKER_PATTERN regex (around line 70, module level)

- [ ] Update regex to include new marker types:

```python
MARKER_PATTERN = re.compile(
    r">>(SAVE|RECALL|FORGET|LESSON|USEFUL|USELESS|RATE_LESSON)(?:\[([^\]]*)\])?:\s*(.+?)(?:\n|$)",
    re.IGNORECASE
)
```

- [ ] Find marker processing section in process_response() (around line 389+)

- [ ] Add handling for ELO markers. Before the main marker loop, prepare deduplication:

```python
# In process_response(), before marker processing loop:
# Collect all ELO markers with their lessons for deduplication
elo_actions = {}  # lesson_id -> (cmd, content, match)

for match in MARKER_PATTERN.finditer(text):
    cmd = match.group(1).upper()
    if cmd in ("USEFUL", "USELESS", "RATE_LESSON"):
        content = match.group(3).strip()
        if cmd == "RATE_LESSON":
            lesson_id = content.split(":")[0].strip()
        else:
            lesson_id = content

        # Explicit (RATE_LESSON) always overrides implicit (USEFUL/USELESS)
        if cmd == "RATE_LESSON" or lesson_id not in elo_actions:
            elo_actions[lesson_id] = (cmd, content, match)
```

- [ ] Add elif blocks in the main marker processing loop for ELO markers:

```python
elif cmd == "USEFUL":
    # Implicit feedback: lesson was used and helped
    lesson_id = content.strip()
    delta = getattr(cfg.lessons, 'elo_implicit_delta', 5)
    try:
        new_rating = await mm.update_lesson_elo(lesson_id, delta=delta)
        actions.append({
            "action": "useful",
            "lesson_id": lesson_id,
            "new_rating": new_rating
        })
        print(f"[elo] USEFUL: {lesson_id} → rating {new_rating}", flush=True)
    except ValueError as e:
        print(f"[elo] USEFUL failed: {e}", flush=True)

elif cmd == "USELESS":
    # Implicit feedback: lesson was available but not used
    # No rating change, just logging
    lesson_id = content.strip()
    actions.append({
        "action": "useless",
        "lesson_id": lesson_id
    })
    print(f"[elo] USELESS: {lesson_id} (no penalty)", flush=True)

elif cmd == "RATE_LESSON":
    # Explicit feedback: user rates lesson quality
    # content = "lesson_id:+" or "lesson_id:-"
    parts = content.rsplit(":", 1)
    if len(parts) == 2 and parts[1].strip() in ("+", "-"):
        lesson_id = parts[0].strip()
        delta = getattr(cfg.lessons, 'elo_explicit_delta', 10)
        if parts[1].strip() == "-":
            delta = -delta

        try:
            new_rating = await mm.update_lesson_elo(lesson_id, delta=delta)
            rating_sign = "+" if parts[1].strip() == "+" else "-"
            actions.append({
                "action": "rate_lesson",
                "lesson_id": lesson_id,
                "rating": rating_sign,
                "new_rating": new_rating
            })
            print(f"[elo] RATE_LESSON: {lesson_id} {rating_sign} → rating {new_rating}", flush=True)
        except ValueError as e:
            print(f"[elo] RATE_LESSON failed: {e}", flush=True)
    else:
        print(f"[elo] RATE_LESSON format invalid: {content}", flush=True)
```

- [ ] Test: Create unit test `test_marker_parsing.py`:

```python
import re
import sys
sys.path.insert(0, '/home/tarik/.openclaw/workspace-lyume/python')

from memory_proxy import MARKER_PATTERN

def test_marker_regex():
    # Test USEFUL marker
    text1 = ">>USEFUL:lesson-abc-123\nSome other text"
    match1 = MARKER_PATTERN.search(text1)
    assert match1, "Should match USEFUL marker"
    assert match1.group(1) == "USEFUL"
    assert match1.group(3) == "lesson-abc-123"
    print("✓ USEFUL marker parsing works")

    # Test USELESS marker
    text2 = ">>USELESS:lesson-def-456"
    match2 = MARKER_PATTERN.search(text2)
    assert match2, "Should match USELESS marker"
    assert match2.group(1) == "USELESS"
    assert match2.group(3) == "lesson-def-456"
    print("✓ USELESS marker parsing works")

    # Test RATE_LESSON with +
    text3 = ">>RATE_LESSON:lesson-ghi-789:+"
    match3 = MARKER_PATTERN.search(text3)
    assert match3, "Should match RATE_LESSON:+ marker"
    assert match3.group(1) == "RATE_LESSON"
    assert match3.group(3) == "lesson-ghi-789:+"
    print("✓ RATE_LESSON:+ marker parsing works")

    # Test RATE_LESSON with -
    text4 = ">>RATE_LESSON:lesson-jkl-012:-"
    match4 = MARKER_PATTERN.search(text4)
    assert match4, "Should match RATE_LESSON:- marker"
    assert match4.group(1) == "RATE_LESSON"
    assert match4.group(3) == "lesson-jkl-012:-"
    print("✓ RATE_LESSON:- marker parsing works")

    print("\n✅ All marker regex tests passed!")

test_marker_regex()
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_marker_parsing.py
```

Expected output:
```
✓ USEFUL marker parsing works
✓ USELESS marker parsing works
✓ RATE_LESSON:+ marker parsing works
✓ RATE_LESSON:- marker parsing works

✅ All marker regex tests passed!
```

- [ ] Commit:

```bash
git add python/memory_proxy.py
git commit -m "feat: Add marker parsing for USEFUL/USELESS/RATE_LESSON with ELO updates"
```

---

## Task 8: Consolidation Pass 4 — ELO deactivation

**Files:**
- `python/memory_consolidator.py` (after line ~313, after Pass 3)

**Steps:**

- [ ] Find `run_consolidation()` function (around line 257)

- [ ] Locate Pass 3 (stale archive) which ends around line 313

- [ ] Add new function `deactivate_low_elo()` before `run_consolidation()`:

```python
async def deactivate_low_elo(pool: asyncpg.Pool, days: int = 30) -> int:
    """
    Deactivate lessons below ELO floor for N+ days.

    Args:
        pool: Database connection pool
        days: Number of days below floor before deactivation (default 30)

    Returns:
        Number of lessons deactivated
    """
    result = await pool.execute(
        """
        UPDATE lessons
        SET active = false
        WHERE active = true
          AND elo_below_since IS NOT NULL
          AND elo_below_since < now() - make_interval(days => $1)
        """,
        days,
    )

    # Parse result string like "UPDATE 5"
    count = int(result.split()[-1]) if result else 0
    return count
```

- [ ] In `run_consolidation()`, add Pass 4 after Pass 3 (after stale archive, before closing):

```python
async def run_consolidation():
    """Main consolidation routine — 3 passes + ELO deactivation."""
    # ... Pass 1, 2, 3 (existing code) ...

    # Pass 3: Archive stale lessons (existing code ends here)
    # stale_count = await archive_stale(pool, days=stale_days)
    # log.info(f"Stale: archived {stale_count} memories (>{stale_days} days since last_updated)")

    # Pass 4: Deactivate low ELO lessons
    elo_days = getattr(cfg.lessons, 'elo_deactivate_days', 30)
    elo_deactivated = await deactivate_low_elo(pool, days=elo_days)
    log.info(f"ELO: deactivated {elo_deactivated} low-rated lessons (>{elo_days} days below floor)")

    duration = time.time() - t0
    log.info(f"Consolidation complete. Duration: {duration:.1f}s")
```

- [ ] Test: Create integration test `test_elo_deactivation.py`:

```python
import asyncio
import uuid
from datetime import datetime, timedelta
from python.memory_manager import MemoryManager
from python.memory_consolidator import deactivate_low_elo
from python.config import cfg

async def test_elo_deactivation():
    mm = MemoryManager()

    # Create a lesson and set it to low ELO
    lesson_id = await mm.save_lesson(
        content="Test lesson for deactivation",
        trigger_context="test trigger for deactivation",
        source="test",
        category="general",
    )

    # Drop rating to 10 (below floor of 20)
    await mm.update_lesson_elo(lesson_id, delta=-40)

    # Verify elo_below_since is set
    elo_below = await mm.pool.fetchval(
        "SELECT elo_below_since FROM lessons WHERE id = $1",
        uuid.UUID(lesson_id)
    )
    assert elo_below is not None, "elo_below_since should be set"
    print(f"✓ Lesson marked as below floor: {elo_below}")

    # Manually update elo_below_since to 31 days ago (bypass timestamp)
    thirty_one_days_ago = datetime.now() - timedelta(days=31)
    await mm.pool.execute(
        "UPDATE lessons SET elo_below_since = $1 WHERE id = $2",
        thirty_one_days_ago,
        uuid.UUID(lesson_id)
    )
    print(f"✓ Updated elo_below_since to 31 days ago: {thirty_one_days_ago}")

    # Verify lesson is still active
    active_before = await mm.pool.fetchval(
        "SELECT active FROM lessons WHERE id = $1",
        uuid.UUID(lesson_id)
    )
    assert active_before == True, "Lesson should still be active"
    print(f"✓ Lesson is active before deactivation: {active_before}")

    # Run deactivation pass
    elo_days = getattr(cfg.lessons, 'elo_deactivate_days', 30)
    count = await deactivate_low_elo(mm.pool, days=elo_days)
    print(f"✓ Deactivation pass completed, deactivated {count} lessons")

    # Verify lesson is now inactive
    active_after = await mm.pool.fetchval(
        "SELECT active FROM lessons WHERE id = $1",
        uuid.UUID(lesson_id)
    )
    assert active_after == False, "Lesson should be deactivated"
    print(f"✓ Lesson is now inactive: {active_after}")

    print("\n✅ ELO deactivation test passed!")

    await mm.pool.close()

asyncio.run(test_elo_deactivation())
```

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 test_elo_deactivation.py
```

Expected output:
```
✓ Lesson marked as below floor: <timestamp>
✓ Updated elo_below_since to 31 days ago: <timestamp>
✓ Lesson is active before deactivation: True
✓ Deactivation pass completed, deactivated 1 lessons
✓ Lesson is now inactive: False

✅ ELO deactivation test passed!
```

- [ ] Commit:

```bash
git add python/memory_consolidator.py
git commit -m "feat: Add consolidation Pass 4 for ELO-based deactivation"
```

---

## Task 9: Integration test — full ELO flow

**Files:**
- `python/tests/test_elo_lessons.py` (create)

**Steps:**

- [ ] Create new test file `python/tests/test_elo_lessons.py`:

```python
"""
Integration tests for ELO rating system.

Tests the complete flow:
  save lesson → implicit/explicit feedback → ELO update → search filter
"""

import asyncio
import uuid
import re
from datetime import datetime, timedelta
import pytest

from python.memory_manager import MemoryManager
from python.memory_proxy import MemoryProxy
from python.memory_consolidator import deactivate_low_elo
from python.config import cfg


class TestELOFlow:
    """Test complete ELO workflow."""

    @pytest.mark.asyncio
    async def test_save_and_rate_lesson(self):
        """Test: save_lesson → update_elo(+5) → search shows lesson"""
        mm = MemoryManager()

        # Create lesson using real signature
        lesson_id = await mm.save_lesson(
            content="Test lesson for ELO rating",
            trigger_context="test trigger context",
            source="test",
            category="general",
        )

        # Apply implicit feedback (USEFUL)
        rating1 = await mm.update_lesson_elo(lesson_id, delta=5)
        assert rating1 == 55, f"Rating should be 55 after +5, got {rating1}"

        # Search should return the lesson
        results = await mm.search_lessons("test lesson", limit=10)
        result_ids = [str(r['id']) for r in results]
        assert lesson_id in result_ids, "Lesson should appear in search"

        await mm.pool.close()

    @pytest.mark.asyncio
    async def test_low_elo_excluded_from_search(self):
        """Test: update_elo(-40) → rating < floor → search excludes lesson"""
        mm = MemoryManager()

        # Create lesson using real signature
        lesson_id = await mm.save_lesson(
            content="Bad lesson that will be rated low",
            trigger_context="test trigger",
            source="test",
            category="general",
        )

        # Drop rating below floor
        rating = await mm.update_lesson_elo(lesson_id, delta=-40)
        assert rating == 10, f"Rating should be 10 after -40, got {rating}"
        assert rating < cfg.lessons.elo_floor

        # Search should NOT return the lesson
        results = await mm.search_lessons("bad lesson", limit=10)
        result_ids = [str(r['id']) for r in results]
        assert lesson_id not in result_ids, "Low ELO lesson should be excluded"

        await mm.pool.close()

    @pytest.mark.asyncio
    async def test_recovery_from_low_elo(self):
        """Test: update_elo(-40) → update_elo(+20) → rating >= floor → elo_below_since cleared"""
        mm = MemoryManager()

        # Create and degrade lesson
        lesson_id = await mm.save_lesson(
            content="Recovering lesson that starts good",
            trigger_context="test trigger",
            source="test",
            category="general",
        )

        # First drop below floor
        await mm.update_lesson_elo(lesson_id, delta=-40)
        elo_below_1 = await mm.pool.fetchval(
            "SELECT elo_below_since FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert elo_below_1 is not None, "elo_below_since should be set when rating < floor"

        # Then recover
        rating = await mm.update_lesson_elo(lesson_id, delta=20)
        assert rating == 30, f"Rating should be 30 after +20, got {rating}"
        assert rating >= cfg.lessons.elo_floor

        # elo_below_since should be cleared
        elo_below_2 = await mm.pool.fetchval(
            "SELECT elo_below_since FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert elo_below_2 is None, "elo_below_since should be NULL when rating >= floor"

        # Lesson should now appear in search
        results = await mm.search_lessons("recovering lesson", limit=10)
        result_ids = [str(r['id']) for r in results]
        assert lesson_id in result_ids, "Recovered lesson should appear in search"

        await mm.pool.close()

    def test_marker_regex_parsing(self):
        """Test: MARKER_PATTERN regex matches USEFUL, USELESS, RATE_LESSON"""
        from memory_proxy import MARKER_PATTERN

        # Test USEFUL
        text_useful = ">>USEFUL:lesson-abc-123"
        match = MARKER_PATTERN.search(text_useful)
        assert match, "Should match USEFUL"
        assert match.group(1) == "USEFUL"
        assert match.group(3) == "lesson-abc-123"

        # Test USELESS
        text_useless = ">>USELESS:lesson-def-456"
        match = MARKER_PATTERN.search(text_useless)
        assert match, "Should match USELESS"
        assert match.group(1) == "USELESS"

        # Test RATE_LESSON +
        text_rate_plus = ">>RATE_LESSON:lesson-ghi-789:+"
        match = MARKER_PATTERN.search(text_rate_plus)
        assert match, "Should match RATE_LESSON:+"
        assert match.group(1) == "RATE_LESSON"
        assert "+" in match.group(3)

        # Test RATE_LESSON -
        text_rate_minus = ">>RATE_LESSON:lesson-jkl-012:-"
        match = MARKER_PATTERN.search(text_rate_minus)
        assert match, "Should match RATE_LESSON:-"
        assert match.group(1) == "RATE_LESSON"
        assert "-" in match.group(3)

    def test_build_intuition_includes_lesson_id(self):
        """Test: build_intuition_block includes lesson_id for marker referencing"""
        from memory_proxy import build_intuition_block

        lessons = [
            {
                "id": "abc-123",
                "content": "First lesson",
                "mood": "warm",
                "lyume_mood": None,
            },
            {
                "id": "def-456",
                "content": "Second lesson",
                "mood": None,
                "lyume_mood": None,
            },
        ]

        block = build_intuition_block(lessons)

        # Verify lesson IDs are in block
        assert "[abc-123]" in block, "Lesson 1 ID should be in block"
        assert "[def-456]" in block, "Lesson 2 ID should be in block"

        # Verify content is still there
        assert "First lesson" in block, "Content should be in block"
        assert "Second lesson" in block, "Content should be in block"

        # Verify block structure
        assert "<intuition>" in block, "Should have intuition tags"

    @pytest.mark.asyncio
    async def test_elo_deactivation_after_30_days(self):
        """Test: deactivate_low_elo removes lessons below floor for 30+ days"""
        mm = MemoryManager()

        # Create lesson and degrade
        lesson_id = await mm.save_lesson(
            content="Old bad lesson that stayed below floor",
            trigger_context="test trigger",
            source="test",
            category="general",
        )

        # Drop rating
        await mm.update_lesson_elo(lesson_id, delta=-40)

        # Manually set elo_below_since to 31 days ago
        thirty_one_days_ago = datetime.now() - timedelta(days=31)
        await mm.pool.execute(
            "UPDATE lessons SET elo_below_since = $1 WHERE id = $2",
            thirty_one_days_ago,
            uuid.UUID(lesson_id)
        )

        # Run deactivation
        elo_days = getattr(cfg.lessons, 'elo_deactivate_days', 30)
        count = await deactivate_low_elo(mm.pool, days=elo_days)

        # Verify lesson is deactivated
        active = await mm.pool.fetchval(
            "SELECT active FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert active == False, "Lesson should be deactivated"
        assert count >= 1, "Deactivation should report at least 1 lesson"

        await mm.pool.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] Run tests:

```bash
cd /home/tarik/.openclaw/workspace-lyume
python3 -m pytest python/tests/test_elo_lessons.py -v
```

Expected output:
```
python/tests/test_elo_lessons.py::TestELOFlow::test_save_and_rate_lesson PASSED
python/tests/test_elo_lessons.py::TestELOFlow::test_low_elo_excluded_from_search PASSED
python/tests/test_elo_lessons.py::TestELOFlow::test_recovery_from_low_elo PASSED
python/tests/test_elo_lessons.py::TestELOFlow::test_marker_regex_parsing PASSED
python/tests/test_elo_lessons.py::TestELOFlow::test_build_intuition_includes_lesson_id PASSED
python/tests/test_elo_lessons.py::TestELOFlow::test_elo_deactivation_after_30_days PASSED

====== 6 passed in 1.23s ======
```

- [ ] Commit:

```bash
git add python/tests/test_elo_lessons.py
git commit -m "test: Add integration tests for complete ELO rating flow"
```

---

## Final Checklist

- [ ] All 9 tasks completed
- [ ] All tests passing
- [ ] Code follows project style (Python 3.12, asyncio, type hints)
- [ ] Database migration applied
- [ ] Config parameters accessible
- [ ] search_lessons() and search_lessons_balanced() use ELO filter
- [ ] Markers USEFUL/USELESS/RATE_LESSON parsed and applied
- [ ] Consolidation pass deactivates low-rated lessons
- [ ] Commits are atomic and descriptive

---

## Deployment Notes

Before deploying to production:

1. **Test with real data:**
   ```bash
   # Run full test suite
   python3 -m pytest python/tests/test_elo_lessons.py -v
   ```

2. **Verify consolidation runs nightly:**
   - Check cron/scheduler logs for deactivation pass

3. **Monitor metrics:**
   - Count of lessons by ELO range: [0-20], [20-50], [50-100]
   - Count of lessons with `elo_below_since IS NOT NULL`
   - Count of markers processed per day (USEFUL/USELESS/RATE_LESSON)

4. **Update SOUL.md:**
   - Add instructions for implicit feedback (USEFUL/USELESS)
   - Document user override (RATE_LESSON) with examples
