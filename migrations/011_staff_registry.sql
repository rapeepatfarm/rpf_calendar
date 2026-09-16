-- =============================================================
-- RPF Calendar — Migration 011 (version2 เฟส A)
-- ทะเบียนพนักงาน: ฝ่าย + รหัสพนักงาน
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\011_staff_registry.sql
-- =============================================================

-- ── ฝ่าย ─────────────────────────────────────────────────────
-- เป็นตารางไม่ใช่ข้อความอิสระ เพราะต้องกรองและ "เลือกทั้งฝ่าย" เป็นผู้ปฏิบัติงานได้
-- ถ้าเป็นข้อความ "โรงเรือน A" กับ "โรงเรือนA" จะกลายเป็นคนละฝ่ายโดยไม่มีใครรู้
--
-- ฝ่ายกับจุดงานเป็นคนละชั้น (ผู้ใช้ยืนยัน §29) — ฝ่ายเลี้ยงไก่มีจุดงานโรงเรือน A/B/C
-- จุดงานจะมาในเฟส C (duty_posts.department_id ชี้มาที่นี่)
CREATE TABLE IF NOT EXISTS departments (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INT NOT NULL DEFAULT 0,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── รหัสพนักงาน ──────────────────────────────────────────────
-- เป็นกุญแจข้ามโปรแกรม ไม่ใช่กุญแจภายใน — ภายในยังผูกด้วย staff.id เหมือนเดิม
-- มีไว้ให้คนอ่าน ค้นหา และเป็นค่านิ่งเมื่อโปรแกรมพี่น้องจะดึงข้อมูลพนักงานไปใช้
-- (กติกาซิงค์ห้ามผูกด้วยชื่อ)
--
-- ยอมให้ว่างได้ เพราะคนที่มีอยู่แล้วยังไม่มีรหัส แต่กรอกแล้วห้ามซ้ำ
-- จึงเป็น partial unique index ไม่ใช่ UNIQUE ธรรมดา (ค่าว่างหลายแถวต้องอยู่ร่วมกันได้)
ALTER TABLE staff ADD COLUMN IF NOT EXISTS code TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS staff_code_uq ON staff (code) WHERE code <> '';

-- ── ฝ่ายของพนักงาน ───────────────────────────────────────────
-- ON DELETE SET NULL: ลบฝ่ายแล้วคนต้องยังอยู่ (router จะปิดใช้งานแทนการลบถ้ามีคนอยู่)
ALTER TABLE staff ADD COLUMN IF NOT EXISTS department_id
    INT REFERENCES departments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS staff_department_idx ON staff (department_id);

-- ── ฝ่ายตั้งต้นตามที่ผู้ใช้ยกตัวอย่างไว้ (§29) ───────────────
-- แก้ชื่อ/ลบได้จากหน้าจัดการฝ่าย · ON CONFLICT กันรันซ้ำ
INSERT INTO departments (name, sort_order) VALUES
    ('เลี้ยงไก่',        1),
    ('โรงงานอาหารสัตว์', 2),
    ('BIOGAS',          3),
    ('Office',          4)
ON CONFLICT (name) DO NOTHING;

-- =============================================================
-- ยังไม่ผูกพนักงานที่มีอยู่เข้ากับฝ่ายใด — เป็นข้อมูลจริงของฟาร์ม ให้ผู้ใช้เลือกเอง
-- จากหน้าจัดการพนักงาน (ตอนนี้ "ตำแหน่ง" ยังเป็นข้อความอิสระเหมือนเดิม)
-- =============================================================
