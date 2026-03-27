#!/usr/bin/env python3
"""CLI: search memories by semantic similarity."""

import asyncio
import sys

from memory_manager import MemoryManager


async def main():
    if len(sys.argv) < 2:
        print("Usage: search_memory.py <query> [limit]")
        sys.exit(1)

    query = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    mm = MemoryManager()
    results = await mm.search_semantic(query, limit=limit)
    if not results:
        print("No memories found.")
    else:
        for r in results:
            print(f"[{r['similarity']:.0%}] {r['content']}")
    await mm.close()


if __name__ == "__main__":
    asyncio.run(main())
