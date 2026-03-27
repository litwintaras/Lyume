-- Migration 004: Add ELO rating columns to lessons table
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_rating INTEGER DEFAULT 50;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_below_since TIMESTAMPTZ DEFAULT NULL;

-- Create index for elo_rating filter (optimization for search queries)
CREATE INDEX IF NOT EXISTS idx_lessons_elo_rating ON lessons (elo_rating) WHERE active = true;
