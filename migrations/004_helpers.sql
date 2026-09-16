-- =============================================================
-- RPF Calendar — Migration 004
-- ผู้ช่วยหลายคนต่อหนึ่งกิจกรรม (งานอย่างทำวัคซีนต้องใช้คนหลายคน)
-- รันด้วย: psql -U postgres -d rpf_calendar -f migrations\004_helpers.sql
-- =============================================================

-- assignee_id ยังเป็น "ผู้รับผิดชอบหลัก" คนเดียวเหมือนเดิม
-- ตารางนี้เก็บคนที่มาช่วย ซึ่งกดเริ่ม/สิ้นสุดงานได้เหมือนกัน
-- และเห็นงานนี้ใน "งานของฉัน" ด้วย
CREATE TABLE IF NOT EXISTS activity_helpers (
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    staff_id    INT NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, staff_id)
);

-- ค้นจากฝั่งคน ("งานไหนบ้างที่ฉันเป็นผู้ช่วย") ต้องเร็วพอๆ กับค้นจากฝั่งงาน
CREATE INDEX IF NOT EXISTS activity_helpers_staff_idx ON activity_helpers (staff_id);

-- แผนงานประจำก็ระบุทีมผู้ช่วยไว้ได้ ตัวสร้างจะคัดลอกไปให้ทุกรอบ
CREATE TABLE IF NOT EXISTS series_helpers (
    series_id INT NOT NULL REFERENCES activity_series(id) ON DELETE CASCADE,
    staff_id  INT NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    PRIMARY KEY (series_id, staff_id)
);

-- ── หมายเหตุ ─────────────────────────────────────────────────
-- ON DELETE CASCADE ที่ staff_id ต่างจากที่อื่นในระบบนี้ (ปกติใช้ SET NULL
-- เพื่อรักษาประวัติ) เพราะแถวนี้ไม่ใช่ประวัติ เป็นแค่ "ใครถูกมอบหมายให้ช่วย"
-- ตัวประวัติจริงอยู่ใน activity_log ซึ่งบันทึกชื่อคนกดไว้แยกต่างหากแล้ว
-- =============================================================
