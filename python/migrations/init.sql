-- First-run schema creation. Runs once if tables don't exist.

CREATE EXTENSION IF NOT EXISTS vector;

-- Semantic memories
CREATE TABLE IF NOT EXISTS memories_semantic (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    concept_name TEXT DEFAULT '',
    category TEXT DEFAULT 'general',
    keywords TEXT[] DEFAULT '{}',
    embedding vector(768),
    source_info JSONB,
    archived BOOLEAN DEFAULT FALSE,
    access_count INTEGER DEFAULT 0,
    last_accessed TIMESTAMPTZ,
    last_updated TIMESTAMPTZ DEFAULT now(),
    merged_into UUID REFERENCES memories_semantic(id) ON DELETE SET NULL,
    search_vector tsvector,
    mood TEXT,
    lyume_mood TEXT,
    summary TEXT
);

-- Lessons (procedural memory / intuition)
CREATE TABLE IF NOT EXISTS lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_context TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    source TEXT DEFAULT 'manual',
    category TEXT DEFAULT 'general',
    active BOOLEAN DEFAULT TRUE,
    trigger_count INTEGER DEFAULT 0,
    last_triggered TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    merged_into UUID REFERENCES lessons(id) ON DELETE SET NULL,
    elo_rating INTEGER DEFAULT 50,
    elo_below_since TIMESTAMPTZ,
    search_vector tsvector,
    mood TEXT,
    lyume_mood TEXT,
    summary TEXT
);

-- Full-text search trigger function (shared)
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple', coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.triggers WHERE trigger_name = 'memories_search_vector_update') THEN
        CREATE TRIGGER memories_search_vector_update
        BEFORE INSERT OR UPDATE ON memories_semantic
        FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.triggers WHERE trigger_name = 'lessons_search_vector_update') THEN
        CREATE TRIGGER lessons_search_vector_update
        BEFORE INSERT OR UPDATE ON lessons
        FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS memories_search_vector_idx ON memories_semantic USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS lessons_search_vector_idx ON lessons USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_lessons_elo_rating ON lessons (elo_rating) WHERE active = true;
