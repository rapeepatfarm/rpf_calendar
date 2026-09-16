"""ตรวจการนับรอบถัดไปจากวันที่ทำเสร็จจริง (โหมด after_done)

กรณีตัวอย่างจากหน้างานจริง: แผน 15 ต.ค. ทุก 3 เดือน แต่ทำเสร็จช้าไป 15 วัน
รอบถัดไปต้องเลื่อนตามไปด้วย ไม่ใช่กลับไปเป็นวันที่ 15 เหมือนเดิม
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import recurrence  # noqa: E402


def series(**kw) -> dict:
    base = {
        "freq": "monthly_day", "interval": 1, "starts_on": date(2026, 1, 1),
        "ends_on": None, "max_count": None, "byweekday": None, "bymonthday": None,
        "nth_week": None, "nth_weekday": None, "bymonth": None, "byday": None,
        "duration_days": 1, "anchor_mode": recurrence.ANCHOR_AFTER_DONE,
    }
    return {**base, **kw}


# ── กรณีที่ผู้ใช้ยกตัวอย่างมา ────────────────────────────────

def test_quarterly_plan_shifts_when_work_finishes_late():
    """แผน 15 ต.ค. ทุก 3 เดือน · เสร็จจริง 30 ต.ค. -> รอบถัดไป 30 ม.ค. ไม่ใช่ 15 ม.ค."""
    plan = series(interval=3, bymonthday=15, starts_on=date(2026, 10, 15))
    assert recurrence.next_after(plan, date(2026, 10, 30)) == date(2027, 1, 30)


def test_quarterly_plan_shifts_when_work_finishes_early():
    """เลื่อนเข้าก็ต้องขยับตามเหมือนกัน — เสร็จ 5 ต.ค. -> รอบถัดไป 5 ม.ค."""
    plan = series(interval=3, bymonthday=15, starts_on=date(2026, 10, 15))
    assert recurrence.next_after(plan, date(2026, 10, 5)) == date(2027, 1, 5)


def test_on_time_completion_keeps_the_original_rhythm():
    plan = series(interval=3, bymonthday=15, starts_on=date(2026, 10, 15))
    assert recurrence.next_after(plan, date(2026, 10, 15)) == date(2027, 1, 15)


# ── คาบแบบอื่น ───────────────────────────────────────────────

def test_monthly_counts_one_month_from_completion():
    assert recurrence.next_after(series(interval=1), date(2026, 3, 20)) == date(2026, 4, 20)


def test_yearly_counts_a_full_year_from_completion():
    plan = series(freq="yearly", interval=1)
    assert recurrence.next_after(plan, date(2026, 3, 20)) == date(2027, 3, 20)


def test_daily_counts_days_from_completion():
    plan = series(freq="daily", interval=10)
    assert recurrence.next_after(plan, date(2026, 3, 20)) == date(2026, 3, 30)


def test_weekly_counts_weeks_from_completion():
    plan = series(freq="weekly", interval=2)
    assert recurrence.next_after(plan, date(2026, 3, 20)) == date(2026, 4, 3)


def test_monthly_nth_uses_the_period_not_the_weekday_rule():
    """โหมดนี้สนใจระยะห่าง ไม่ดึงกลับไปหา 'จันทร์ที่ 2' ของเดือนปลายทาง

    ถ้าดึงกลับ ระยะห่างที่ผู้ใช้ตั้งใจจะเพี้ยนไปได้หลายวัน
    """
    plan = series(freq="monthly_nth", interval=2, nth_week=2, nth_weekday=0)
    assert recurrence.next_after(plan, date(2026, 3, 20)) == date(2026, 5, 20)


# ── วันสิ้นเดือน ─────────────────────────────────────────────

def test_end_of_month_completion_clamps_into_a_shorter_month():
    """เสร็จ 31 ม.ค. + 1 เดือน ต้องได้ 28 ก.พ. ไม่ใช่ข้ามไป 3 มี.ค."""
    assert recurrence.next_after(series(interval=1), date(2027, 1, 31)) == date(2027, 2, 28)


def test_end_of_month_completion_uses_29_in_a_leap_year():
    assert recurrence.next_after(series(interval=1), date(2028, 1, 31)) == date(2028, 2, 29)


# ── ขอบเขตของแผน ─────────────────────────────────────────────

def test_stops_when_the_next_date_would_pass_the_end_of_the_plan():
    """รอบถัดไปคือ 20 เม.ย. แต่แผนจบ 10 เม.ย. — ต้องไม่สร้างรอบนั้น"""
    plan = series(interval=1, ends_on=date(2026, 4, 10))
    assert recurrence.next_after(plan, date(2026, 3, 20)) is None

    # ถ้าแผนจบหลังจากนั้น รอบเดียวกันต้องสร้างได้ตามปกติ
    plan_longer = series(interval=1, ends_on=date(2026, 12, 31))
    assert recurrence.next_after(plan_longer, date(2026, 3, 20)) == date(2026, 4, 20)


def test_stops_after_reaching_the_maximum_number_of_rounds():
    plan = series(interval=1, max_count=3)
    assert recurrence.next_after(plan, date(2026, 3, 20), made_count=2) == date(2026, 4, 20)
    assert recurrence.next_after(plan, date(2026, 3, 20), made_count=3) is None


# ── คำบรรยายภาษาไทย ──────────────────────────────────────────

def test_description_says_it_follows_actual_completion():
    text = recurrence.describe(series(interval=3, bymonthday=15))
    assert "นับจากวันที่ทำเสร็จจริง" in text
    # ต้องไม่หลงเหลือข้อความ "วันที่ 15 ของเดือน" ที่ไม่เป็นจริงในโหมดนี้
    assert "วันที่ 15 ของเดือน" not in text


def test_description_of_fixed_mode_is_unchanged():
    plan = series(interval=1, bymonthday=15, anchor_mode=recurrence.ANCHOR_FIXED)
    assert recurrence.describe(plan) == "วันที่ 15 ของเดือน"


def test_fixed_mode_still_generates_a_full_calendar_series():
    """โหมดเดิมต้องไม่เปลี่ยนพฤติกรรม"""
    plan = series(interval=3, bymonthday=15, starts_on=date(2026, 10, 15),
                  anchor_mode=recurrence.ANCHOR_FIXED)
    got = recurrence.occurrences(plan, date(2027, 5, 1))
    assert got == [date(2026, 10, 15), date(2027, 1, 15), date(2027, 4, 15)]
