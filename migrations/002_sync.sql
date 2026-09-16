-- =============================================================
-- RPF Calendar — Migration 002
-- ตารางรองรับการซิงค์กิจกรรมจากโปรแกรมอื่นของฟาร์ม
-- (เฟสนี้ทำโครงรองรับ ยังไม่ต่อแหล่งจริง — ดู sync/sources/_example.py)
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\002_sync.sql
-- =============================================================

CREATE TABLE IF NOT EXISTS sync_sources (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,     -- ตรงกับ .code ของ adapter ใน sync/sources
    name        TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    -- ข้อมูลต่อ DB ต้นทางและตัวเลือกของ adapter
    -- (ไม่เก็บรหัสผ่านที่นี่ — ให้อยู่ใน .env เหมือน DB หลัก)
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- ให้กิจกรรมจากแหล่งนี้ตกลงประเภทไหนในปฏิทิน
    category_id INT REFERENCES activity_categories(id) ON DELETE SET NULL,
    -- ดึงย้อนหลังกี่วันในแต่ละรอบ — ต้องคลุมช่วงที่ต้นทางยังแก้ไขได้
    lookback_days INT NOT NULL DEFAULT 30,
    last_run_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ประวัติการรันทุกรอบ — ใช้ไล่ตอนตัวเลขในปฏิทินไม่ตรงกับต้นทาง
CREATE TABLE IF NOT EXISTS sync_runs (
    id           BIGSERIAL PRIMARY KEY,
    source_id    INT REFERENCES sync_sources(id) ON DELETE CASCADE,
    source_code  TEXT NOT NULL DEFAULT '',   -- เก็บซ้ำไว้ เผื่อแหล่งถูกลบแล้วยังอ่านประวัติได้
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    ok           BOOLEAN NOT NULL DEFAULT FALSE,
    created_n    INT NOT NULL DEFAULT 0,
    updated_n    INT NOT NULL DEFAULT 0,
    cancelled_n  INT NOT NULL DEFAULT 0,
    skipped_n    INT NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS sync_runs_source_idx ON sync_runs (source_id, started_at DESC);
