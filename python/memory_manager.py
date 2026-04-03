"""
MemoryManager — PostgreSQL + pgvector memory for Lyume.
Embeddings via configurable client (HTTP or local llama-cpp).
Supports: save, search, archive, recall from archive.
"""

import asyncio
import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from config import cfg
from embedding_client import create_embedding_client

DB_CONFIG = {
    "host": cfg.database.host,
    "port": cfg.database.port,
    "user": cfg.database.user,
    "database": cfg.database.name,
    "password": cfg.database.password,
    "ssl": False,
}

# Singleton embedding client
_embed_client = None


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        emb = cfg.embedding
        _embed_client = create_embedding_client(
            provider=getattr(emb, "provider", "local"),
            url=getattr(emb, "url", ""),
            api_key=getattr(emb, "api_key", ""),
            model=getattr(emb, "model", "nomic-embed-text"),
            model_path=getattr(emb, "model_path", ""),
            n_ctx=getattr(emb, "n_ctx", 512),
            n_gpu_layers=getattr(emb, "n_gpu_layers", 0),
            dimensions=getattr(emb, "dimensions", 768),
        )
    return _embed_client


async def get_embedding_async(text: str) -> list[float]:
    """Async embedding — delegates to configured client."""
    client = _get_embed_client()
    return await client.embed(text)


def get_embedding(text: str) -> list[float]:
    """Sync wrapper for backward compat."""
    import concurrent.futures
    client = _get_embed_client()
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, client.embed(text)).result()
    except RuntimeError:
        return asyncio.run(client.embed(text))


def rrf_merge(vector_results: list[dict], bm25_results: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: merge two ranked lists by id."""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for rank, row in enumerate(vector_results):
        rid = str(row['id'])
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
        rows[rid] = row
    for rank, row in enumerate(bm25_results):
        rid = str(row['id'])
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
        if rid not in rows:
            rows[rid] = row
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [rows[rid] for rid in sorted_ids]


class MemoryManager:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(**DB_CONFIG, min_size=cfg.database.pool_min, max_size=cfg.database.pool_max)
            async with self.pool.acquire() as conn:
                # Check if tables exist — if not, run init.sql
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'memories_semantic')"
                )
                if not exists:
                    init_sql = (pathlib.Path(__file__).parent / "migrations" / "init.sql").read_text()
                    await conn.execute(init_sql)
                else:
                    # Run incremental migrations for existing DBs
                    # Migration: merged_into columns
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
                    # Migration: search_vector (tsvector) for hybrid search
                    await conn.execute("""
                        DO $$ BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name='memories_semantic' AND column_name='search_vector'
                            ) THEN
                                ALTER TABLE memories_semantic ADD COLUMN search_vector tsvector;
                                UPDATE memories_semantic SET search_vector = to_tsvector('simple', coalesce(content, ''));
                            END IF;

                            CREATE OR REPLACE FUNCTION update_search_vector()
                            RETURNS trigger AS $fn$
                            BEGIN
                                NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
                                RETURN NEW;
                            END;
                            $fn$ LANGUAGE plpgsql;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.triggers
                                WHERE trigger_name = 'memories_search_vector_update'
                            ) THEN
                                CREATE TRIGGER memories_search_vector_update
                                BEFORE INSERT OR UPDATE ON memories_semantic
                                FOR EACH ROW EXECUTE FUNCTION update_search_vector();
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM pg_indexes
                                WHERE tablename = 'memories_semantic' AND indexname = 'memories_search_vector_idx'
                            ) THEN
                                CREATE INDEX memories_search_vector_idx ON memories_semantic USING GIN(search_vector);
                            END IF;
                        END $$;
                    """)
                    # Migration 004: Add ELO rating columns
                    migration_004 = (pathlib.Path(__file__).parent / "migrations" / "004_elo_rating.sql").read_text()
                    await self.pool.execute(migration_004)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def save_semantic(
        self,
        content: str,
        concept_name: str = "",
        category: str = "general",
        keywords: list[str] | None = None,
        source_info: dict | None = None,
        mood: str | None = None,
        lyume_mood: str | None = None,
        summary: str | None = None,
    ) -> str:
        """Save a semantic memory with embedding. Deduplicates by content similarity."""
        await self.connect()
        embedding = await get_embedding_async(content)

        # Check for near-duplicates (>90% similarity)
        dupes = await self.pool.fetch(
            """
            SELECT id, content FROM memories_semantic
            WHERE 1 - (embedding <=> $1::vector) > $2 AND archived = false
            LIMIT 1
            """,
            json.dumps(embedding),
            cfg.memory.dedup_similarity,
        )
        if dupes:
            # Update existing instead of creating duplicate
            await self.pool.execute(
                """
                UPDATE memories_semantic
                SET content = $1, embedding = $2::vector, category = $3,
                    last_updated = $4, last_accessed = $4, access_count = access_count + 1,
                    mood = COALESCE($6, mood), lyume_mood = COALESCE($7, lyume_mood),
                    summary = COALESCE($8, summary)
                WHERE id = $5
                """,
                content,
                json.dumps(embedding),
                category,
                datetime.now(timezone.utc),
                dupes[0]["id"],
                mood,
                lyume_mood,
                summary,
            )
            return str(dupes[0]["id"])

        mem_id = str(uuid.uuid4())
        await self.pool.execute(
            """
            INSERT INTO memories_semantic
                (id, concept_name, content, embedding, category, keywords,
                 source_info, last_updated, last_accessed, access_count, archived, mood, lyume_mood, summary)
            VALUES ($1, $2, $3, $4::vector, $5, $6, $7, $8, $8, 0, false, $9, $10, $11)
            """,
            uuid.UUID(mem_id),
            concept_name,
            content,
            json.dumps(embedding),
            category,
            keywords or [],
            json.dumps(source_info) if source_info else None,
            datetime.now(timezone.utc),
            mood,
            lyume_mood,
            summary,
        )
        return mem_id

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
            embedding = await get_embedding_async(query)
        if threshold is None:
            threshold = cfg.memory.similarity_threshold

        archive_filter = "" if include_archived else "AND archived = false"
        category_filter = ""
        params = [json.dumps(embedding), threshold, limit]

        if category:
            category_filter = f"AND category = ${len(params) + 1}"
            params.append(category)

        rows = await self.pool.fetch(
            f"""
            SELECT id, concept_name, content, category, keywords, archived, mood, lyume_mood, summary,
                   last_accessed, access_count,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memories_semantic
            WHERE 1 - (embedding <=> $1::vector) > $2 {archive_filter} {category_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            *params,
        )

        # Update last_accessed and access_count for found memories
        if rows:
            ids = [row["id"] for row in rows]
            await self.pool.execute(
                """
                UPDATE memories_semantic
                SET last_accessed = $1, access_count = access_count + 1
                WHERE id = ANY($2)
                """,
                datetime.now(timezone.utc),
                ids,
            )

        return [
            {
                "id": str(row["id"]),
                "concept_name": row["concept_name"],
                "content": row["content"],
                "category": row["category"],
                "keywords": row["keywords"],
                "similarity": round(float(row["similarity"]), 4),
                "archived": row["archived"],
                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                "access_count": row["access_count"],
                "mood": row["mood"],
                "lyume_mood": row["lyume_mood"],
                "summary": row["summary"],
            }
            for row in rows
        ]

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """Sanitize query text for plainto_tsquery."""
        return query.strip()

    async def search_bm25_raw(self, query: str, limit: int = 10, explicit_recall: bool = True) -> list[dict]:
        """BM25 full-text search via tsvector."""
        sanitized = self._sanitize_query(query)
        if not sanitized:
            return []
        await self.connect()

        params = [sanitized, limit]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, concept_name, content, category, keywords, archived,
                       mood, lyume_mood, summary, last_accessed, access_count,
                       ts_rank(search_vector, plainto_tsquery('simple', $1)) AS similarity
                FROM memories_semantic
                WHERE archived = false
                  AND search_vector @@ plainto_tsquery('simple', $1)
                ORDER BY similarity DESC
                LIMIT $2
                """,
                *params,
            )
        return [
            {
                "id": str(row["id"]),
                "concept_name": row["concept_name"],
                "content": row["content"],
                "category": row["category"],
                "keywords": row["keywords"],
                "similarity": round(float(row["similarity"]), 4),
                "archived": row["archived"],
                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                "access_count": row["access_count"],
                "mood": row["mood"],
                "lyume_mood": row["lyume_mood"],
                "summary": row["summary"],
            }
            for row in rows
        ]

    async def search_hybrid(self, query: str, limit: int = None, threshold: float = None,
                            embedding: list[float] | None = None, explicit_recall: bool = True) -> list[dict]:
        """Hybrid search: vector + BM25 merged via RRF."""
        if limit is None:
            limit = cfg.memory.search_limit
        if threshold is None:
            threshold = cfg.memory.similarity_threshold
        candidate_limit = getattr(cfg.memory, 'hybrid_bm25_limit', 10)
        k = getattr(cfg.memory, 'hybrid_rrf_k', 60)

        vector_results = await self.search_semantic(
            query, limit=candidate_limit, threshold=threshold,
            embedding=embedding, explicit_recall=explicit_recall
        )
        bm25_results = await self.search_bm25_raw(query, limit=candidate_limit, explicit_recall=explicit_recall)
        merged = rrf_merge(vector_results, bm25_results, k=k)
        return merged[:limit]

    async def archive_by_content(self, query: str) -> int:
        """Archive memories matching query by similarity (>>FORGET:)."""
        await self.connect()
        embedding = await get_embedding_async(query)

        result = await self.pool.execute(
            """
            UPDATE memories_semantic
            SET archived = true
            WHERE 1 - (embedding <=> $1::vector) > $2 AND archived = false
            """,
            json.dumps(embedding),
            cfg.memory.archive_similarity,
        )
        count = int(result.split()[-1])
        return count

    async def unarchive(self, mem_id: str) -> bool:
        """Restore archived memory to active."""
        await self.connect()
        result = await self.pool.execute(
            """
            UPDATE memories_semantic
            SET archived = false, last_accessed = $1
            WHERE id = $2
            """,
            datetime.now(timezone.utc),
            uuid.UUID(mem_id),
        )
        return result == "UPDATE 1"

    async def delete_semantic(self, mem_id: str) -> bool:
        await self.connect()
        result = await self.pool.execute(
            "DELETE FROM memories_semantic WHERE id = $1", uuid.UUID(mem_id)
        )
        return result == "DELETE 1"

    async def list_semantic(self, limit: int = 20, include_archived: bool = False) -> list[dict]:
        await self.connect()
        archive_filter = "" if include_archived else "WHERE archived = false"
        rows = await self.pool.fetch(
            f"""
            SELECT id, concept_name, content, category, keywords,
                   last_updated, last_accessed, access_count, archived
            FROM memories_semantic
            {archive_filter}
            ORDER BY last_updated DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "concept_name": row["concept_name"],
                "content": row["content"],
                "category": row["category"],
                "keywords": row["keywords"],
                "last_updated": row["last_updated"].isoformat(),
                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                "access_count": row["access_count"],
                "archived": row["archived"],
            }
            for row in rows
        ]

    # ── Lessons (intuition system) ──

    async def save_lesson(
        self,
        content: str,
        trigger_context: str,
        source: str = "manual",
        category: str = "general",
        mood: str | None = None,
        lyume_mood: str | None = None,
        summary: str | None = None,
    ) -> str:
        """Save a lesson. Embedding is from trigger_context, not content. Dedup >85%."""
        await self.connect()
        embedding = await get_embedding_async(trigger_context)

        dupes = await self.pool.fetch(
            """
            SELECT id, content FROM lessons
            WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true
            LIMIT 1
            """,
            json.dumps(embedding),
            cfg.lessons.active_similarity,
        )
        if dupes:
            await self.pool.execute(
                """
                UPDATE lessons
                SET content = $1, trigger_context = $2, source = $3,
                    category = $4, embedding = $5::vector,
                    mood = COALESCE($6, mood), lyume_mood = COALESCE($7, lyume_mood),
                    summary = COALESCE($8, summary)
                WHERE id = $9
                """,
                content,
                trigger_context,
                source,
                category,
                json.dumps(embedding),
                mood,
                lyume_mood,
                summary,
                dupes[0]["id"],
            )
            return str(dupes[0]["id"])

        lesson_id = str(uuid.uuid4())
        await self.pool.execute(
            """
            INSERT INTO lessons (id, content, trigger_context, embedding, source, category, mood, lyume_mood, summary)
            VALUES ($1, $2, $3, $4::vector, $5, $6, $7, $8, $9)
            """,
            uuid.UUID(lesson_id),
            content,
            trigger_context,
            json.dumps(embedding),
            source,
            category,
            mood,
            lyume_mood,
            summary,
        )
        return lesson_id

    async def update_lesson_elo(self, lesson_id: str, delta: int) -> int:
        """Update ELO rating for a lesson. Returns new rating [0, 100]."""
        await self.connect()
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
            embedding = await get_embedding_async(query)
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
            embedding = await get_embedding_async(query)
        if threshold is None:
            threshold = cfg.lessons.similarity_threshold
        emb_json = json.dumps(embedding)
        elo_floor = getattr(cfg.lessons, 'elo_floor', 20)

        cooldown_filter = ""
        cooldown_params = []
        if not explicit_recall:
            cooldown_days = getattr(cfg.consolidation, 'cooldown_days', 180)
            cooldown_filter = "AND (last_triggered IS NULL OR last_triggered < now() - make_interval(days => $4))"
            cooldown_params = [cooldown_days]

        # TOP-3 загальні + TOP-1 холодний паралельно
        rows_all, rows_cold = await asyncio.gather(
            self.pool.fetch(
                f"""
                SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM lessons
                WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true AND elo_rating >= $3 {cooldown_filter}
                ORDER BY embedding <=> $1::vector
                LIMIT 3
                """,
                emb_json, threshold, elo_floor, *cooldown_params,
            ),
            self.pool.fetch(
                f"""
                SELECT id, content, trigger_context, category, mood, lyume_mood, summary,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM lessons
                WHERE 1 - (embedding <=> $1::vector) > $2 AND active = true AND mood IS NULL AND elo_rating >= $3 {cooldown_filter}
                ORDER BY embedding <=> $1::vector
                LIMIT 1
                """,
                emb_json, threshold, elo_floor, *cooldown_params,
            ),
        )

        seen_ids = set()
        result_rows = []

        # Slot 1-2: найкращі загальні
        for row in rows_all[:2]:
            if row["id"] not in seen_ids:
                result_rows.append(row)
                seen_ids.add(row["id"])

        # Slot 3: холодний
        for row in rows_cold:
            if row["id"] not in seen_ids:
                result_rows.append(row)
                seen_ids.add(row["id"])
                break

        # Fallback: якщо холодного немає
        if len(result_rows) < limit:
            for row in rows_all[2:]:
                if row["id"] not in seen_ids:
                    result_rows.append(row)
                    seen_ids.add(row["id"])
                    if len(result_rows) >= limit:
                        break

        # Log balance info
        hot = sum(1 for r in result_rows if r["mood"])
        cold = len(result_rows) - hot
        print(f"[balanced] {len(result_rows)} lessons: {hot} hot, {cold} cold", flush=True)

        # Trigger tracking
        if result_rows:
            ids = [row["id"] for row in result_rows]
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
            for row in result_rows
        ]

    async def get_emotion_stats(self) -> dict:
        """Emotion ratio monitoring for lessons."""
        await self.connect()
        row = await self.pool.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE active = true) AS total,
                COUNT(*) FILTER (WHERE active = true AND mood IS NOT NULL) AS hot,
                COUNT(*) FILTER (WHERE active = true AND mood IS NULL) AS cold,
                COUNT(*) FILTER (WHERE active = true AND mood = 'warm') AS warm,
                COUNT(*) FILTER (WHERE active = true AND mood = 'fun') AS fun,
                COUNT(*) FILTER (WHERE active = true AND mood = 'excited') AS excited,
                COUNT(*) FILTER (WHERE active = true AND mood = 'frustrated') AS frustrated,
                COUNT(*) FILTER (WHERE active = true AND mood = 'sad') AS sad,
                COUNT(*) FILTER (WHERE active = true AND mood = 'passionate') AS passionate
            FROM lessons
        """)
        total = row["total"] or 0
        hot = row["hot"] or 0
        pct = round((hot / total) * 100, 1) if total > 0 else 0.0
        return {
            "total_active": total,
            "hot_count": hot,
            "cold_count": row["cold"] or 0,
            "hot_percentage": pct,
            "mood_breakdown": {
                k: row[k] or 0 for k in ("warm", "fun", "excited", "frustrated", "sad", "passionate")
            },
            "alert": pct > 40.0,
        }

    async def check_emotion_spiral(self, category: str | None = None, window_days: int = 7) -> dict:
        """Detect emotional feedback spiral by comparing periods."""
        await self.connect()
        now = datetime.now(timezone.utc)
        current_start = now - timedelta(days=window_days)
        prev_start = current_start - timedelta(days=window_days)

        if category:
            row = await self.pool.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= $1 AND created_at < $2) AS cur,
                    COUNT(*) FILTER (WHERE created_at >= $3 AND created_at < $1) AS prev
                FROM lessons WHERE active = true AND mood IS NOT NULL AND category = $4
            """, current_start, now, prev_start, category)
        else:
            row = await self.pool.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= $1 AND created_at < $2) AS cur,
                    COUNT(*) FILTER (WHERE created_at >= $3 AND created_at < $1) AS prev
                FROM lessons WHERE active = true AND mood IS NOT NULL
            """, current_start, now, prev_start)

        cur, prev = row["cur"] or 0, row["prev"] or 0
        growth = round(((cur - prev) / prev) * 100, 1) if prev > 0 else (999.0 if cur > 0 else 0.0)
        return {
            "current_period": cur, "previous_period": prev,
            "growth_percentage": growth, "warning": growth > 50.0,
            "window_days": window_days, "category": category,
        }

    async def list_lessons(
        self, limit: int = 50, active_only: bool = True
    ) -> list[dict]:
        """List lessons for CLI/TUI."""
        await self.connect()
        active_filter = "WHERE active = true" if active_only else ""
        rows = await self.pool.fetch(
            f"""
            SELECT id, content, trigger_context, category, source,
                   created_at, last_triggered, trigger_count, active
            FROM lessons
            {active_filter}
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "trigger_context": row["trigger_context"],
                "category": row["category"],
                "source": row["source"],
                "created_at": row["created_at"].isoformat(),
                "last_triggered": row["last_triggered"].isoformat() if row["last_triggered"] else None,
                "trigger_count": row["trigger_count"],
                "active": row["active"],
            }
            for row in rows
        ]

    async def get_top_memories(self, limit: int = 5) -> list[dict]:
        """Get most important memories by access_count and recency. For session warmup."""
        await self.connect()
        rows = await self.pool.fetch(
            """
            SELECT id, concept_name, content, category, keywords, archived,
                   mood, lyume_mood, summary, last_accessed, access_count
            FROM memories_semantic
            WHERE archived = false
            ORDER BY access_count DESC, last_accessed DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "concept_name": row["concept_name"],
                "content": row["content"],
                "category": row["category"],
                "keywords": row["keywords"],
                "archived": row["archived"],
                "mood": row["mood"],
                "lyume_mood": row["lyume_mood"],
                "summary": row["summary"],
                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                "access_count": row["access_count"],
            }
            for row in rows
        ]

    async def get_recent_lessons(self, limit: int = 3) -> list[dict]:
        """Get most recent lessons. For session warmup."""
        await self.connect()
        rows = await self.pool.fetch(
            """
            SELECT id, content, trigger_context, category, mood, lyume_mood, summary
            FROM lessons
            WHERE active = true
            ORDER BY last_triggered DESC NULLS LAST, created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "trigger_context": row["trigger_context"],
                "category": row["category"],
                "mood": row["mood"],
                "lyume_mood": row["lyume_mood"],
                "summary": row["summary"],
            }
            for row in rows
        ]

    async def get_recent_summaries(self, limit: int = 3) -> list[dict]:
        """Get most recent session summaries, chronologically (newest first)."""
        await self.connect()
        rows = await self.pool.fetch(
            """
            SELECT id, concept_name, content, category, keywords,
                   last_updated, last_accessed, access_count
            FROM memories_semantic
            WHERE category = 'session_summary' AND archived = false
            ORDER BY last_updated DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "concept_name": row["concept_name"],
                "content": row["content"],
                "category": row["category"],
                "keywords": row["keywords"],
                "last_updated": row["last_updated"].isoformat(),
                "access_count": row["access_count"],
            }
            for row in rows
        ]

    async def stats(self) -> dict:
        """Memory statistics."""
        await self.connect()
        row = await self.pool.fetchrow(
            """
            SELECT
                count(*) FILTER (WHERE NOT archived) AS active,
                count(*) FILTER (WHERE archived) AS archived,
                count(*) AS total
            FROM memories_semantic
            """
        )
        return dict(row)

    async def update_semantic(self, mem_id: str, content: str,
                              concept_name: str | None = None,
                              category: str | None = None) -> bool:
        """Update content (and re-embed) of an existing memory."""
        await self.connect()
        embedding = await get_embedding_async(content)
        result = await self.pool.execute(
            """
            UPDATE memories_semantic
            SET content = $1, embedding = $2::vector,
                concept_name = COALESCE($3, concept_name),
                category = COALESCE($4, category),
                last_updated = $5
            WHERE id = $6
            """,
            content,
            json.dumps(embedding),
            concept_name,
            category,
            datetime.now(timezone.utc),
            uuid.UUID(mem_id),
        )
        return result == "UPDATE 1"

    async def archive_semantic(self, mem_id: str) -> bool:
        """Archive a memory by ID."""
        await self.connect()
        result = await self.pool.execute(
            "UPDATE memories_semantic SET archived = true WHERE id = $1",
            uuid.UUID(mem_id),
        )
        return result == "UPDATE 1"

    async def deactivate_lesson(self, lesson_id: str) -> bool:
        await self.connect()
        result = await self.pool.execute(
            "UPDATE lessons SET active = false WHERE id = $1",
            uuid.UUID(lesson_id),
        )
        return result == "UPDATE 1"

    async def activate_lesson(self, lesson_id: str) -> bool:
        await self.connect()
        result = await self.pool.execute(
            "UPDATE lessons SET active = true WHERE id = $1",
            uuid.UUID(lesson_id),
        )
        return result == "UPDATE 1"

    async def delete_lesson(self, lesson_id: str) -> bool:
        await self.connect()
        result = await self.pool.execute(
            "DELETE FROM lessons WHERE id = $1", uuid.UUID(lesson_id)
        )
        return result == "DELETE 1"

    async def update_lesson(self, lesson_id: str, content: str,
                            trigger_context: str | None = None) -> bool:
        """Update lesson content and re-embed."""
        await self.connect()
        embedding = await get_embedding_async(content)
        result = await self.pool.execute(
            """
            UPDATE lessons
            SET content = $1, embedding = $2::vector,
                trigger_context = COALESCE($3, trigger_context)
            WHERE id = $4
            """,
            content,
            json.dumps(embedding),
            trigger_context,
            uuid.UUID(lesson_id),
        )
        return result == "UPDATE 1"

    async def lesson_stats(self) -> int:
        """Quick count of active lessons without loading all data."""
        await self.connect()
        row = await self.pool.fetchrow(
            "SELECT count(*) AS total FROM lessons WHERE active = true"
        )
        return int(row["total"]) if row else 0
