#!/usr/bin/env python3
"""CLI: save a memory to PostgreSQL."""

import asyncio
import sys

from memory_manager import MemoryManager


async def main():
    if len(sys.argv) < 2:
        print("Usage: save_memory.py <text> [category]")
        sys.exit(1)

    text = sys.argv[1]
    category = sys.argv[2] if len(sys.argv) > 2 else "general"

    mm = MemoryManager()
    mem_id = await mm.save_semantic(content=text, category=category)
    print(f"Saved: {mem_id}")
    await mm.close()


if __name__ == "__main__":
    asyncio.run(main())
