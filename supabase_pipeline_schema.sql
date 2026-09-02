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

-- ── Global clip library ───────────────────────────────────────────────────────
-- Shared between laptop + Oracle. Replaces local video_clip_log.json.
-- V1/V2/slot/date stored in video_origin for audit only — NOT used as dedup namespaces.
-- A clip is globally blocked whenever cooldown_until > now().
CREATE TABLE IF NOT EXISTS otb_clip_library (
    clip_id        TEXT        PRIMARY KEY,
    source         TEXT        NOT NULL,           -- pexels | pixabay | kling | runway
    beat_type      TEXT,                           -- hook | problem | stakes | resolution | lesson_pre
    scene_desc     TEXT,                           -- search query or prompt used
    pillar         TEXT,                           -- supply_chain | family | airport | etc.
    first_used_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    cooldown_until TIMESTAMPTZ NOT NULL,
    reuse_count    INTEGER     NOT NULL DEFAULT 0,
    video_origin   TEXT                            -- "v1_slot1_2026-08-28" — audit only
);

CREATE INDEX IF NOT EXISTS idx_otb_clip_cooldown
    ON otb_clip_library(cooldown_until);

CREATE INDEX IF NOT EXISTS idx_otb_clip_eligible
    ON otb_clip_library(source, beat_type, last_used_at)
    WHERE cooldown_until < now();

-- Atomically increment reuse_count and reset cooldown for remixed clips.
-- Called by the remix engine after a successful remix render.
CREATE OR REPLACE FUNCTION mark_clips_remixed(clip_ids text[], new_cooldown timestamptz)
RETURNS void LANGUAGE sql AS $$
    UPDATE otb_clip_library
    SET    reuse_count   = reuse_count + 1,
           last_used_at  = now(),
           cooldown_until = new_cooldown
    WHERE  clip_id = ANY(clip_ids);
$$;
