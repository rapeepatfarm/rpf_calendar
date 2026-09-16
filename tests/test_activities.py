"""ตรวจตรรกะที่พังแล้วจะรู้ตัวยาก — งานค้าง วงจรสถานะ และการเติมเวลา

เทสต์ชุดนี้ไม่แตะฐานข้อมูล ใช้ตรวจตรรกะล้วนๆ ให้รันเร็วและรันที่ไหนก็ได้
ส่วนที่ต้องมี DB จะเพิ่มตอนทำเฟส 3 (ตัวสร้างงานประจำ)
"""
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import thaidate  # noqa: E402
from services.activities import _end_time  # noqa: E402


# ── การเติมเวลา ──────────────────────────────────────────────

def _fill(start=None, end=None, minutes=None) -> dict:
    data = {"planned_start_time": start, "planned_end_time": end, "duration_min": minutes}
    _end_time(data)
    return data


def test_duration_fills_end_time():
    assert _fill(start=time(8, 0), minutes=150)["planned_end_time"] == time(10, 30)


def test_end_time_fills_duration():
    assert _fill(start=time(8, 0), end=time(10, 30))["duration_min"] == 150


def test_overnight_job_does_not_wrap_to_earlier_time():
    """งานที่ล้นข้ามเที่ยงคืนต้องไม่ได้เวลาจบที่ย้อนกลับไปก่อนเวลาเริ่ม"""
    assert _fill(start=time(23, 0), minutes=120)["planned_end_time"] is None


def test_existing_values_are_not_overwritten():
    filled = _fill(start=time(8, 0), end=time(9, 0), minutes=999)
    assert filled["planned_end_time"] == time(9, 0)
    assert filled["duration_min"] == 999


# ── วันที่ไทย ────────────────────────────────────────────────

def test_buddhist_year_in_short_date():
    assert thaidate.short(date(2026, 8, 22)) == "22 ส.ค. 69"


def test_long_date_starts_with_weekday():
    assert thaidate.long(date(2026, 8, 22)) == "เสาร์ที่ 22 สิงหาคม 2569"


def test_add_months_clamps_to_end_of_short_month():
    """31 ม.ค. + 1 เดือน ต้องได้ 28/29 ก.พ. ไม่ใช่ 3 มี.ค.

    ตัวสร้างงานประจำรายเดือนในเฟส 3 จะพึ่งกติกานี้
    """
    assert thaidate.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert thaidate.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)   # ปีอธิกสุรทิน
    assert thaidate.add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)


def test_add_months_crosses_year_boundary():
    assert thaidate.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert thaidate.add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)


def test_duration_text():
    assert thaidate.duration(45) == "45 นาที"
    assert thaidate.duration(90) == "1 ชม. 30 น."
    assert thaidate.duration(120) == "2 ชม."


def test_relative_day_labels():
    today = thaidate.today()
    assert thaidate.relative_day(today) == "วันนี้"
    assert thaidate.relative_day(today + timedelta(days=1)) == "พรุ่งนี้"
    assert thaidate.relative_day(today - timedelta(days=1)) == "เมื่อวาน"


# ── สิทธิ์ ───────────────────────────────────────────────────

def test_unlinked_user_does_not_own_unassigned_work():
    """ผู้ใช้ที่ยังไม่ผูกทะเบียนพนักงาน ต้องไม่กลายเป็นเจ้าของงานที่ยังไม่มอบหมาย

    ถ้าเทียบ None == None ตรงๆ ทุกคนจะกดเริ่มงานที่ยังไม่ระบุผู้รับผิดชอบได้หมด
    """
    from auth import owns_activity
    user = {"id": 1, "role": "worker", "staff_id": None}
    assert owns_activity(user, {"assignee_id": None}) is False


def test_worker_owns_only_their_own_work():
    from auth import can_run_activity, owns_activity
    worker = {"id": 2, "role": "worker", "staff_id": 5}
    assert owns_activity(worker, {"assignee_id": 5}) is True
    assert owns_activity(worker, {"assignee_id": 6}) is False
    assert can_run_activity(worker, {"assignee_id": 6}) is False
    assert can_run_activity({"id": 1, "role": "manager"}, {"assignee_id": 6}) is True


def test_worker_cannot_edit_work_already_started():
    """พองานเริ่มแล้ว การแก้แผนย้อนหลังจะทำให้รายงาน 'ทำตรงแผน' เชื่อถือไม่ได้"""
    from auth import can_edit_activity
    worker = {"id": 2, "role": "worker", "staff_id": 5}
    own_planned = {"created_by": 2, "status": "planned", "assignee_id": 5}
    own_started = {"created_by": 2, "status": "in_progress", "assignee_id": 5}
    assert can_edit_activity(worker, own_planned) is True
    assert can_edit_activity(worker, own_started) is False


def test_viewer_can_do_nothing():
    from auth import can_create, can_edit_activity, can_manage, can_run_activity
    viewer = {"id": 3, "role": "viewer", "staff_id": 7}
    assert can_create(viewer) is False
    assert can_manage(viewer) is False
    assert can_run_activity(viewer, {"assignee_id": 7}) is False
    assert can_edit_activity(viewer, {"created_by": 3, "status": "planned"}) is False
