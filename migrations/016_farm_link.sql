-- =============================================================
-- RPF Calendar — Migration 016
-- กิจกรรมที่สร้างในปฏิทินแล้วส่งไปเป็นกิจกรรมฝูงไก่ใน RPF Farm
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\016_farm_link.sql
-- =============================================================
--
-- ผู้ใช้ขอ (2026-10-02): ประเภทกิจกรรมมีช่องติ๊ก "ส่งไป RPF Farm" — ถ้าติ๊ก ฟอร์มกิจกรรม
-- ต้องให้เลือกฝูงไก่ (และวัคซีน/กิจกรรมจากทะเบียนฟาร์ม) แล้วฟาร์มจะมาดึงไปสร้างแผนของฝูงเอง
--
-- ทิศทางข้อมูลไม่เปลี่ยน — ปฏิทินไม่เขียนลง DB ของฟาร์ม
-- ฟาร์มดึงผ่าน rpf_farm/services/calendar_pull.pull_calendar_activities() (ปุ่มเดิมในหน้า /calendar)
--
-- ธงอยู่ที่ประเภท แต่ "ข้อมูลที่ส่งจริง" อยู่ที่ตัวกิจกรรม (farm_flock_id ...)
-- ฟาร์มอ่านจากกิจกรรม ไม่ได้อ่านธงของประเภท — ถ้าวันหลังเอาติ๊กที่ประเภทออก
-- งานที่ส่งไปแล้วยังผูกกับฝูงเดิม ไม่หายจากฟาร์มเงียบๆ

ALTER TABLE activity_categories
    ADD COLUMN IF NOT EXISTS farm_sync BOOLEAN NOT NULL DEFAULT FALSE;

-- กุญแจเป็น id ของฟาร์ม (เลขนิ่ง) · *_code / *_name เป็นสำเนาไว้แสดงผลเท่านั้น
-- ห้ามใช้สำเนาเป็นกุญแจ — ฝั่งฟาร์มเปลี่ยนชื่อวัคซีน/รหัสฝูงได้เสมอ
ALTER TABLE activities
    ADD COLUMN IF NOT EXISTS farm_flock_id   INT,
    ADD COLUMN IF NOT EXISTS farm_flock_code TEXT,
    ADD COLUMN IF NOT EXISTS farm_kind       TEXT,
    ADD COLUMN IF NOT EXISTS farm_item_id    INT,
    ADD COLUMN IF NOT EXISTS farm_item_name  TEXT;

-- ครบทั้งชุดหรือว่างทั้งชุด — ส่งไปครึ่งเดียวฟาร์มลงบันทึกไม่ได้
ALTER TABLE activities DROP CONSTRAINT IF EXISTS activities_farm_link_chk;
ALTER TABLE activities ADD CONSTRAINT activities_farm_link_chk CHECK (
    (farm_flock_id IS NULL AND farm_kind IS NULL AND farm_item_id IS NULL)
    OR (farm_flock_id IS NOT NULL AND farm_kind IN ('vaccine', 'activity')
        AND farm_item_id IS NOT NULL)
);

-- แผนงานประจำผูกฝูงได้ด้วย (เช่น Spray ND/IB ไก่ไข่รายเล้า ใช้ประเภท "วัคซีนไก่ไข่")
-- ทุกรอบที่ scheduler สร้างจะได้ค่าชุดนี้ไป
ALTER TABLE activity_series
    ADD COLUMN IF NOT EXISTS farm_flock_id   INT,
    ADD COLUMN IF NOT EXISTS farm_flock_code TEXT,
    ADD COLUMN IF NOT EXISTS farm_kind       TEXT,
    ADD COLUMN IF NOT EXISTS farm_item_id    INT,
    ADD COLUMN IF NOT EXISTS farm_item_name  TEXT;

ALTER TABLE activity_series DROP CONSTRAINT IF EXISTS activity_series_farm_link_chk;
ALTER TABLE activity_series ADD CONSTRAINT activity_series_farm_link_chk CHECK (
    (farm_flock_id IS NULL AND farm_kind IS NULL AND farm_item_id IS NULL)
    OR (farm_flock_id IS NOT NULL AND farm_kind IN ('vaccine', 'activity')
        AND farm_item_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS activities_farm_flock_idx
    ON activities (farm_flock_id) WHERE farm_flock_id IS NOT NULL;
