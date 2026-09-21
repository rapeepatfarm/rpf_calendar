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


# ── หน้าที่ประจำ: ประจำจุด / ว่าง / ขาดคน (เฟส C) ──────────────

def post(id, name, required_n=None):
    return {"id": id, "name": name, "required_n": required_n, "sort_order": id}


def assign(id, post_id, staff_id, start, end=None, covers=None, name=None, active=True):
    return {"id": id, "post_id": post_id, "staff_id": staff_id,
            "starts_on": date.fromisoformat(start),
            "ends_on": date.fromisoformat(end) if end else None,
            "covers_staff_id": covers, "covers_name": f"คน{covers}" if covers else None,
            "staff_name": name or f"คน{staff_id}", "staff_color": "#000", "staff_active": active,
            "post_name": f"จุด{post_id}"}


def person(id, dept=""):
    return {"id": id, "name": f"คน{id}", "color": "#000", "department_name": dept}


HOUSE_A = post(1, "โรงเรือน A", required_n=2)
D = date(2026, 9, 20)


def test_open_ended_assignment_covers_any_later_day():
    rows = [assign(1, 1, 11, "2026-01-01")]
    r = staffing.roster_for_day([HOUSE_A], rows, [], date(2030, 1, 1))[0]
    assert [a["staff_id"] for a in r["present"]] == [11]


def test_ended_assignment_does_not_count_after_its_end():
    rows = [assign(1, 1, 11, "2026-01-01", "2026-09-19")]
    r = staffing.roster_for_day([HOUSE_A], rows, [], D)[0]
    assert r["present"] == [] and r["have"] == 0


def test_leave_makes_a_regular_worker_absent_and_the_post_short():
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01")]
    leaves = [leave(1, 11, "2026-09-20", "2026-09-21")]
    r = staffing.roster_for_day([HOUSE_A], rows, leaves, D)[0]
    assert [a["staff_id"] for a in r["absent"]] == [11]
    assert r["have"] == 1 and r["need"] == 2 and r["short"] and r["missing"] == 1


def test_a_substitute_fills_the_gap():
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01"),
            assign(3, 1, 13, "2026-09-20", "2026-09-21", covers=11)]
    leaves = [leave(1, 11, "2026-09-20", "2026-09-21")]
    r = staffing.roster_for_day([HOUSE_A], rows, leaves, D)[0]
    assert [a["staff_id"] for a in r["covering"]] == [13]
    assert r["have"] == 2 and not r["short"]


def test_a_substitute_who_is_also_on_leave_does_not_count():
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01"),
            assign(3, 1, 13, "2026-09-20", "2026-09-21", covers=11)]
    leaves = [leave(1, 11, "2026-09-20", "2026-09-21"), leave(2, 13, "2026-09-20", "2026-09-20")]
    r = staffing.roster_for_day([HOUSE_A], rows, leaves, D)[0]
    assert r["covering"] == [] and r["short"]


def test_required_n_is_a_minimum_not_the_roster_size():
    """ประจำ 3 ต้องการอย่างน้อย 2 → ลา 1 คนไม่ขาด · ลา 2 คนถึงขาด"""
    rows = [assign(i, 1, 10 + i, "2026-01-01") for i in range(1, 4)]
    one = staffing.roster_for_day([HOUSE_A], rows, [leave(1, 11, "2026-09-20", "2026-09-20")], D)[0]
    assert not one["short"] and one["have"] == 2
    two = staffing.roster_for_day([HOUSE_A], rows, [
        leave(1, 11, "2026-09-20", "2026-09-20"), leave(2, 12, "2026-09-20", "2026-09-20")], D)[0]
    assert two["short"] and two["missing"] == 1


def test_required_n_null_means_everyone_must_be_present():
    strict = post(2, "Office")
    rows = [assign(1, 2, 11, "2026-01-01"), assign(2, 2, 12, "2026-01-01")]
    r = staffing.roster_for_day([strict], rows, [leave(1, 12, "2026-09-20", "2026-09-20")], D)[0]
    assert r["need"] == 2 and r["short"]
    r2 = staffing.roster_for_day([strict], rows, [], D)[0]
    assert not r2["short"]


def test_inactive_staff_still_on_the_roster_are_ignored():
    """คนที่ถูกปิดใช้งาน (ลาออก) แต่ยังไม่มีใครไปจบผังให้ ต้องไม่ทำให้ระบบเห็นว่ามีคน"""
    rows = [assign(1, 1, 11, "2026-01-01", active=False), assign(2, 1, 12, "2026-01-01")]
    r = staffing.roster_for_day([HOUSE_A], rows, [], D)[0]
    assert r["have"] == 1 and r["short"]


def test_free_staff_excludes_both_leave_and_assigned():
    staff = [person(11), person(12), person(13), person(14)]
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 13, "2026-09-20", "2026-09-20", covers=11)]
    leaves = [leave(1, 12, "2026-09-20", "2026-09-20")]
    free = staffing.free_on(staff, rows, leaves, D)
    assert [s["id"] for s in free] == [14]


def test_shortfalls_merge_consecutive_days_into_one_range():
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01")]
    leaves = [leave(1, 11, "2026-09-20", "2026-09-22")]
    runs = staffing.shortfalls([HOUSE_A], rows, leaves, date(2026, 9, 15), date(2026, 9, 30))
    assert len(runs) == 1
    run = runs[0]
    assert (run["date_from"], run["date_to"]) == (date(2026, 9, 20), date(2026, 9, 22))
    assert run["missing"] == 1 and run["absent_names"] == ["คน11"]


def test_shortfalls_split_when_the_gap_changes_size():
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01")]
    leaves = [leave(1, 11, "2026-09-20", "2026-09-22"), leave(2, 12, "2026-09-21", "2026-09-21")]
    runs = staffing.shortfalls([HOUSE_A], rows, leaves, date(2026, 9, 19), date(2026, 9, 23))
    spans = [(r["date_from"].day, r["date_to"].day, r["missing"]) for r in runs]
    assert spans == [(20, 20, 1), (21, 21, 2), (22, 22, 1)]


def test_shortfalls_for_one_person_only_report_posts_they_belong_to():
    """ตอนบันทึกการลาของคน 11 ต้องเห็นเฉพาะจุดที่เขาประจำ ไม่ใช่ทุกจุดที่ขาดอยู่แล้ว"""
    house_b = post(2, "โรงเรือน B", required_n=1)
    rows = [assign(1, 1, 11, "2026-01-01"), assign(2, 1, 12, "2026-01-01")]   # B ไม่มีใครเลย
    leaves = [leave(1, 11, "2026-09-20", "2026-09-20")]
    runs = staffing.shortfalls([HOUSE_A, house_b], rows, leaves, D, D, staff_id=11)
    assert [r["post"]["name"] for r in runs] == ["โรงเรือน A"]
    everything = staffing.shortfalls([HOUSE_A, house_b], rows, leaves, D, D)
    assert sorted(r["post"]["name"] for r in everything) == ["โรงเรือน A", "โรงเรือน B"]


# ── ข้อมูลสำหรับแถบพนักงาน ──────────────────────────────────

def test_panel_data_sends_raw_iso_dates_for_js_and_thai_text_for_display():
    row = staffing.panel_data([leave(1, 9, "2026-09-10", "2026-09-12", note="ไปงานบวช")])[0]
    assert row["from"] == "2026-09-10" and row["to"] == "2026-09-12"
    assert row["when"] == "10 ก.ย. 69 – 12 ก.ย. 69 (3 วัน)"     # รูปแบบเดียวกับกิจกรรม
    assert row["part_label"] == "ทั้งวัน"
    assert row["note"] == "ไปงานบวช"
    assert row["staff_id"] == 9
