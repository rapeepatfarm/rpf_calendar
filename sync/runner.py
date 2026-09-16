"""sync/runner.py — ตัวรันซิงค์ที่ใช้ร่วมกันทุกแหล่ง

กติกาความปลอดภัยข้อมูลอยู่ที่นี่ที่เดียว adapter แต่ละตัวจึงแค่ "ดึงข้อมูลมา"
ไม่ต้องรู้เรื่องกฎพวกนี้ และไม่มีทางเผลอทำผิดคนละแบบ

ยังไม่มี adapter จริงต่ออยู่ — ดู sources/_example.py

กติกา (ถอดจากปัญหา sync ที่เคยเจอในระบบ RPF)
  1. ผูกด้วย external_id เท่านั้น ห้ามผูกด้วยชื่อ
  2. ต้นทางลบแล้วต้องปิดตาม — ห้ามเหลือ "งานผี" ค้างในปฏิทิน
  3. ห้ามทับข้อมูลการทำงานจริงที่คนกรอกไว้
  4. อ่านต้นทางอย่างเดียว ไม่เขียนกลับ
  5. งานที่ซิงค์มา แก้ฟิลด์แผนในปฏิทินไม่ได้ (บังคับที่ router)
  6. ทุกรอบเขียน sync_runs ว่าทำอะไรไปบ้าง
"""
import logging
from datetime import date

from database import execute, fetchall, fetchone, get_conn
from services import activities as act
from sync.base import ExternalActivity, SyncSource

log = logging.getLogger("sync")


def run(conn, source: SyncSource, config: dict, since: date, user: dict | None = None) -> dict:
    """ซิงค์ 1 แหล่ง คืนสรุปว่าสร้าง/แก้/ปิดไปกี่รายการ

    เปิดแถวใน sync_runs ก่อนเริ่มเสมอ (กติกาข้อ 6) เพื่อให้รอบที่พังกลางคัน
    ยังทิ้งร่องรอยไว้ว่าเกิดอะไรขึ้น ไม่ใช่เงียบหายไปเฉยๆ
    """
    run_row = fetchone(conn, """
        INSERT INTO sync_runs (source_id, source_code) VALUES (%s, %s) RETURNING id
    """, (config.get("source_id"), source.code))
    try:
        stats = _run_inner(conn, source, config, since, user)
    except Exception as exc:
        # ห้ามเขียนร่องรอยลง conn เดิม — มันกำลังจะถูก rollback ทั้งก้อน
        # ร่องรอยจะหายไปพร้อมกัน (แถว sync_runs ที่ INSERT ไว้ข้างบนก็หายด้วย)
        # และถ้า exc เป็น error ของฐานข้อมูล transaction จะเสียแล้ว
        # คำสั่ง UPDATE ตรงนี้จะโยน InFailedSqlTransaction ทับสาเหตุจริงจนหาไม่เจอ
        record_failure(config.get("source_id"), source.code, exc)
        raise
    execute(conn, """
        UPDATE sync_runs SET finished_at = NOW(), ok = TRUE,
               created_n = %s, updated_n = %s, cancelled_n = %s, skipped_n = %s
         WHERE id = %s
    """, (stats["created"], stats["updated"], stats["cancelled"], stats["skipped"],
          run_row["id"]))
    return stats


def _run_inner(conn, source: SyncSource, config: dict, since: date,
               user: dict | None) -> dict:
    incoming = source.fetch(config, since)
    seen = {item.external_id for item in incoming}

    existing = {
        row["external_id"]: row
        for row in fetchall(conn, """
            SELECT id, external_id, external_hash, status, started_at, finished_at,
                   result_note, planned_date, planned_end_date, date_overridden
              FROM activities
             WHERE source_system = %s AND NOT is_deleted
        """, (source.system,))
    }

    stats = {"created": 0, "updated": 0, "cancelled": 0, "skipped": 0}
    for item in incoming:
        current = existing.get(item.external_id)
        if current is None:
            _insert(conn, source, item, config, user)
            stats["created"] += 1
        elif current["external_hash"] != item.fingerprint():
            _update_plan_only(conn, current, item, user)
            stats["updated"] += 1
        else:
            stats["skipped"] += 1

    # กติกาข้อ 2 — แถวที่เคยซิงค์ไว้แต่หายไปจากต้นทางรอบนี้
    # ปิดเป็น cancelled ไม่ลบทิ้ง เพราะประวัติของงานที่เคยทำต้องอยู่ครบ
    for external_id, row in existing.items():
        if external_id in seen or row["status"] in act.CLOSED_STATUSES:
            continue
        if row["planned_date"] < since:
            continue          # อยู่นอกช่วงที่ดึงมา ไม่ใช่ว่าถูกลบ
        activity = act.get(conn, row["id"])
        act.cancel(conn, activity, user, "ถูกลบหรือยกเลิกจากต้นทาง")
        stats["cancelled"] += 1

    log.info("sync %s: %s", source.code, stats)
    return stats


def _resolve_assignee(conn, hint: str) -> int | None:
    """จับคู่ชื่อผู้รับผิดชอบจากต้นทางกับทะเบียน staff

    จับคู่ไม่ได้ก็ปล่อยว่าง ให้หัวหน้ามอบหมายเอง — เดาผิดแย่กว่าไม่เดา
    เพราะงานจะไปโผล่ในหน้า "งานของฉัน" ของคนที่ไม่เกี่ยวข้อง
    """
    if not hint.strip():
        return None
    row = fetchone(conn, "SELECT id FROM staff WHERE active AND name = %s", (hint.strip(),))
    return row["id"] if row else None


def _insert(conn, source: SyncSource, item: ExternalActivity, config: dict, user: dict | None):
    row = fetchone(conn, """
        INSERT INTO activities
            (title, category_id, description, assignee_id, priority,
             planned_date, planned_end_date, is_all_day, planned_start_time,
             duration_min, carry_over, source, source_system, external_id,
             external_hash, created_by, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'sync', %s, %s, %s, %s, %s)
        RETURNING id
    """, (item.title, config.get("category_id"), item.description,
          _resolve_assignee(conn, item.assignee_hint), item.priority,
          item.planned_date, item.final_date, item.is_all_day, item.start_time,
          item.duration_min, source.system, item.external_id, item.fingerprint(),
          user["id"] if user else None, user["id"] if user else None))

    act._log(conn, row["id"], "synced", user, to_status="planned",
             detail=f"นำเข้าจาก {source.name}")

    # ต้นทางบอกว่าทำไปแล้ว — ปิดตามให้เลย ผู้ใช้จะได้ไม่ต้องกดซ้ำ
    if item.source_status == "done":
        act.finish(conn, act.get(conn, row["id"]), user, "")


def _update_plan_only(conn, current: dict, item: ExternalActivity, user: dict | None):
    """แก้เฉพาะฟิลด์ฝั่งแผน — กติกาข้อ 3

    started_at / finished_at / result_note / status ที่คนกรอกไว้ห้ามแตะเด็ดขาด
    ไม่งั้นคนที่กดเริ่มงานไปแล้วจะโดนรอบซิงค์ถัดไปล้างของทิ้ง
    """
    # วันที่ถูกแก้จากปฏิทินแล้ว — เก็บของเดิมไว้ ไม่เอาวันจากต้นทางมาทับ
    # (ฝั่งฟาร์มจะมาดึงวันนี้กลับไปใช้เอง ผ่าน services/calendar_pull.py)
    keep_dates = current["date_overridden"]
    start = current["planned_date"] if keep_dates else item.planned_date
    end = current["planned_end_date"] if keep_dates else item.final_date

    execute(conn, """
        UPDATE activities SET title = %s, description = %s, priority = %s,
               planned_date = %s, planned_end_date = %s, is_all_day = %s,
               planned_start_time = %s, duration_min = %s,
               external_hash = %s, updated_at = NOW()
         WHERE id = %s
    """, (item.title, item.description, item.priority, start, end,
          item.is_all_day, item.start_time, item.duration_min,
          item.fingerprint(), current["id"]))

    if keep_dates:
        # อัปเดต hash ด้วยเพื่อไม่ให้รอบถัดไปมองว่า "ต้นทางเปลี่ยน" ซ้ำๆ ทุกรอบ
        # แล้วเขียน log รกโดยไม่มีอะไรเปลี่ยนจริง
        detail = (f"ต้นทางแก้ข้อมูล แต่คงวันที่แก้จากปฏิทินไว้ "
                  f"({current['planned_date']})")
    elif current["planned_date"] != item.planned_date:
        detail = f"ต้นทางเลื่อนวัน: {current['planned_date']} → {item.planned_date}"
    else:
        detail = "ต้นทางแก้ข้อมูลแผน"
    act._log(conn, current["id"], "synced", user, detail=detail)


def record_failure(source_id: int | None, source_code: str, exc: Exception) -> None:
    """บันทึกว่ารอบซิงค์ล้มเหลว **บน connection แยกที่ commit ของตัวเอง**

    ต้องแยก connection เพราะรอบที่พังจะถูก rollback ทั้ง transaction
    ถ้าเขียนร่องรอยลงไปในนั้นก็หายไปด้วยกัน — ซึ่งเคยทำให้ผู้ใช้กดดึงข้อมูล
    ไม่สำเร็จหลายรอบโดยไม่มีอะไรบันทึกไว้เลยว่าพังเพราะอะไร
    (รู้ได้ทีหลังจากเลข sequence ที่ถูกใช้ไปแล้วเท่านั้น)

    ตัวมันเองห้ามโยน exception ต่อ ไม่งั้นจะกลบสาเหตุจริงที่กำลังจะถูก raise
    """
    try:
        with get_conn() as conn:
            execute(conn, """
                INSERT INTO sync_runs (source_id, source_code, finished_at, ok, error)
                VALUES (%s, %s, NOW(), FALSE, %s)
            """, (source_id, source_code, str(exc)[:500]))
            if source_id is not None:
                execute(conn, """
                    UPDATE sync_sources SET last_run_at = NOW(), last_status = %s
                     WHERE id = %s
                """, (f"ผิดพลาด: {str(exc)[:120]}", source_id))
    except Exception:
        pass
