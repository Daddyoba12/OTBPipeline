-- OTB Pipeline Cloud Sync — Supabase tables
-- Run once in: https://supabase.com/dashboard/project/zwgngbzbdvnrdnanjded/sql/new

-- One row per slot (1-4) + slot=0 for global status
CREATE TABLE IF NOT EXISTS otb_pipeline_state (
    slot               INTEGER PRIMARY KEY,
    hook               TEXT    DEFAULT '',
    hook_v2            TEXT    DEFAULT '',
    lesson             TEXT    DEFAULT '',
    lesson_v2          TEXT    DEFAULT '',
    problem            TEXT    DEFAULT '',
    stakes             TEXT    DEFAULT '',
    resolution         TEXT    DEFAULT '',
    rendered_at        TEXT    DEFAULT '',
    caption_tiktok     TEXT    DEFAULT '',
    caption_instagram  TEXT    DEFAULT '',
    v1_url             TEXT    DEFAULT '',
    v2_url             TEXT    DEFAULT '',
    pending_approval   BOOLEAN DEFAULT FALSE,
    current_step       TEXT    DEFAULT '',
    posts_today        INTEGER DEFAULT 0,
    ran_slots_json     TEXT    DEFAULT '[]',
    pending_slots_json TEXT    DEFAULT '[]',
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- Commands written by browser, read + executed by local pipeline
CREATE TABLE IF NOT EXISTS otb_pipeline_commands (
    id          BIGSERIAL PRIMARY KEY,
    slot        INTEGER NOT NULL,
    command     TEXT    NOT NULL,   -- post / skip / regen / edit
    edit_fields JSONB,              -- {field: value} for edit commands
    status      TEXT    DEFAULT 'pending',  -- pending / done / failed
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    done_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_otb_cmd_pending
    ON otb_pipeline_commands(status, created_at)
    WHERE status = 'pending';

-- Seed initial rows so they exist for PATCH operations
INSERT INTO otb_pipeline_state (slot) VALUES (0),(1),(2),(3),(4)
ON CONFLICT (slot) DO NOTHING;
