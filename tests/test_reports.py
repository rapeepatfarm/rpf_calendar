"""ตรวจนิยามสถิติ — จุดที่ตีความผิดง่ายและไม่มีอะไรเตือน

`_with_rate` เป็นหัวใจของรายงานทั้งหน้า ถ้าตัวหารผิดจะไม่มี error ให้เห็น
แค่เปอร์เซ็นต์เพี้ยนเงียบๆ แล้วหัวหน้าตัดสินใจจากเลขที่ผิด
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import calgrid, reports  # noqa: E402


def bucket(on_time=0, late=0, missed=0, cancelled=0, still_open=0, total=None, minutes=0):
    return {"on_time": on_time, "late": late, "missed": missed, "cancelled": cancelled,
            "still_open": still_open, "minutes": minutes,
            "total": total if total is not None
            else on_time + late + missed + cancelled + still_open}


# ── % ทำตรงแผน ───────────────────────────────────────────────

def test_rate_counts_only_work_that_came_due():
    row = reports._with_rate(bucket(on_time=8, late=2))
    assert row["judged"] == 10
    assert row["on_time_pct"] == 80.0


def test_cancelled_is_excluded_from_the_denominator():
    """ยกเลิกแผนโดยตั้งใจ ไม่ใช่ความผิดพลาด — ต้องไม่ทำให้เปอร์เซ็นต์ตกลง"""
    without = reports._with_rate(bucket(on_time=8, late=2))
    with_cancels = reports._with_rate(bucket(on_time=8, late=2, cancelled=20))
    assert with_cancels["on_time_pct"] == without["on_time_pct"] == 80.0
    assert with_cancels["judged"] == 10


def test_open_work_is_excluded_from_the_denominator():
    """งานที่ยังไม่ถึงกำหนดหรือยังทำอยู่ ยังตัดสินไม่ได้ว่าตรงแผนหรือไม่"""
    row = reports._with_rate(bucket(on_time=5, still_open=15))
    assert row["judged"] == 5
    assert row["on_time_pct"] == 100.0


def test_missed_counts_against_the_rate():
    row = reports._with_rate(bucket(on_time=5, missed=5))
    assert row["on_time_pct"] == 50.0


def test_rate_is_none_when_nothing_came_due():
    """ยังไม่มีอะไรถึงกำหนด ต้องคืน None ไม่ใช่ 0% — ศูนย์เปอร์เซ็นต์สื่อว่าทำพลาดหมด"""
    row = reports._with_rate(bucket(still_open=9, cancelled=3))
    assert row["on_time_pct"] is None
    assert row["judged"] == 0


def test_rate_rounds_to_one_decimal():
    assert reports._with_rate(bucket(on_time=46, late=10, missed=5))["on_time_pct"] == 75.4


def test_all_outcomes_have_a_thai_label():
    for key in ("on_time", "late", "missed", "cancelled", "planned", "in_progress"):
        assert reports.OUTCOME_LABELS[key]


# ── มุมมองรายสัปดาห์ ─────────────────────────────────────────

def item(id_, start, end, all_day=False, start_time=None, priority=3):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return {"id": id_, "planned_date": s, "planned_end_date": e,
            "span_days": (e - s).days + 1, "priority": priority,
            "is_all_day": all_day, "planned_start_time": start_time,
            "title": f"งาน {id_}"}


MONDAY = date(2026, 8, 24)
TODAY = date(2026, 8, 24)


def test_week_of_snaps_back_to_monday():
    assert calgrid.week_of(date(2026, 8, 24)) == MONDAY      # จันทร์เอง
    assert calgrid.week_of(date(2026, 8, 30)) == MONDAY      # อาทิตย์ปลายสัปดาห์
    assert calgrid.week_of(date(2026, 8, 31)) == date(2026, 8, 31)


def test_week_has_seven_days_and_marks_today():
    week = calgrid.build_week(MONDAY, [], TODAY)
    assert len(week["days"]) == 7
    assert week["monday"] == MONDAY and week["sunday"] == date(2026, 8, 30)
    assert sum(1 for d in week["days"] if d["is_today"]) == 1


def test_multi_day_work_goes_to_the_bar_row_not_the_day_columns():
    """งานหลายวันต้องอยู่แถบบนแถวเดียว ไม่ใช่ซ้ำในทุกคอลัมน์ที่มันคาบ"""
    week = calgrid.build_week(MONDAY, [item(1, "2026-08-25", "2026-08-27")], TODAY)
    assert len(week["bars"]) == 1
    assert week["bars"][0]["col_start"] == 2 and week["bars"][0]["span"] == 3
    assert all(d["items"] == [] for d in week["days"])


def test_all_day_single_day_work_also_goes_to_the_bar_row():
    week = calgrid.build_week(MONDAY, [item(1, "2026-08-26", "2026-08-26", all_day=True)], TODAY)
    assert len(week["bars"]) == 1
    assert all(d["items"] == [] for d in week["days"])


def test_timed_work_goes_into_its_day_column():
    from datetime import time
    week = calgrid.build_week(
        MONDAY, [item(1, "2026-08-26", "2026-08-26", start_time=time(9, 0))], TODAY)
    assert week["bars"] == []
    wednesday = week["days"][2]
    assert wednesday["date"] == date(2026, 8, 26)
    assert [i["id"] for i in wednesday["items"]] == [1]


def test_bar_crossing_the_week_edge_is_clipped():
    week = calgrid.build_week(MONDAY, [item(1, "2026-08-22", "2026-08-26")], TODAY)
    bar = week["bars"][0]
    assert bar["col_start"] == 1 and bar["span"] == 3
    assert bar["clipped_left"] and not bar["clipped_right"]


def test_overlapping_bars_get_separate_lanes():
    week = calgrid.build_week(MONDAY, [
        item(1, "2026-08-24", "2026-08-26"),
        item(2, "2026-08-25", "2026-08-28"),
    ], TODAY)
    assert sorted(b["lane"] for b in week["bars"]) == [0, 1]
    assert week["lanes"] == 2


def test_work_outside_the_week_is_dropped():
    week = calgrid.build_week(MONDAY, [item(1, "2026-09-10", "2026-09-11")], TODAY)
    assert week["bars"] == []
    assert all(d["items"] == [] for d in week["days"])
