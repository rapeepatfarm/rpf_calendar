-- =============================================================
-- RPF Calendar — Migration 012 (version2 เฟส B)
-- วันลาของพนักงานเป็นตารางของตัวเอง ไม่ใช่กิจกรรมอีกต่อไป
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\012_leaves.sql
-- =============================================================

-- ── ประเภทการลา ──────────────────────────────────────────────
-- เป็นทะเบียน ไม่ฝังชื่อในโค้ด (กติกาเดียวกับ needs_start ใน 010)
CREATE TABLE IF NOT EXISTS leave_types (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    color      TEXT NOT NULL DEFAULT '#e08c00',
    sort_order INT NOT NULL DEFAULT 0,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO leave_types (name, color, sort_order) VALUES
    ('ลาป่วย',     '#e5484d', 1),
    ('ลากิจ',      '#e08c00', 2),
    ('ลาพักร้อน',   '#2f7de1', 3),
    ('หยุดชดเชย',  '#1f9254', 4),
    ('ขาดงาน',     '#5b6b82', 5)
ON CONFLICT (name) DO NOTHING;

-- ── การลา ────────────────────────────────────────────────────
-- ทำไมไม่ใช้กิจกรรมประเภท "พนักงานลาหยุด" ต่อ (§27): กิจกรรมพอสำหรับ "เห็นว่าใครลา"
-- แต่ไม่พอสำหรับ "เช็กว่าใครว่าง" ซึ่งต้องถามเป็นรายคนเร็วๆ จากฟอร์มกิจกรรม
-- จากผังหน้าที่ประจำ และจากปฏิทิน · ตารางนี้ตอบคำถามนั้นด้วย query เดียว
CREATE TABLE IF NOT EXISTS staff_leaves (
    id            BIGSERIAL PRIMARY KEY,
    staff_id      INT NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    leave_type_id INT REFERENCES leave_types(id) ON DELETE SET NULL,
    date_from     DATE NOT NULL,
    date_to       DATE NOT NULL,
    -- ครึ่งวัน: ใช้ได้เฉพาะแถวที่เป็นวันเดียว · ลา 4.5 วัน = แถว 4 วันเต็ม + แถวครึ่งวัน
    -- ไม่ทำ start_part/end_part เพราะซับซ้อนเกินประโยชน์ (ผู้ใช้ยืนยัน §29.2)
    part          TEXT NOT NULL DEFAULT 'full',    -- full | am | pm
    note          TEXT NOT NULL DEFAULT '',
    -- ลบแบบซ่อน — วันลาที่เคยบันทึกคือประวัติ รายงานวันลาในอนาคตต้องใช้ได้
    is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,
    -- ร่องรอยว่าย้ายมาจากกิจกรรมเก่าแถวไหน (ใช้กันย้ายซ้ำถ้ารัน migration ซ้ำ)
    moved_from_activity_id BIGINT REFERENCES activities(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    INT REFERENCES users(id),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    INT REFERENCES users(id),
    CONSTRAINT staff_leaves_range_chk    CHECK (date_to >= date_from),
    CONSTRAINT staff_leaves_part_chk     CHECK (part IN ('full', 'am', 'pm')),
    CONSTRAINT staff_leaves_half_day_chk CHECK (part = 'full' OR date_from = date_to)
);

-- คำถามหลักคือ "ช่วงนี้ใครลาบ้าง" (คาบเกี่ยวช่วง) และ "คนนี้ลาวันไหนบ้าง"
CREATE INDEX IF NOT EXISTS staff_leaves_range_idx
    ON staff_leaves (date_from, date_to) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS staff_leaves_staff_idx
    ON staff_leaves (staff_id, date_from) WHERE NOT is_deleted;
CREATE UNIQUE INDEX IF NOT EXISTS staff_leaves_moved_uq
    ON staff_leaves (moved_from_activity_id) WHERE moved_from_activity_id IS NOT NULL;

-- ── ย้ายการลาที่เคยบันทึกเป็นกิจกรรม ─────────────────────────
-- เอาเฉพาะที่ระบุผู้รับผิดชอบไว้ (ไม่รู้ว่าใครลาก็ย้ายไม่ได้) และยังไม่ถูกลบ
-- ประเภทการลาให้ว่างไว้ — ชื่อกิจกรรมเดิมเก็บไว้ในหมายเหตุ ผู้ใช้ไปเติมประเภทเองได้
INSERT INTO staff_leaves (staff_id, date_from, date_to, part, note,
                          moved_from_activity_id, created_by, created_at)
SELECT a.assignee_id, a.planned_date, a.planned_end_date, 'full',
       'ย้ายมาจากกิจกรรม "' || a.title || '"'
           || CASE WHEN a.description <> '' THEN ' — ' || a.description ELSE '' END,
       a.id, a.created_by, a.created_at
  FROM activities a
  JOIN activity_categories c ON c.id = a.category_id
 WHERE c.name = 'พนักงานลาหยุด'
   AND NOT a.is_deleted
   AND a.assignee_id IS NOT NULL
ON CONFLICT (moved_from_activity_id) WHERE moved_from_activity_id IS NOT NULL DO NOTHING;

-- ปิดกิจกรรมเดิมแบบซ่อน พร้อมเขียนประวัติไว้ว่าย้ายไปไหน
-- (ปกติ activity_log เขียนจาก services/activities.py เท่านั้น — ที่นี่เป็นการย้ายข้อมูล
--  ครั้งเดียวของ migration ไม่ใช่ทางลัดใหม่ในโค้ด)
INSERT INTO activity_log (activity_id, action, from_status, to_status, detail)
SELECT a.id, 'deleted', a.status, a.status,
       'ย้ายไปทะเบียนวันลา (migration 012) — การลาไม่ใช่กิจกรรมอีกต่อไป'
  FROM activities a
  JOIN staff_leaves l ON l.moved_from_activity_id = a.id
 WHERE NOT a.is_deleted;

UPDATE activities a
   SET is_deleted = TRUE, updated_at = NOW()
  FROM staff_leaves l
 WHERE l.moved_from_activity_id = a.id AND NOT a.is_deleted;

-- ประเภทนี้ไม่ควรถูกเลือกอีก — การลาบันทึกที่หน้าวันลาแทน
UPDATE activity_categories SET active = FALSE, updated_at = NOW()
 WHERE name = 'พนักงานลาหยุด';

-- =============================================================
-- หมายเหตุ: กิจกรรมประเภทนี้ที่ไม่ได้ระบุผู้รับผิดชอบ (ถ้ามี) จะไม่ถูกย้าย
-- และยังอยู่บนปฏิทินตามเดิม — ต้องไปบันทึกใหม่ที่หน้าวันลาแล้วลบตัวเก่าเอง
-- =============================================================
