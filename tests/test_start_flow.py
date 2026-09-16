"""ตรวจการยืนยันก่อนเริ่มงานและการถอนการเริ่ม

`start_state` ตัดสินว่ากล่องยืนยันจะขึ้นข้อความไหน และเป็นตัวเดียวกับที่เซิร์ฟเวอร์
ใช้ตัดสินว่าจะบังคับให้ยืนยันหรือไม่ · ถ้าคำนวณผิด ผู้ใช้จะเริ่มงานก่อนกำหนดได้
โดยไม่มีอะไรเตือน
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import activities as act  # noqa: E402

TODAY = date(2026, 8, 24)


def work(start, end=None):
    s = date.fromisoformat(start)
    return {"planned_date": s,
            "planned_end_date": date.fromisoformat(end) if end else s}


def state_of(start, end=None):
    return act.start_state(work(start, end), TODAY)


# ── วันนี้อยู่ตรงไหนของช่วงแผน ────────────────────────────────

def test_before_the_planned_day_is_early():
    got = state_of("2026-08-27")
    assert got["start_state"] == act.START_EARLY
    assert got["start_days"] == 3


def test_the_planned_day_itself_is_ontime():
    assert state_of("2026-08-24")["start_state"] == act.START_ONTIME


def test_after_the_planned_day_is_late():
    got = state_of("2026-08-20")
    assert got["start_state"] == act.START_LATE
    assert got["start_days"] == 4


# ── งานหลายวัน — ทุกวันในช่วงถือว่าถึงกำหนด ──────────────────

def test_first_day_of_a_multi_day_span_is_ontime():
    assert state_of("2026-08-24", "2026-08-27")["start_state"] == act.START_ONTIME


def test_middle_of_a_multi_day_span_is_still_ontime():
    """งาน 22–27 ส.ค. กดเริ่มวันที่ 24 ต้องไม่ขึ้นว่าเลยกำหนด — ยังอยู่ในช่วง"""
    assert state_of("2026-08-22", "2026-08-27")["start_state"] == act.START_ONTIME


def test_last_day_of_a_multi_day_span_is_ontime():
    assert state_of("2026-08-20", "2026-08-24")["start_state"] == act.START_ONTIME


def test_after_a_multi_day_span_is_late_counted_from_the_end():
    got = state_of("2026-08-15", "2026-08-20")
    assert got["start_state"] == act.START_LATE
    assert got["start_days"] == 4       # นับจากวันสุดท้าย ไม่ใช่วันแรก


def test_before_a_multi_day_span_is_early_counted_from_the_start():
    got = state_of("2026-08-28", "2026-09-02")
    assert got["start_state"] == act.START_EARLY
    assert got["start_days"] == 4


def test_missing_end_date_falls_back_to_the_start_date():
    """ข้อมูลเก่าที่ยังไม่มี planned_end_date ต้องไม่ทำให้พัง"""
    got = act.start_state({"planned_date": date(2026, 8, 20)}, TODAY)
    assert got["start_state"] == act.START_LATE


def test_state_uses_todays_date_when_not_given():
    from services import thaidate
    today = thaidate.today()
    assert act.start_state({"planned_date": today})["start_state"] == act.START_ONTIME
    assert act.start_state(
        {"planned_date": today + timedelta(days=1)})["start_state"] == act.START_EARLY


# ── ป้ายกำกับ ────────────────────────────────────────────────

def test_unstart_has_a_thai_label_for_the_timeline():
    assert act.ACTION_LABELS["unstarted"]
