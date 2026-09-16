"""ตรวจการจัดวางแถบกิจกรรมในปฏิทิน

จุดที่พลาดง่าย: แถบซ้อนทับกันในชั้นเดียว หรือแถบที่ข้ามสัปดาห์ถูกตัดผิดตำแหน่ง
ทั้งสองอย่างมองด้วยตาบนหน้าจอแล้วดูเหมือนถูกจนกว่าจะเจอเดือนที่งานเยอะพอดี
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import calgrid  # noqa: E402


def item(id_, start, end, priority=3):
    return {"id": id_, "planned_date": date.fromisoformat(start),
            "planned_end_date": date.fromisoformat(end),
            "span_days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
            "priority": priority, "title": f"งาน {id_}"}


# สิงหาคม 2026 เริ่มวันเสาร์ · ตารางเริ่มวันจันทร์ที่ 27 ก.ค.
YEAR, MONTH, TODAY = 2026, 8, date(2026, 8, 24)


def week_with(weeks, iso):
    """หาสัปดาห์ที่มีวันที่นี้อยู่"""
    target = date.fromisoformat(iso)
    return next(w for w in weeks if w["days"][0]["date"] <= target <= w["days"][6]["date"])


def test_grid_covers_whole_month_in_full_weeks():
    weeks = calgrid.build_weeks(YEAR, MONTH, [], TODAY)
    assert all(len(w["days"]) == 7 for w in weeks)
    assert weeks[0]["days"][0]["date"] == date(2026, 7, 27)      # วันจันทร์
    assert weeks[0]["days"][0]["date"].weekday() == 0
    assert weeks[-1]["days"][6]["date"] >= date(2026, 8, 31)


def test_single_day_bar_spans_one_column():
    weeks = calgrid.build_weeks(YEAR, MONTH, [item(1, "2026-08-25", "2026-08-25")], TODAY)
    bar = week_with(weeks, "2026-08-25")["bars"][0]
    assert bar["span"] == 1
    assert bar["col_start"] == 2                                  # อังคาร
    assert not bar["clipped_left"] and not bar["clipped_right"]


def test_multi_day_bar_spans_the_whole_range():
    """25–27 ส.ค. ต้องได้แถบเดียวคร่อม 3 วัน ไม่ใช่ 3 แถบแยก"""
    weeks = calgrid.build_weeks(YEAR, MONTH, [item(1, "2026-08-25", "2026-08-27")], TODAY)
    bars = [b for w in weeks for b in w["bars"]]
    assert len(bars) == 1
    assert bars[0]["col_start"] == 2 and bars[0]["span"] == 3


def test_bar_crossing_weeks_is_split_and_marked_as_clipped():
    """งาน 28 ส.ค. – 2 ก.ย. ต้องตัดเป็น 2 ท่อน และบอกว่าท่อนไหนยังไม่จบ"""
    weeks = calgrid.build_weeks(YEAR, MONTH, [item(1, "2026-08-28", "2026-09-02")], TODAY)
    bars = [b for w in weeks for b in w["bars"]]
    assert len(bars) == 2

    first, second = bars
    assert first["col_start"] == 5 and first["span"] == 3         # ศุกร์–อาทิตย์
    assert not first["clipped_left"] and first["clipped_right"]

    assert second["col_start"] == 1 and second["span"] == 3       # จันทร์–พุธ
    assert second["clipped_left"] and not second["clipped_right"]


def test_overlapping_bars_go_to_different_lanes():
    weeks = calgrid.build_weeks(YEAR, MONTH, [
        item(1, "2026-08-24", "2026-08-26"),
        item(2, "2026-08-25", "2026-08-27"),
        item(3, "2026-08-26", "2026-08-28"),
    ], TODAY)
    week = week_with(weeks, "2026-08-25")
    assert sorted(b["lane"] for b in week["bars"]) == [0, 1, 2]
    assert week["lanes"] == 3


def test_non_overlapping_bars_reuse_the_same_lane():
    """แถบที่ไม่ชนกันต้องอยู่ชั้นเดียวกัน ไม่งั้นแถวปฏิทินจะสูงเกินจำเป็น"""
    weeks = calgrid.build_weeks(YEAR, MONTH, [
        item(1, "2026-08-24", "2026-08-25"),
        item(2, "2026-08-27", "2026-08-28"),
    ], TODAY)
    week = week_with(weeks, "2026-08-24")
    assert [b["lane"] for b in week["bars"]] == [0, 0]
    assert week["lanes"] == 1


def test_bars_beyond_max_lanes_become_a_more_count():
    items = [item(i, "2026-08-25", "2026-08-25") for i in range(1, 8)]
    weeks = calgrid.build_weeks(YEAR, MONTH, items, TODAY)
    week = week_with(weeks, "2026-08-25")
    assert len(week["bars"]) == calgrid.MAX_LANES
    day = next(d for d in week["days"] if d["date"] == date(2026, 8, 25))
    assert day["more"] == 7 - calgrid.MAX_LANES


def test_longer_bars_are_placed_above_shorter_ones():
    weeks = calgrid.build_weeks(YEAR, MONTH, [
        item(1, "2026-08-25", "2026-08-25"),
        item(2, "2026-08-25", "2026-08-28"),
    ], TODAY)
    week = week_with(weeks, "2026-08-25")
    long_bar = next(b for b in week["bars"] if b["item"]["id"] == 2)
    short_bar = next(b for b in week["bars"] if b["item"]["id"] == 1)
    assert long_bar["lane"] < short_bar["lane"]


def test_days_are_flagged_for_month_and_today():
    weeks = calgrid.build_weeks(YEAR, MONTH, [], TODAY)
    days = [d for w in weeks for d in w["days"]]
    assert sum(1 for d in days if d["in_month"]) == 31
    assert sum(1 for d in days if d["is_today"]) == 1


# ── แผนที่วัน -> กิจกรรม (ใช้ในแผงรายละเอียด) ────────────────

def test_day_index_lists_every_day_a_bar_covers():
    index = calgrid.day_index([item(7, "2026-08-25", "2026-08-27")])
    assert index == {"2026-08-25": [7], "2026-08-26": [7], "2026-08-27": [7]}


def test_day_index_keeps_multiple_activities_per_day():
    index = calgrid.day_index([
        item(1, "2026-08-25", "2026-08-25"),
        item(2, "2026-08-24", "2026-08-26"),
    ])
    assert index["2026-08-25"] == [2, 1]      # แถบยาวมาก่อน เหมือนลำดับในปฏิทิน
