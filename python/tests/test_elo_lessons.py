"""
Integration tests for ELO rating system.
"""

import uuid
from datetime import datetime, timedelta
import pytest
import pytest_asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from memory_manager import MemoryManager
from memory_proxy import MARKER_PATTERN, build_intuition_block
from memory_consolidator import deactivate_low_elo
from config import cfg


def _unique(label: str) -> str:
    """Generate unique trigger context to avoid dedup."""
    return f"{label} {uuid.uuid4()}"


@pytest_asyncio.fixture
async def mm():
    manager = MemoryManager()
    await manager.connect()
    yield manager
    await manager.pool.close()


async def _fresh_lesson(mm, label: str) -> str:
    """Create a lesson with unique trigger and reset ELO to 50."""
    lesson_id = await mm.save_lesson(
        content=f"Test lesson {label}",
        trigger_context=_unique(label),
        source="test",
        category="general",
    )
    # Reset ELO to known state (50) in case dedup returned existing lesson
    await mm.pool.execute(
        "UPDATE lessons SET elo_rating = 50, elo_below_since = NULL WHERE id = $1",
        uuid.UUID(lesson_id),
    )
    return lesson_id


class TestUpdateLessonElo:

    @pytest.mark.asyncio
    async def test_positive_delta(self, mm):
        lesson_id = await _fresh_lesson(mm, "positive_delta")
        rating = await mm.update_lesson_elo(lesson_id, delta=5)
        assert rating == 55

    @pytest.mark.asyncio
    async def test_negative_delta(self, mm):
        lesson_id = await _fresh_lesson(mm, "negative_delta")
        rating = await mm.update_lesson_elo(lesson_id, delta=-40)
        assert rating == 10

    @pytest.mark.asyncio
    async def test_clamp_upper(self, mm):
        lesson_id = await _fresh_lesson(mm, "clamp_upper")
        rating = await mm.update_lesson_elo(lesson_id, delta=100)
        assert rating == 100

    @pytest.mark.asyncio
    async def test_clamp_lower(self, mm):
        lesson_id = await _fresh_lesson(mm, "clamp_lower")
        rating = await mm.update_lesson_elo(lesson_id, delta=-100)
        assert rating == 0

    @pytest.mark.asyncio
    async def test_elo_below_since_set(self, mm):
        lesson_id = await _fresh_lesson(mm, "below_since_set")
        await mm.update_lesson_elo(lesson_id, delta=-40)
        elo_below = await mm.pool.fetchval(
            "SELECT elo_below_since FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert elo_below is not None

    @pytest.mark.asyncio
    async def test_elo_below_since_cleared_on_recovery(self, mm):
        lesson_id = await _fresh_lesson(mm, "recovery")
        await mm.update_lesson_elo(lesson_id, delta=-40)  # 10
        await mm.update_lesson_elo(lesson_id, delta=20)   # 30 >= floor
        elo_below = await mm.pool.fetchval(
            "SELECT elo_below_since FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert elo_below is None

    @pytest.mark.asyncio
    async def test_nonexistent_lesson_raises(self, mm):
        with pytest.raises(ValueError):
            await mm.update_lesson_elo(str(uuid.uuid4()), delta=5)


class TestSearchLessonsEloFilter:

    @pytest.mark.asyncio
    async def test_low_elo_excluded_from_search(self, mm):
        uid = str(uuid.uuid4())
        trigger = f"elo exclusion test {uid}"
        lesson_id = await mm.save_lesson(
            content=f"Low elo lesson {uid}",
            trigger_context=trigger,
            source="test",
            category="general",
        )
        await mm.update_lesson_elo(lesson_id, delta=-40)  # 10 < floor
        results = await mm.search_lessons(trigger, limit=50, threshold=0.01)
        result_ids = [r['id'] for r in results]
        assert lesson_id not in result_ids

    @pytest.mark.asyncio
    async def test_good_elo_included_in_search(self, mm):
        uid = str(uuid.uuid4())
        trigger = f"elo inclusion test {uid}"
        lesson_id = await mm.save_lesson(
            content=f"Good elo lesson {uid}",
            trigger_context=trigger,
            source="test",
            category="general",
        )
        # Ensure rating is 50 (above floor)
        await mm.pool.execute(
            "UPDATE lessons SET elo_rating = 50 WHERE id = $1",
            uuid.UUID(lesson_id),
        )
        results = await mm.search_lessons(trigger, limit=50, threshold=0.01)
        result_ids = [r['id'] for r in results]
        assert lesson_id in result_ids


class TestMarkerParsing:

    def test_useful_marker(self):
        text = ">>USEFUL:lesson-abc-123"
        match = MARKER_PATTERN.search(text)
        assert match
        assert match.group(1) == "USEFUL"
        assert match.group(3) == "lesson-abc-123"

    def test_useless_marker(self):
        text = ">>USELESS:lesson-def-456"
        match = MARKER_PATTERN.search(text)
        assert match
        assert match.group(1) == "USELESS"
        assert match.group(3) == "lesson-def-456"

    def test_rate_lesson_positive(self):
        text = ">>RATE_LESSON:lesson-ghi-789:+"
        match = MARKER_PATTERN.search(text)
        assert match
        assert match.group(1) == "RATE_LESSON"
        assert "+" in match.group(3)

    def test_rate_lesson_negative(self):
        text = ">>RATE_LESSON:lesson-jkl-012:-"
        match = MARKER_PATTERN.search(text)
        assert match
        assert match.group(1) == "RATE_LESSON"
        assert "-" in match.group(3)


class TestBuildIntuitionBlock:

    def test_includes_lesson_ids(self):
        lessons = [
            {"id": "abc-123", "content": "First lesson", "mood": None, "lyume_mood": None},
            {"id": "def-456", "content": "Second lesson", "mood": None, "lyume_mood": None},
        ]
        block = build_intuition_block(lessons)
        assert "[abc-123]" in block
        assert "[def-456]" in block
        assert "First lesson" in block
        assert "<intuition>" in block


class TestEloDeactivation:

    @pytest.mark.asyncio
    async def test_deactivate_after_threshold_days(self, mm):
        lesson_id = await _fresh_lesson(mm, "deactivation")
        await mm.update_lesson_elo(lesson_id, delta=-40)
        thirty_one_days_ago = datetime.now() - timedelta(days=31)
        await mm.pool.execute(
            "UPDATE lessons SET elo_below_since = $1 WHERE id = $2",
            thirty_one_days_ago,
            uuid.UUID(lesson_id)
        )
        elo_days = getattr(cfg.lessons, 'elo_deactivate_days', 30)
        count = await deactivate_low_elo(mm.pool, days=elo_days)
        active = await mm.pool.fetchval(
            "SELECT active FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert active == False
        assert count >= 1

    @pytest.mark.asyncio
    async def test_no_deactivate_if_recent(self, mm):
        lesson_id = await _fresh_lesson(mm, "no_deactivate")
        await mm.update_lesson_elo(lesson_id, delta=-40)
        count = await deactivate_low_elo(mm.pool, days=30)
        active = await mm.pool.fetchval(
            "SELECT active FROM lessons WHERE id = $1",
            uuid.UUID(lesson_id)
        )
        assert active == True
