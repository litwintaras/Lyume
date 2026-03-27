"""
Lyume Memory Consolidator — nightly merge of similar memories and lessons.
Runs via systemd timer. Three passes: semantic merge, lesson aggregation, stale archive.
"""

import asyncio
import json
import logging
import sys
import time
import uuid as uuid_mod
from datetime import datetime, timezone

import asyncpg
import httpx

from config import cfg
from memory_manager import get_embedding, get_embedding_async, DB_CONFIG

log = logging.getLogger("consolidator")


def _normalize_embedding(embedding) -> str:
    """Convert embedding to JSON string regardless of input type."""
    if isinstance(embedding, str):
        return embedding
    return json.dumps(list(embedding))


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

    new_embedding = await get_embedding_async(synthesized)
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


async def aggregate_lesson_cluster(
    pool: asyncpg.Pool,
    cluster_ids: list[str],
) -> bool:
    """Aggregate lessons: highest trigger_count = base, sum counts, deactivate rest."""
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


async def deactivate_low_elo(pool: asyncpg.Pool, days: int = 30) -> int:
    """Deactivate lessons below ELO floor for N+ days."""
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
    count = int(result.split()[-1]) if result else 0
    return count


async def run_consolidation():
    """Main consolidation routine — 3 passes."""
    t0 = time.time()
    log.info("Consolidation started")

    if not getattr(cfg.consolidation, 'enabled', True):
        log.info("Consolidation disabled in config")
        return

    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=3)
    try:
        # Check minimum data
        row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM memories_semantic WHERE archived = false")
        if row["cnt"] < 3:
            log.info(f"Only {row['cnt']} active memories — skipping consolidation")
            return

        lm_url = cfg.llm.url
        model = cfg.llm.model
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

        # Pass 4: Deactivate low ELO lessons
        elo_days = getattr(cfg.lessons, 'elo_deactivate_days', 30)
        elo_deactivated = await deactivate_low_elo(pool, days=elo_days)
        log.info(f"ELO: deactivated {elo_deactivated} low-rated lessons (>{elo_days} days below floor)")

        duration = time.time() - t0
        log.info(f"Consolidation complete. Duration: {duration:.1f}s")
    finally:
        await pool.close()


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
