-- Migration 005: Emotional Memory for BNS (Neurochemical Simulation)
-- Stores chemical state snapshots at significant moments (spikes, session boundaries)

CREATE TABLE IF NOT EXISTS emotional_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chemical_state JSONB NOT NULL,        -- {"dopamine": 0.7, "serotonin": 0.5, "cortisol": 0.3, "oxytocin": 0.8}
    trigger_event TEXT NOT NULL,           -- "user_praise", "user_criticism", "error", "spike_dopamine", "spike_cortisol", "session_start", "session_end"
    trigger_detail TEXT,                   -- Additional context: user message excerpt, error text, etc.
    emotional_tone TEXT,                   -- The tone string at time of recording: "теплий, ентузіазмований"
    user_id VARCHAR(128) DEFAULT 'default'
);

-- Index for time-range queries (trend analysis)
CREATE INDEX IF NOT EXISTS idx_emotional_memory_timestamp ON emotional_memory (timestamp DESC);

-- Index for filtering by trigger type
CREATE INDEX IF NOT EXISTS idx_emotional_memory_trigger ON emotional_memory (trigger_event);

-- Index for user filtering (future multi-user support)
CREATE INDEX IF NOT EXISTS idx_emotional_memory_user ON emotional_memory (user_id);
