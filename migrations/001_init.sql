-- =============================================================
-- RPF Calendar — Migration 001 (initial schema)
-- ปฏิทินวางแผนงานฟาร์ม
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\001_init.sql
-- =============================================================

-- ── ผู้ใช้งาน ────────────────────────────────────────────────
-- staff แยกจาก users เพราะคนงานบางคนไม่มีบัญชี/ไม่ได้ใช้มือถือ
-- แต่ยังต้องระบุชื่อเป็นผู้รับผิดชอบในแผนงานได้
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'viewer',   -- admin | manager | worker | viewer
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_role_chk CHECK (role IN ('admin', 'manager', 'worker', 'viewer'))
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id  INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    page_key TEXT NOT NULL,
    can_view BOOLEAN NOT NULL DEFAULT FALSE,
    can_edit BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (user_id, page_key)
);

-- ทะเบียนผู้รับผิดชอบ (หน้า master)
CREATE TABLE IF NOT EXISTS staff (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    position   TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    color      TEXT NOT NULL DEFAULT '#2f7de1',
    -- ผูกบัญชีล็อกอิน — คนที่ผูกไว้จะเห็น "งานของฉัน" และกดเริ่ม/จบเองได้
    -- ON DELETE SET NULL: ลบบัญชีแล้วชื่อในทะเบียนต้องยังอยู่ ไม่งั้นแผนงานเก่าจะไร้เจ้าของ
    user_id    INT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── MASTER DATA ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_categories (
    id                   SERIAL PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    color                TEXT NOT NULL DEFAULT '#2f7de1',
    icon                 TEXT NOT NULL DEFAULT '',
    default_priority     SMALLINT NOT NULL DEFAULT 3,
    default_duration_min INT,
    sort_order           INT NOT NULL DEFAULT 0,
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT categories_priority_chk CHECK (default_priority BETWEEN 1 AND 4)
);

-- ── แผนงานประจำ (เฟส 3 — สร้างตารางไว้ก่อนเพื่อให้ FK ของ activities สมบูรณ์) ──
CREATE TABLE IF NOT EXISTS activity_series (
    id                   SERIAL PRIMARY KEY,
    title                TEXT NOT NULL,
    category_id          INT REFERENCES activity_categories(id) ON DELETE SET NULL,
    description          TEXT NOT NULL DEFAULT '',
    assignee_id          INT REFERENCES staff(id) ON DELETE SET NULL,
    priority             SMALLINT NOT NULL DEFAULT 3,
    is_all_day           BOOLEAN NOT NULL DEFAULT FALSE,
    start_time           TIME,
    duration_min         INT,

    freq                 TEXT NOT NULL DEFAULT 'daily',
    interval             INT NOT NULL DEFAULT 1,
    byweekday            INT[],
    bymonthday           INT,
    nth_week             INT,
    nth_weekday          INT,
    bymonth              INT,
    byday                INT,
    starts_on            DATE NOT NULL,
    ends_on              DATE,
    max_count            INT,

    carry_over           BOOLEAN NOT NULL DEFAULT TRUE,
    auto_skip_after_days INT,

    active               BOOLEAN NOT NULL DEFAULT TRUE,
    generated_until      DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by           INT REFERENCES users(id),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by           INT REFERENCES users(id),
    CONSTRAINT series_priority_chk CHECK (priority BETWEEN 1 AND 4),
    CONSTRAINT series_freq_chk CHECK (freq IN
        ('daily', 'weekly', 'monthly_day', 'monthly_nth', 'yearly'))
);

-- ── กิจกรรมรายครั้ง — ตารางหลักที่ทุกหน้าจออ่าน ─────────────
CREATE TABLE IF NOT EXISTS activities (
    id                   BIGSERIAL PRIMARY KEY,
    series_id            INT REFERENCES activity_series(id) ON DELETE SET NULL,
    title                TEXT NOT NULL,
    category_id          INT REFERENCES activity_categories(id) ON DELETE SET NULL,
    description          TEXT NOT NULL DEFAULT '',
    assignee_id          INT REFERENCES staff(id) ON DELETE SET NULL,
    priority             SMALLINT NOT NULL DEFAULT 3,   -- 1 ด่วนมาก … 4 ต่ำ

    -- แผน — planned_date คือวันที่วางแผนไว้เดิม ระบบไม่แก้ค่านี้เองเด็ดขาด
    -- (งานค้างใช้วิธี "คำนวณให้โผล่ในวันนี้" ไม่ใช่ย้ายวัน ดูหมายเหตุท้ายไฟล์)
    planned_date         DATE NOT NULL,
    is_all_day           BOOLEAN NOT NULL DEFAULT FALSE,
    planned_start_time   TIME,
    planned_end_time     TIME,
    duration_min         INT,

    -- สถานะและของจริง
    status               TEXT NOT NULL DEFAULT 'planned',
    started_at           TIMESTAMPTZ,
    started_by           INT REFERENCES users(id),
    finished_at          TIMESTAMPTZ,
    finished_by          INT REFERENCES users(id),
    -- เก็บค่าไว้ตอนกดสิ้นสุด ไม่คำนวณสดทุกครั้ง — ไม่งั้นรายงานเก่าจะเปลี่ยนค่า
    -- เมื่อมีคนแก้เวลาย้อนหลัง
    actual_minutes       INT,
    result_note          TEXT NOT NULL DEFAULT '',
    cancel_reason        TEXT NOT NULL DEFAULT '',

    carry_over           BOOLEAN NOT NULL DEFAULT TRUE,
    auto_skip_after_days INT,

    -- ที่มา
    source               TEXT NOT NULL DEFAULT 'manual',   -- manual | series | sync
    source_system        TEXT,
    external_id          TEXT,
    external_hash        TEXT,

    is_deleted           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by           INT REFERENCES users(id),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by           INT REFERENCES users(id),

    CONSTRAINT activities_priority_chk CHECK (priority BETWEEN 1 AND 4),
    CONSTRAINT activities_status_chk CHECK (status IN
        ('planned', 'in_progress', 'done', 'cancelled', 'missed')),
    CONSTRAINT activities_source_chk CHECK (source IN ('manual', 'series', 'sync'))
);

-- กันงานซ้ำจากการสร้างล่วงหน้าซ้ำรอบ — ตัวสร้างพึ่ง constraint นี้ ไม่ใช่พึ่งการตรวจก่อน insert
CREATE UNIQUE INDEX IF NOT EXISTS activities_series_date_uq
    ON activities (series_id, planned_date) WHERE series_id IS NOT NULL;

-- กันงานผีจากการ sync ซ้ำ
CREATE UNIQUE INDEX IF NOT EXISTS activities_external_uq
    ON activities (source_system, external_id) WHERE source_system IS NOT NULL;

CREATE INDEX IF NOT EXISTS activities_date_status_idx ON activities (planned_date, status);
CREATE INDEX IF NOT EXISTS activities_assignee_date_idx ON activities (assignee_id, planned_date);
-- หางานค้างเร็วๆ (status='planned' AND planned_date < today) โดยไม่ต้องสแกนทั้งตาราง
CREATE INDEX IF NOT EXISTS activities_open_idx ON activities (planned_date)
    WHERE status = 'planned' AND NOT is_deleted;

-- ── ประวัติ ──────────────────────────────────────────────────
-- ทุกการเปลี่ยนแปลงเขียนที่นี่ผ่าน services/activities.py ที่เดียว
CREATE TABLE IF NOT EXISTS activity_log (
    id          BIGSERIAL PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,   -- created | edited | started | finished | reopened
                                 -- | cancelled | rescheduled | synced | deleted
    from_status TEXT,
    to_status   TEXT,
    detail      TEXT NOT NULL DEFAULT '',
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    by_user_id  INT REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS activity_log_activity_idx ON activity_log (activity_id, at DESC);

-- ── ค่าตั้งค่า ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

INSERT INTO settings (key, value) VALUES
    ('plan_horizon_months', '12'),
    ('day_start_time', '06:00')
ON CONFLICT (key) DO NOTHING;

-- =============================================================
-- หมายเหตุการออกแบบที่ต้องรักษาไว้
--
-- 1. planned_date ห้ามให้ระบบแก้เอง — งานที่ไม่ได้กดเริ่มจะ "โผล่ในงานวันนี้"
--    ด้วยการ query (status='planned' AND planned_date < CURRENT_DATE AND carry_over)
--    ไม่ใช่ด้วยการ UPDATE วันที่ ถ้าย้ายวันจริงจะเสียประวัติและคิด % ทำตรงแผนไม่ได้
--
-- 2. missed ต่างจาก cancelled — missed คือวางแผนแล้วทำไม่ทัน
--    cancelled คือตั้งใจยกเลิกแผน รายงานต้องแยกสองอย่างนี้ออกจากกัน
-- =============================================================
