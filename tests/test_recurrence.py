"""ตรวจกติกาการทำซ้ำ — เน้นรายเดือนและรายปีที่ฟาร์มใช้จริง

กรณีที่พังแล้วรู้ตัวยากที่สุดคือวันสิ้นเดือนกับ 29 ก.พ. เพราะจะเงียบหายไปทั้งรอบ
โดยไม่มี error ให้เห็น กว่าจะรู้ก็ตอนงานไม่โผล่ในปฏิทินแล้ว
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
        "duration_days": 1,
    }
    return {**base, **kw}


# ── รายเดือนตามวันที่ (แบบที่ฟาร์มใช้มากที่สุด) ─────────────

def test_monthly_day_every_month():
    got = recurrence.occurrences(
        series(bymonthday=5, starts_on=date(2026, 1, 1)), date(2026, 4, 30))
    assert got == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5), date(2026, 4, 5)]


def test_monthly_day_31_falls_back_to_end_of_month():
    """สั่ง 'ทุกวันที่ 31' ต้องมีครบทุกเดือน ไม่ใช่ข้ามเดือนที่ไม่มีวันที่ 31

    rrule มาตรฐานจะข้ามเดือนสั้นทิ้ง ซึ่งทำให้ 'งานสิ้นเดือน' หายไป 5 เดือนต่อปี
    """
    got = recurrence.occurrences(
        series(bymonthday=31, starts_on=date(2027, 1, 1)), date(2027, 6, 30))
    assert got == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31),
                   date(2027, 4, 30), date(2027, 5, 31), date(2027, 6, 30)]


def test_monthly_day_31_uses_29_in_leap_february():
    got = recurrence.occurrences(
        series(bymonthday=31, starts_on=date(2028, 2, 1)), date(2028, 2, 29))
    assert got == [date(2028, 2, 29)]


def test_monthly_day_quarterly():
    got = recurrence.occurrences(
        series(bymonthday=1, interval=3, starts_on=date(2026, 1, 1)), date(2026, 12, 31))
    assert got == [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]


# ── รายเดือนตามสัปดาห์ ───────────────────────────────────────

def test_monthly_nth_second_monday():
    got = recurrence.occurrences(
        series(freq="monthly_nth", nth_week=2, nth_weekday=0,
               starts_on=date(2026, 8, 1)), date(2026, 10, 31))
    assert got == [date(2026, 8, 10), date(2026, 9, 14), date(2026, 10, 12)]
    assert all(d.weekday() == 0 for d in got)


def test_monthly_nth_last_friday():
    got = recurrence.occurrences(
        series(freq="monthly_nth", nth_week=-1, nth_weekday=4,
               starts_on=date(2026, 8, 1)), date(2026, 9, 30))
    assert got == [date(2026, 8, 28), date(2026, 9, 25)]


def test_monthly_nth_skips_month_without_fifth_weekday():
    """'ศุกร์ที่ 5' มีแค่บางเดือน — เดือนที่ไม่มีต้องข้าม ไม่ใช่เลื่อนไปเดือนถัดไป"""
    got = recurrence.occurrences(
        series(freq="monthly_nth", nth_week=5, nth_weekday=4,
               starts_on=date(2026, 1, 1)), date(2026, 3, 31))
    assert got == [date(2026, 1, 30)]     # ก.พ. และ มี.ค. 2026 ไม่มีศุกร์ที่ 5


# ── รายปี ────────────────────────────────────────────────────

def test_yearly_fixed_date():
    got = recurrence.occurrences(
        series(freq="yearly", bymonth=3, byday=15, starts_on=date(2026, 1, 1)),
        date(2029, 12, 31))
    assert got == [date(2026, 3, 15), date(2027, 3, 15),
                   date(2028, 3, 15), date(2029, 3, 15)]


def test_yearly_feb_29_falls_back_to_28():
    """29 ก.พ. รายปี ต้องมีทุกปี ปีที่ไม่ใช่อธิกสุรทินใช้ 28 ก.พ."""
    got = recurrence.occurrences(
        series(freq="yearly", bymonth=2, byday=29, starts_on=date(2027, 1, 1)),
        date(2029, 12, 31))
    assert got == [date(2027, 2, 28), date(2028, 2, 29), date(2029, 2, 28)]


# ── รายสัปดาห์ / รายวัน ──────────────────────────────────────

def test_weekly_picks_selected_weekdays():
    got = recurrence.occurrences(
        series(freq="weekly", byweekday=[1, 4], starts_on=date(2026, 8, 24)),
        date(2026, 9, 6))
    assert got == [date(2026, 8, 25), date(2026, 8, 28),
                   date(2026, 9, 1), date(2026, 9, 4)]


def test_weekly_every_two_weeks_stays_on_same_week_cycle():
    got = recurrence.occurrences(
        series(freq="weekly", byweekday=[0], interval=2, starts_on=date(2026, 8, 24)),
        date(2026, 10, 5))
    assert got == [date(2026, 8, 24), date(2026, 9, 7),
                   date(2026, 9, 21), date(2026, 10, 5)]


def test_daily_with_interval():
    got = recurrence.occurrences(
        series(freq="daily", interval=3, starts_on=date(2026, 8, 24)), date(2026, 9, 2))
    assert got == [date(2026, 8, 24), date(2026, 8, 27),
                   date(2026, 8, 30), date(2026, 9, 2)]


# ── ขอบเขตของแผน ─────────────────────────────────────────────

def test_ends_on_cuts_the_series():
    got = recurrence.occurrences(
        series(bymonthday=1, starts_on=date(2026, 1, 1), ends_on=date(2026, 3, 15)),
        date(2026, 12, 31))
    assert got == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


def test_max_count_limits_the_series():
    got = recurrence.occurrences(
        series(bymonthday=1, max_count=2, starts_on=date(2026, 1, 1)), date(2026, 12, 31))
    assert got == [date(2026, 1, 1), date(2026, 2, 1)]


def test_since_skips_already_generated_dates():
    """ตัวสร้างเรียกด้วย since เพื่อไม่ต้องคำนวณรอบเก่าซ้ำทุกวัน"""
    got = recurrence.occurrences(
        series(bymonthday=1, starts_on=date(2026, 1, 1)), date(2026, 5, 31),
        since=date(2026, 4, 1))
    assert got == [date(2026, 4, 1), date(2026, 5, 1)]


def test_no_occurrences_when_until_is_before_start():
    assert recurrence.occurrences(series(starts_on=date(2027, 1, 1)), date(2026, 12, 31)) == []


def test_bad_interval_does_not_hang():
    """interval 0 ที่หลุดเข้ามาต้องไม่ทำให้วนไม่รู้จบ"""
    got = recurrence.occurrences(
        series(freq="daily", interval=0, starts_on=date(2026, 1, 1)), date(2026, 1, 5))
    assert got == [date(2026, 1, i) for i in range(1, 6)]


# ── คำบรรยายภาษาไทย ──────────────────────────────────────────

def test_describe_monthly_day():
    assert "วันที่ 5 ของเดือน" in recurrence.describe(series(bymonthday=5))


def test_describe_month_end_explains_the_clamping():
    text = recurrence.describe(series(bymonthday=31))
    assert "วันสุดท้าย" in text


def test_describe_monthly_nth():
    text = recurrence.describe(series(freq="monthly_nth", nth_week=2, nth_weekday=0))
    assert "วันจันทร์ที่ 2 ของเดือน" == text


def test_describe_includes_multi_day_span():
    text = recurrence.describe(series(bymonthday=1, duration_days=3))
    assert "ครั้งละ 3 วัน" in text
