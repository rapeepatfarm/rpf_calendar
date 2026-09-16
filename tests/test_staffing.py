"""ตรรกะล้วนของทะเบียนวันลา (v2 เฟส B) — ไม่แตะ DB

ส่วนที่ต้องมี DB (ตรวจซ้อน ครึ่งวันที่เซิร์ฟเวอร์ การย้ายข้อมูล) ตรวจด้วยสคริปต์
สถานการณ์บน rpf_calendar_test แทน
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import calgrid, staffing  # noqa: E402


def leave(id, staff_id, start, end, part="full", name="สมชาย", note=""):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return {"id": id, "staff_id": staff_id, "date_from": s, "date_to": e,
            "span_days": (e - s).days + 1, "part": part,
            "staff_name": name, "staff_color": "#336699", "staff_code": "",
            "department_id": None, "department_name": None,
            "type_name": "ลากิจ", "type_color": "#e08c00", "note": note}


# ── ใครลาวันนี้ ─────────────────────────────────────────────

def test_leaves_on_includes_every_day_of_the_range():
    rows = [leave(1, 9, "2026-09-10", "2026-09-12")]
    assert staffing.leaves_on(rows, date(2026, 9, 10)) == rows
    assert staffing.leaves_on(rows, date(2026, 9, 12)) == rows
    assert staffing.leaves_on(rows, date(2026, 9, 13)) == []
    assert staffing.leaves_on(rows, date(2026, 9, 9)) == []


def test_half_day_leave_still_counts_as_away_that_day():
    """ครึ่งวันก็คือ "ลา" สำหรับการเช็กความว่าง — เฟส D จะกันไม่ให้เลือกเป็นผู้ปฏิบัติงาน"""
    rows = [leave(1, 9, "2026-09-10", "2026-09-10", part="am")]
    assert len(staffing.leaves_on(rows, date(2026, 9, 10))) == 1


# ── แถบบนปฏิทิน ─────────────────────────────────────────────

def test_bar_items_carry_the_fields_calgrid_needs_and_a_leave_flag():
    bar = staffing.bar_items([leave(5, 9, "2026-09-10", "2026-09-12")])[0]
    assert bar["kind"] == "leave"
    assert bar["planned_date"] == date(2026, 9, 10)
    assert bar["planned_end_date"] == date(2026, 9, 12)
    assert bar["span_days"] == 3
    assert bar["id"] < 0                      # ไม่ทับ id กิจกรรมใน _sort_key
    assert bar["leave_id"] == 5


def test_bar_label_tells_full_day_from_half_day():
    full, am, pm = staffing.bar_items([
        leave(1, 9, "2026-09-10", "2026-09-10"),
        leave(2, 9, "2026-09-11", "2026-09-11", part="am"),
        leave(3, 9, "2026-09-12", "2026-09-12", part="pm"),
    ])
    assert full["label"] == "ลา สมชาย"
    assert am["label"] == "ลาเช้า สมชาย"
    assert pm["label"] == "ลาบ่าย สมชาย"


def vaccines(n, start="2026-09-17", end="2026-09-20"):
    return [{"id": i, "planned_date": date.fromisoformat(start),
             "planned_end_date": date.fromisoformat(end), "span_days": 4, "priority": 1}
            for i in range(1, n + 1)]


def week_with(weeks, day):
    return next(w for w in weeks if any(d["date"] == day for d in w["days"]))


def test_leave_bars_do_not_eat_the_activity_lane_budget():
    """วันวัคซีน 4 รายการกินครบ MAX_LANES — แถบลาต้องยังขึ้น และวัคซีนต้องขึ้นครบทั้ง 4

    เจอจริงในข้อมูลฟาร์ม (17–20 ก.ย. 69 มีวัคซีน 4 รายการ) แถบลาวันอาทิตย์หายเข้า "+3"
    ทางแก้: การลาได้ชั้นต่างหาก (ชั้นบนสุด) ไม่นับรวมโควตาของกิจกรรม
    """
    bars = staffing.bar_items([leave(1, 9, "2026-09-20", "2026-09-22")])
    week = week_with(calgrid.build_weeks(2026, 9, vaccines(4) + bars, date(2026, 9, 16)),
                     date(2026, 9, 20))
    kinds = [b["item"].get("kind", "activity") for b in week["bars"]]
    assert kinds.count("leave") == 1
    assert kinds.count("activity") == 4
    assert week["lanes"] == 5
    assert all(d["more"] == 0 for d in week["days"])
    assert next(b for b in week["bars"] if b["item"].get("kind") == "leave")["lane"] == 0


def test_leave_lanes_are_capped_so_a_holiday_week_stays_readable():
    """ลากัน 5 คนวันเดียว — ขึ้นแค่ MAX_LEAVE_LANES ที่เหลือไป "+N" · กิจกรรมยังได้โควตาเต็ม"""
    rows = [leave(i, i, "2026-09-20", "2026-09-20", name=f"คน{i}") for i in range(1, 6)]
    week = week_with(calgrid.build_weeks(2026, 9, vaccines(4) + staffing.bar_items(rows),
                                         date(2026, 9, 16)), date(2026, 9, 20))
    kinds = [b["item"].get("kind", "activity") for b in week["bars"]]
    assert kinds.count("leave") == calgrid.MAX_LEAVE_LANES
    assert kinds.count("activity") == 4
    sunday = next(d for d in week["days"] if d["date"] == date(2026, 9, 20))
    assert sunday["more"] == 5 - calgrid.MAX_LEAVE_LANES


def test_activity_overflow_still_works_when_no_leave_in_the_week():
    """ไม่มีการลา = พฤติกรรมเดิมเป๊ะ (5 กิจกรรม → 4 ชั้น + "+1")"""
    week = week_with(calgrid.build_weeks(2026, 9, vaccines(5), date(2026, 9, 16)),
                     date(2026, 9, 17))
    assert week["lanes"] == calgrid.MAX_LANES
    assert next(d for d in week["days"] if d["date"] == date(2026, 9, 17))["more"] == 1


def test_leave_bars_share_lanes_with_activities():
    """การลาใช้กลไกจัดชั้นเดียวกับกิจกรรม — สองแถบวันเดียวกันต้องอยู่คนละชั้น"""
    activity = {"id": 100, "planned_date": date(2026, 9, 10),
                "planned_end_date": date(2026, 9, 10), "span_days": 1, "priority": 3}
    bars = staffing.bar_items([leave(1, 9, "2026-09-10", "2026-09-11")])
    weeks = calgrid.build_weeks(2026, 9, [activity] + bars, date(2026, 9, 16))
    week = next(w for w in weeks if any(d["date"] == date(2026, 9, 10) for d in w["days"]))
    lanes = {b["item"].get("kind", "activity"): b["lane"] for b in week["bars"]}
    assert set(lanes) == {"activity", "leave"}
    assert lanes["activity"] != lanes["leave"]


# ── ข้อมูลสำหรับแถบพนักงาน ──────────────────────────────────

def test_panel_data_sends_raw_iso_dates_for_js_and_thai_text_for_display():
    row = staffing.panel_data([leave(1, 9, "2026-09-10", "2026-09-12", note="ไปงานบวช")])[0]
    assert row["from"] == "2026-09-10" and row["to"] == "2026-09-12"
    assert row["when"] == "10 ก.ย. 69 – 12 ก.ย. 69 (3 วัน)"     # รูปแบบเดียวกับกิจกรรม
    assert row["part_label"] == "ทั้งวัน"
    assert row["note"] == "ไปงานบวช"
    assert row["staff_id"] == 9
