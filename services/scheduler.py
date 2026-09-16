"""services/scheduler.py — งานเบื้องหลังรายวัน

ทำสองอย่าง
  1. สร้างกิจกรรมของแผนงานประจำล่วงหน้าตามระยะที่ตั้งไว้ (ค่าเริ่มต้น 12 เดือน)
  2. ปิดงานค้างที่เกิน auto_skip_after_days เป็น "ไม่ได้ทำ"

รูปแบบเดียวกับ poller ของ rpf_power คือเริ่มพร้อม lifespan ของแอป
รันครั้งแรกตอนโปรแกรมขึ้น แล้วรันซ้ำทุกวันตอนตี 0:05

ทุกอย่างในนี้ต้อง **รันซ้ำได้โดยไม่เกิดของซ้ำ** เพราะโปรแกรมอาจถูกรีสตาร์ทหลายรอบต่อวัน
กันของซ้ำด้วย unique constraint (series_id, planned_date) ไม่ใช่ด้วยการตรวจก่อน insert
"""
import asyncio
import logging
from datetime import date, datetime, time, timedelta

from config import PLAN_HORIZON_MONTHS, THAI_TZ
from database import execute, fetchall, fetchone, get_conn
from services import recurrence, thaidate

log = logging.getLogger("scheduler")

RUN_AT = time(0, 5)


def horizon(conn) -> date:
    """วางแผนล่วงหน้าถึงวันไหน — ค่าใน settings ทับค่าใน .env ได้"""
    row = fetchone(conn, "SELECT value FROM settings WHERE key = 'plan_horizon_months'")
    months = PLAN_HORIZON_MONTHS
    if row:
        try:
            months = max(1, min(60, int(row["value"])))
        except ValueError:
            pass
    return thaidate.add_months(thaidate.today(), months)


def _series_helpers(conn, series_id: int) -> list[int]:
    return [r["staff_id"] for r in fetchall(
        conn, "SELECT staff_id FROM series_helpers WHERE series_id = %s", (series_id,))]


def _insert_occurrence(conn, series: dict, start: date, helper_ids: list[int]) -> bool:
    """สร้างกิจกรรม 1 รอบ · คืน False ถ้ารอบวันนั้นมีอยู่แล้ว"""
    end = start + timedelta(days=max(1, series["duration_days"]) - 1)
    row = fetchone(conn, """
        INSERT INTO activities
            (series_id, title, category_id, description, assignee_id, priority,
             planned_date, planned_end_date, is_all_day, planned_start_time,
             planned_end_time, duration_min, carry_over, needs_start,
             auto_skip_after_days,
             source, created_by, updated_by)
        VALUES (%(series_id)s, %(title)s, %(category_id)s, %(description)s,
                %(assignee_id)s, %(priority)s, %(start)s, %(end)s, %(is_all_day)s,
                %(start_time)s, NULL, %(duration_min)s, %(carry_over)s,
                COALESCE((SELECT needs_start FROM activity_categories
                           WHERE id = %(category_id)s), TRUE),
                %(auto_skip)s, 'series', %(created_by)s, %(created_by)s)
        -- ต้องเขียน WHERE ซ้ำให้ตรงกับ index เพราะ activities_series_date_uq
        -- เป็น partial unique index — ถ้าไม่ใส่ PostgreSQL จะหา arbiter ไม่เจอ
        ON CONFLICT (series_id, planned_date) WHERE series_id IS NOT NULL DO NOTHING
        RETURNING id
    """, {
        "series_id": series["id"], "title": series["title"],
        "category_id": series["category_id"], "description": series["description"],
        "assignee_id": series["assignee_id"], "priority": series["priority"],
        "start": start, "end": end, "is_all_day": series["is_all_day"],
        "start_time": series["start_time"], "duration_min": series["duration_min"],
        "carry_over": series["carry_over"],
        "auto_skip": series["auto_skip_after_days"],
        "created_by": series["created_by"],
    })
    if row is None:
        return False
    for staff_id in helper_ids:
        execute(conn, """
            INSERT INTO activity_helpers (activity_id, staff_id) VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (row["id"], staff_id))
    return True


def ensure_next_occurrence(conn, series: dict, anchor: date | None = None) -> date | None:
    """โหมด after_done — ทำให้มีกิจกรรมที่ยังไม่ปิดค้างไว้ 1 รอบเสมอ

    สร้างล่วงหน้าได้แค่รอบเดียว เพราะวันของรอบถัดๆ ไปขึ้นกับว่ารอบนี้จะเสร็จเมื่อไร
    ซึ่งยังไม่รู้ · ต่างจากโหมด fixed ที่คำนวณล่วงหน้า 12 เดือนได้เลย

    anchor = วันที่ใช้เป็นจุดตั้งต้นนับรอบถัดไป (วันที่ทำเสร็จจริง)
             ถ้าไม่ส่งมา จะหาจากรอบล่าสุดที่ปิดไปแล้ว
    """
    if not series["active"]:
        return None

    # ยังมีรอบที่ยังไม่ปิดค้างอยู่ ไม่ต้องสร้างเพิ่ม
    open_row = fetchone(conn, """
        SELECT id FROM activities
         WHERE series_id = %s AND NOT is_deleted
           AND status IN ('planned', 'in_progress') LIMIT 1
    """, (series["id"],))
    if open_row:
        return None

    stats = fetchone(conn, """
        SELECT COUNT(*) AS made,
               MAX(COALESCE((finished_at AT TIME ZONE 'Asia/Bangkok')::date,
                            planned_end_date)) AS last_anchor
          FROM activities WHERE series_id = %s AND NOT is_deleted
    """, (series["id"],))

    if stats["made"] == 0:
        # ยังไม่เคยสร้างรอบไหนเลย — รอบแรกใช้วันเริ่มแผนตามที่ตั้งไว้
        nxt = series["starts_on"]
        if series.get("ends_on") and nxt > series["ends_on"]:
            return None
    else:
        base = anchor or stats["last_anchor"]
        if base is None:
            return None
        nxt = recurrence.next_after(series, base, made_count=stats["made"])
        if nxt is None:
            return None

    if _insert_occurrence(conn, series, nxt, _series_helpers(conn, series["id"])):
        log.info("แผน %s: สร้างรอบถัดไป %s (นับจาก %s)", series["id"], nxt, anchor or "-")
        return nxt
    return None


def generate_series(conn, series: dict, until: date) -> int:
    """สร้างกิจกรรมของแผนงานหนึ่งจนถึงวัน until · คืนจำนวนที่สร้างใหม่"""
    # โหมด after_done วางล่วงหน้าไม่ได้ เพราะวันขึ้นกับตอนที่ทำเสร็จจริง
    if series.get("anchor_mode") == recurrence.ANCHOR_AFTER_DONE:
        return 1 if ensure_next_occurrence(conn, series) else 0

    # เริ่มคำนวณจากวันที่สร้างค้างไว้ล่าสุด ไม่ต้องไล่ใหม่ทั้งชุดทุกรอบ
    since = series["generated_until"] or series["starts_on"]
    dates = recurrence.occurrences(series, until, since=since)

    helper_ids = _series_helpers(conn, series["id"])
    created = sum(1 for start in dates
                  if _insert_occurrence(conn, series, start, helper_ids))

    execute(conn, "UPDATE activity_series SET generated_until = %s WHERE id = %s",
            (until, series["id"]))
    return created


def generate_all(conn) -> int:
    until = horizon(conn)
    total = 0
    for series in fetchall(conn, "SELECT * FROM activity_series WHERE active ORDER BY id"):
        total += generate_series(conn, series, until)
    return total


def close_stale(conn) -> int:
    """ปิดงานค้างที่เกินกำหนดเป็น 'ไม่ได้ทำ'

    นับจาก planned_date (วันที่ต้องเริ่ม) ให้ตรงกับ days_late ใน activities._SELECT
    "วันค้าง" ต้องหมายถึงสิ่งเดียวกันทั้งระบบ ไม่งั้นป้ายบนหน้าจอบอกค้าง 9 วัน
    แต่ตัวปิดอัตโนมัติที่ตั้งไว้ 7 วันยังไม่ทำงาน แล้วไม่มีใครเข้าใจว่าทำไม
    """
    rows = fetchall(conn, """
        SELECT id, series_id, planned_date, planned_end_date, auto_skip_after_days,
               (CURRENT_DATE - planned_date) AS days_late
          FROM activities
         WHERE NOT is_deleted AND status = 'planned'
           AND needs_start
           AND auto_skip_after_days IS NOT NULL
           AND planned_date < CURRENT_DATE
           AND (CURRENT_DATE - planned_date) > auto_skip_after_days
    """)
    for row in rows:
        execute(conn, """
            UPDATE activities SET status = 'missed', updated_at = NOW()
             WHERE id = %s AND status = 'planned'
        """, (row["id"],))
        execute(conn, """
            INSERT INTO activity_log (activity_id, action, from_status, to_status, detail)
            VALUES (%s, 'missed', 'planned', 'missed', %s)
        """, (row["id"], f"ระบบปิดอัตโนมัติ — ค้างเกิน {row['auto_skip_after_days']} วัน"))

        # แผนแบบ after_done ต้องได้รอบถัดไปด้วย ไม่งั้นสายของแผนขาดตรงนี้
        # แล้วจะไม่มีงานรอบใหม่โผล่มาอีกเลย โดยไม่มีอะไรเตือน
        if row["series_id"]:
            series = fetchone(conn, "SELECT * FROM activity_series WHERE id = %s",
                              (row["series_id"],))
            if series and series.get("anchor_mode") == recurrence.ANCHOR_AFTER_DONE:
                ensure_next_occurrence(conn, series, anchor=row["planned_end_date"])
    return len(rows)


def run_once() -> dict:
    with get_conn() as conn:
        created = generate_all(conn)
        closed = close_stale(conn)
    result = {"created": created, "closed": closed}
    if created or closed:
        log.info("รอบประจำวัน: %s", result)
    return result


def _seconds_until_next_run() -> float:
    now = datetime.now(THAI_TZ)
    target = datetime.combine(now.date(), RUN_AT, tzinfo=THAI_TZ)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class Scheduler:
    """ตัวรันเบื้องหลัง — เริ่ม/หยุดพร้อม lifespan ของแอป"""

    def __init__(self):
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        while True:
            try:
                # to_thread เพราะ psycopg2 เป็น blocking — ถ้ารันตรงๆ จะค้างทั้งเว็บ
                # ระหว่างสร้างงานล่วงหน้าเป็นพันแถว
                await asyncio.to_thread(run_once)
            except Exception:
                # งานเบื้องหลังพังต้องไม่ทำให้เว็บล่ม รอบหน้าค่อยลองใหม่
                log.exception("รอบประจำวันล้มเหลว")
            await asyncio.sleep(_seconds_until_next_run())


scheduler = Scheduler()
