-- =============================================================
-- RPF Calendar — Migration 013 (version2 เฟส C)
-- หน้าที่ประจำ: จุดงาน + คนประจำจุด (+ คนแทนชั่วคราว)
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\013_duty.sql
-- =============================================================

-- ── จุดงาน ───────────────────────────────────────────────────
-- งานประจำที่มีคนอยู่ทุกวัน (โรงเรือน A/B/C · โรงงานอาหาร · BIOGAS · Office)
-- ไม่ใช่กิจกรรม ไม่ขึ้นปฏิทิน ไม่มีกดเริ่ม/จบ — ถ้าทำเป็นแผนงานประจำแบบ daily
-- จะสร้างกิจกรรมวันละแถวต่อจุด ปีละ 1,500 แถว ปฏิทินรก งานค้างล้น (§29.1)
CREATE TABLE IF NOT EXISTS duty_posts (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    department_id INT REFERENCES departments(id) ON DELETE SET NULL,
    -- จำนวนคน "ขั้นต่ำ" ไม่ใช่จำนวนคนในผัง — ประจำ 3 ต้องการอย่างน้อย 2 → ลา 1 คนไม่เตือน
    -- NULL = ขาดใครไม่ได้ (ต้องครบทุกคนที่ประจำอยู่)
    required_n    INT,
    description   TEXT NOT NULL DEFAULT '',
    sort_order    INT NOT NULL DEFAULT 0,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT duty_posts_required_chk CHECK (required_n IS NULL OR required_n >= 0)
);

-- ── ใครประจำจุดไหน ───────────────────────────────────────────
-- แถวละหนึ่งช่วงของคนหนึ่งที่จุดหนึ่ง · "วันนี้ใครอยู่จุด P" ตอบด้วยการคาบเกี่ยวช่วง
--   starts_on <= D AND (ends_on IS NULL OR ends_on >= D)
-- ไม่ต้องสร้างแถวรายวัน
--
-- คนแทนคือแถวแบบเดียวกันที่มี covers_staff_id — ช่วงสั้น ชี้ว่าแทนใคร
-- จึงรองรับลา 5 วันแต่คนแทนคนละคนในแต่ละช่วงได้เอง ไม่ต้องมีตารางแยก (§29.1)
CREATE TABLE IF NOT EXISTS duty_assignments (
    id              BIGSERIAL PRIMARY KEY,
    post_id         INT NOT NULL REFERENCES duty_posts(id) ON DELETE CASCADE,
    staff_id        INT NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    starts_on       DATE NOT NULL,
    ends_on         DATE,                                   -- NULL = ไม่มีกำหนด
    covers_staff_id INT REFERENCES staff(id) ON DELETE SET NULL,  -- NULL = คนประจำ
    note            TEXT NOT NULL DEFAULT '',
    -- ลบแบบซ่อน — ผังในอดีตคือประวัติ (ใครเคยประจำจุดไหนช่วงไหน)
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      INT REFERENCES users(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      INT REFERENCES users(id),
    CONSTRAINT duty_assignments_range_chk CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CONSTRAINT duty_assignments_cover_self_chk
        CHECK (covers_staff_id IS NULL OR covers_staff_id <> staff_id)
);

CREATE INDEX IF NOT EXISTS duty_assignments_post_idx
    ON duty_assignments (post_id, starts_on) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS duty_assignments_staff_idx
    ON duty_assignments (staff_id, starts_on) WHERE NOT is_deleted;

-- =============================================================
-- ไม่ใส่จุดงานตั้งต้น — ชื่อโรงเรือน/จุดงานเป็นข้อมูลจริงของฟาร์ม ให้ผู้ใช้สร้างเอง
-- จากหน้า "หน้าที่ประจำ" (ฝ่ายมีให้เลือกแล้วจาก migration 011)
-- =============================================================
