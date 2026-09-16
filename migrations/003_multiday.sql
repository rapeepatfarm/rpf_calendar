-- =============================================================
-- RPF Calendar — Migration 003
-- กิจกรรมที่กินเวลาหลายวัน (แสดงเป็นแถบต่อเนื่องในปฏิทิน)
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\003_multiday.sql
-- =============================================================

-- planned_date = วันเริ่ม · planned_end_date = วันสิ้นสุด
-- งานวันเดียวเก็บสองค่านี้เท่ากัน จึงไม่ต้องแยกกรณีตอน query
ALTER TABLE activities ADD COLUMN IF NOT EXISTS planned_end_date DATE;
UPDATE activities SET planned_end_date = planned_date WHERE planned_end_date IS NULL;
ALTER TABLE activities ALTER COLUMN planned_end_date SET NOT NULL;

ALTER TABLE activities DROP CONSTRAINT IF EXISTS activities_date_order_chk;
ALTER TABLE activities ADD CONSTRAINT activities_date_order_chk
    CHECK (planned_end_date >= planned_date);

-- ปฏิทินถามว่า "งานไหนคาบเกี่ยวช่วงวันที่นี้บ้าง" คือ
--   planned_date <= ปลายช่วง AND planned_end_date >= ต้นช่วง
-- index บน planned_date เดิมช่วยครึ่งแรก อีก index ช่วยครึ่งหลัง
CREATE INDEX IF NOT EXISTS activities_end_date_idx ON activities (planned_end_date);

-- แผนงานประจำก็กินเวลาหลายวันได้ เช่น "ล้างโรงเรือน 3 วัน ทุกต้นเดือน"
ALTER TABLE activity_series ADD COLUMN IF NOT EXISTS duration_days INT NOT NULL DEFAULT 1;
ALTER TABLE activity_series DROP CONSTRAINT IF EXISTS series_duration_days_chk;
ALTER TABLE activity_series ADD CONSTRAINT series_duration_days_chk
    CHECK (duration_days BETWEEN 1 AND 366);

-- ── หมายเหตุ ─────────────────────────────────────────────────
-- งานหลายวันเปลี่ยนนิยาม "งานของวันนี้" และ "งานค้าง":
--   งานวันนี้ = planned_date <= วันนี้ <= planned_end_date  (อยู่ในช่วงที่ต้องทำ)
--   งานค้าง   = planned_end_date < วันนี้ และยังไม่ได้กดเริ่ม (ช่วงผ่านไปแล้ว)
-- ถ้าใช้ planned_date อย่างเดียว งานที่กินเวลา 3 วันจะกลายเป็นงานค้างตั้งแต่วันที่สอง
-- =============================================================
