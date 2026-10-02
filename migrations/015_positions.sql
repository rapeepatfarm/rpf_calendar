-- =============================================================
-- RPF Calendar — Migration 015
-- ตำแหน่งงานเป็นทะเบียน แทนข้อความอิสระ + แทนธง is_supervisor (014)
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\015_positions.sql
-- =============================================================
--
-- ผู้ใช้ขอเปลี่ยนวิธี (2026-10-02): แทนที่จะติ๊ก "เป็นหัวหน้างาน" รายคน
-- ให้มีทะเบียนตำแหน่งแล้วคุมที่ตำแหน่งแทน · ตำแหน่งตั้งต้น 3 อัน และ
-- ตำแหน่งหัวหน้าเดิมที่แยกย่อยตามจุด (หัวหน้าบ่อ BIOGAS / หัวหน้าโรงผสมอาหาร)
-- ให้ยุบรวมเป็น "หัวหน้างาน" อันเดียว
--
-- `can_assign` = ตำแหน่งนี้ถูกเลือกเป็น "ผู้รับผิดชอบ" ของกิจกรรมได้ไหม
-- เก็บเป็นคอลัมน์ ไม่ใช่เช็กชื่อ "พนักงาน" ในโค้ด — ถ้าเช็กชื่อ พอผู้ใช้เปลี่ยนชื่อตำแหน่ง
-- หรือเพิ่มตำแหน่งใหม่ กติกาจะเงียบหายไปโดยไม่มีอะไรเตือน (บทเรียนเดียวกับ needs_start)
CREATE TABLE IF NOT EXISTS positions (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    can_assign BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO positions (name, can_assign, sort_order, note) VALUES
    ('สัตวบาล',   TRUE,  1, ''),
    ('หัวหน้างาน', TRUE,  2, 'ยุบรวมหัวหน้าทุกจุดมาไว้ที่นี่'),
    ('พนักงาน',   FALSE, 3, 'ตำแหน่งนี้ไม่ถูกเลือกเป็นผู้รับผิดชอบของกิจกรรม')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE staff ADD COLUMN IF NOT EXISTS position_id
    INT REFERENCES positions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS staff_position_idx ON staff (position_id);

-- ── ย้ายข้อมูลเดิมจากช่องข้อความมาเป็นทะเบียน ───────────────
-- ห่อด้วย DO เพราะขั้นนี้ต้องข้ามไปเมื่อรัน migration ซ้ำหลังคอลัมน์เดิมถูกลบแล้ว
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'staff' AND column_name = 'position') THEN

        -- ตำแหน่งอื่นที่ไม่เข้ากติกายุบรวม ให้ยกมาเป็นตำแหน่งของตัวเอง ไม่ทิ้งข้อมูลใคร
        INSERT INTO positions (name, can_assign, sort_order)
        SELECT DISTINCT s.position, TRUE, 9
          FROM staff s
         WHERE s.position <> ''
           AND s.position NOT LIKE 'หัวหน้า%'
           AND s.position NOT IN (SELECT name FROM positions)
        ON CONFLICT (name) DO NOTHING;

        -- หัวหน้าทุกแบบ -> "หัวหน้างาน" (ข้อมูลจริงมี หัวหน้าบ่อ BIOGAS กับ หัวหน้าโรงผสมอาหาร)
        UPDATE staff SET position_id = (SELECT id FROM positions WHERE name = 'หัวหน้างาน')
         WHERE position LIKE 'หัวหน้า%';

        -- ที่เหลือจับคู่ตามชื่อตรงตัว
        UPDATE staff s SET position_id = p.id
          FROM positions p
         WHERE s.position_id IS NULL AND s.position = p.name;

        ALTER TABLE staff DROP COLUMN position;
    END IF;
END $$;

-- ธงรายคนจาก 014 ไม่ใช้แล้ว — กติกาย้ายไปอยู่ที่ positions.can_assign
ALTER TABLE staff DROP COLUMN IF EXISTS is_supervisor;

-- =============================================================
-- หลังจากนี้ "ผู้รับผิดชอบ" ของกิจกรรมและแผนงานประจำจะเลือกได้เฉพาะคนที่
-- ตำแหน่งมี can_assign = TRUE หรือยังไม่ได้ระบุตำแหน่ง
-- (คนที่ยังไม่ระบุตำแหน่งไม่ถูกซ่อน — ไม่งั้นคนหายจากรายการโดยไม่มีใครรู้ว่าเพราะอะไร)
-- =============================================================
