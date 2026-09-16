"""ตรวจตัวจำกัดการเดารหัสผ่าน — สำคัญเมื่อเปิดหน้าล็อกอินออกอินเทอร์เน็ต"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from services import loginguard  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    loginguard._fails.clear()
    yield
    loginguard._fails.clear()


def test_not_locked_at_first():
    assert loginguard.locked_for("somchai", "1.2.3.4") == 0


def test_locks_after_max_failures():
    for _ in range(loginguard.MAX_FAILS):
        loginguard.record_failure("somchai", "1.2.3.4")
    assert loginguard.locked_for("somchai", "1.2.3.4") > 0


def test_one_below_the_limit_still_allowed():
    for _ in range(loginguard.MAX_FAILS - 1):
        loginguard.record_failure("somchai", "1.2.3.4")
    assert loginguard.locked_for("somchai", "1.2.3.4") == 0


def test_success_clears_the_count():
    for _ in range(loginguard.MAX_FAILS):
        loginguard.record_failure("somchai", "1.2.3.4")
    loginguard.clear("somchai", "1.2.3.4")
    assert loginguard.locked_for("somchai", "1.2.3.4") == 0


def test_lock_is_per_ip_so_one_attacker_cannot_lock_out_staff():
    """คนร้ายยิงจากไอพีหนึ่ง ต้องไม่ทำให้พนักงานตัวจริงล็อกอินไม่ได้"""
    for _ in range(loginguard.MAX_FAILS):
        loginguard.record_failure("somchai", "9.9.9.9")
    assert loginguard.locked_for("somchai", "9.9.9.9") > 0
    assert loginguard.locked_for("somchai", "192.168.1.50") == 0


def test_username_is_matched_case_insensitively():
    for _ in range(loginguard.MAX_FAILS):
        loginguard.record_failure("SomChai", "1.2.3.4")
    assert loginguard.locked_for("somchai", "1.2.3.4") > 0


def test_old_failures_fall_out_of_the_window():
    import time
    now = time.time()
    key = loginguard._key("somchai", "1.2.3.4")
    # ความผิดพลาดเก่ากว่าหน้าต่างเวลา ต้องไม่ถูกนับ
    loginguard._fails[key] = [now - loginguard.WINDOW_SEC - 10] * loginguard.MAX_FAILS
    assert loginguard.locked_for("somchai", "1.2.3.4") == 0


def test_tracking_table_does_not_grow_without_limit():
    """ถูกยิงด้วยชื่อผู้ใช้สุ่มเป็นแสนชื่อ ต้องไม่กินหน่วยความจำไม่จำกัด"""
    for i in range(loginguard.MAX_TRACKED + 200):
        loginguard.record_failure(f"user{i}", "1.2.3.4")
    assert len(loginguard._fails) <= loginguard.MAX_TRACKED


def test_wait_message_mentions_minutes():
    assert "นาที" in loginguard.wait_message(600)
