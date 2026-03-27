"""
Seed & manage lessons for the intuition system.

Usage:
    # Single lesson
    python seed_lesson.py "trigger context" "lesson content" [category]

    # Batch from YAML
    python seed_lesson.py --file lessons_seed.yaml

    # List all lessons
    python seed_lesson.py --list

    # List only auto-generated (by agent)
    python seed_lesson.py --list-auto

    # Deactivate a lesson by ID
    python seed_lesson.py --deactivate <uuid>
"""

import asyncio
import sys
from pathlib import Path

import yaml

from memory_manager import MemoryManager


async def seed_one(mm: MemoryManager, trigger: str, content: str, category: str = "general"):
    lesson_id = await mm.save_lesson(
        content=content,
        trigger_context=trigger,
        source="seed",
        category=category,
    )
    print(f"  [{category}] {trigger[:40]:40s} → {content[:60]}")
    return lesson_id


async def seed_from_file(mm: MemoryManager, filepath: str):
    data = yaml.safe_load(Path(filepath).read_text())
    lessons = data.get("lessons", [])
    print(f"Seeding {len(lessons)} lessons from {filepath}...")

    for item in lessons:
        await seed_one(
            mm,
            trigger=item["trigger"],
            content=item["content"],
            category=item.get("category", "general"),
        )

    print(f"Done. {len(lessons)} lessons seeded.")


async def list_lessons(mm: MemoryManager, source_filter: str | None = None):
    lessons = await mm.list_lessons(limit=100, active_only=False)
    if source_filter:
        lessons = [l for l in lessons if l["source"] == source_filter]

    if not lessons:
        print("No lessons found.")
        return

    for l in lessons:
        status = "✓" if l["active"] else "✗"
        triggered = f"×{l['trigger_count']}" if l["trigger_count"] else "—"
        print(
            f"  {status} [{l['source']:6s}] [{l['category']:15s}] {triggered:>4s}  "
            f"{l['trigger_context'][:30]:30s} → {l['content'][:50]}"
        )
        print(f"    id: {l['id']}")

    active = sum(1 for l in lessons if l["active"])
    print(f"\nTotal: {len(lessons)} ({active} active)")


async def deactivate_lesson(mm: MemoryManager, lesson_id: str):
    await mm.connect()
    result = await mm.pool.execute(
        "UPDATE lessons SET active = false WHERE id = $1",
        __import__("uuid").UUID(lesson_id),
    )
    if result == "UPDATE 1":
        print(f"Deactivated: {lesson_id}")
    else:
        print(f"Not found: {lesson_id}")


async def main():
    mm = MemoryManager()
    await mm.connect()

    try:
        if "--list-auto" in sys.argv:
            await list_lessons(mm, source_filter="agent")
        elif "--list" in sys.argv:
            await list_lessons(mm)
        elif "--deactivate" in sys.argv:
            idx = sys.argv.index("--deactivate")
            await deactivate_lesson(mm, sys.argv[idx + 1])
        elif "--file" in sys.argv:
            idx = sys.argv.index("--file")
            filepath = sys.argv[idx + 1]
            await seed_from_file(mm, filepath)
        elif len(sys.argv) >= 3:
            trigger = sys.argv[1]
            content = sys.argv[2]
            category = sys.argv[3] if len(sys.argv) > 3 else "general"
            lesson_id = await seed_one(mm, trigger, content, category)
            print(f"Lesson saved: {lesson_id}")
        else:
            print(__doc__)
    finally:
        await mm.close()


if __name__ == "__main__":
    asyncio.run(main())
