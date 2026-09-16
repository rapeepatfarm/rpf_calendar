"""services/reports.py — สรุปสถิติย้อนหลัง

**นิยามที่ต้องตกลงให้ตรงกันทั้งระบบ** (ถ้าเปลี่ยนต้องแก้ที่นี่ที่เดียว)

ช่วงเวลาที่นับ ใช้ `planned_end_date` เป็นเกณฑ์ — ตอบคำถามว่า
"งานที่ *ควรทำให้เสร็จ* ในช่วงนี้ ทำได้แค่ไหน" ไม่ใช่ "ทำอะไรไปบ้างในช่วงนี้"
สองอย่างนี้ต่างกันเมื่อมีงานค้างข้ามเดือน และแบบแรกคือสิ่งที่หัวหน้าอยากรู้

    เสร็จตรงแผน  งานที่ปิดเสร็จภายในวันสุดท้ายของช่วงที่วางแผนไว้
    เสร็จช้า     งานที่ปิดเสร็จหลังวันสุดท้ายของแผน
    ไม่ได้ทำ     ปิดว่า missed
    ยกเลิก       ปิดว่า cancelled — **ไม่นับในตัวหาร** เพราะแผนถูกถอนโดยตั้งใจ
                 ถ้านับด้วย การยกเลิกงานจะทำให้เปอร์เซ็นต์ดูแย่ลงทั้งที่ไม่ได้ทำงานพลาด
    ยังไม่ปิด    ยังเป็นแผนหรือกำลังทำ

    % ทำตรงแผน = เสร็จตรงแผน ÷ (เสร็จตรงแผน + เสร็จช้า + ไม่ได้ทำ)
"""
from datetime import date

from database import fetchall, fetchone

# แปลงเวลาที่กดจริง (TIMESTAMPTZ) เป็นวันตามปฏิทินไทยก่อนเทียบกับวันแผน
# ถ้าเทียบดิบๆ งานที่กดจบ 6 โมงเย็นจะกลายเป็นวันถัดไปเมื่อเซิร์ฟเวอร์เป็น UTC
_DONE_ON = "(a.finished_at AT TIME ZONE 'Asia/Bangkok')::date"

# วันสุดท้ายของแผน "ตามที่วางไว้แต่แรก"
#
# ตั้งแต่ migration 008 การกดเริ่มงานจะเลื่อน planned_date/planned_end_date
# ไปตรงกับวันที่ลงมือจริง · ถ้ารายงานตัดสินจากคอลัมน์ที่ถูกเลื่อนแล้ว
# ทุกงานจะกลายเป็น "ตรงแผน" หมด เพราะแผนถูกขยับไปทับความจริงไปแล้ว
# — ตัวเลข % ทำตรงแผน จะเป็น 100% ตลอดกาลและไม่มีความหมายอีกเลย
#
# ใช้ตัวนี้ทั้งการตัดสินตรงแผน/ช้า **และการเลือกช่วงเดือน** เพื่อให้
# รายงานของเดือนที่ผ่านไปแล้วไม่ขยับเองเมื่อมีคนเพิ่งไปกดเริ่มงานเก่า
_PLAN_END = "COALESCE(a.planned_end_date_original, a.planned_end_date)"

_BUCKETS = f"""
    COUNT(*) FILTER (WHERE a.status = 'done'
                       AND {_DONE_ON} <= {_PLAN_END})          AS on_time,
    COUNT(*) FILTER (WHERE a.status = 'done'
                       AND {_DONE_ON} >  {_PLAN_END})          AS late,
    COUNT(*) FILTER (WHERE a.status = 'missed')                        AS missed,
    COUNT(*) FILTER (WHERE a.status = 'cancelled')                     AS cancelled,
    COUNT(*) FILTER (WHERE a.status IN ('planned', 'in_progress'))     AS still_open,
    COUNT(*)                                                           AS total,
    COALESCE(SUM(a.actual_minutes), 0)                                 AS minutes
"""


def _filter_sql(filters: dict) -> tuple[str, list]:
    sql, params = "", []
    if filters.get("assignee_id"):
        sql += " AND a.assignee_id = %s"
        params.append(filters["assignee_id"])
    if filters.get("category_id"):
        sql += " AND a.category_id = %s"
        params.append(filters["category_id"])
    return sql, params


def _with_rate(row: dict) -> dict:
    """เติม % ทำตรงแผน — ตัวหารไม่รวมงานที่ยกเลิกและงานที่ยังไม่ปิด"""
    row = dict(row)
    judged = row["on_time"] + row["late"] + row["missed"]
    row["judged"] = judged
    row["on_time_pct"] = round(row["on_time"] * 100 / judged, 1) if judged else None
    return row


def summary(conn, start: date, end: date, filters: dict | None = None) -> dict:
    where, params = _filter_sql(filters or {})
    row = fetchone(conn, f"""
        SELECT {_BUCKETS},
               -- ช้าเฉลี่ยกี่วัน นับเฉพาะงานที่เสร็จช้าจริงๆ
               COALESCE(AVG({_DONE_ON} - {_PLAN_END})
                        FILTER (WHERE a.status = 'done'
                                  AND {_DONE_ON} > {_PLAN_END}), 0) AS avg_late_days
          FROM activities a
         WHERE NOT a.is_deleted AND {_PLAN_END} BETWEEN %s AND %s
    """ + where, [start, end] + params)
    row = _with_rate(row)
    row["avg_late_days"] = round(float(row["avg_late_days"]), 1)
    return row


def by_person(conn, start: date, end: date, filters: dict | None = None) -> list[dict]:
    """ภาระงานรายคน — รวมคนที่ยังไม่มีงานในช่วงนี้ด้วย จะได้เห็นว่าใครว่าง"""
    where, params = _filter_sql(filters or {})
    rows = fetchall(conn, f"""
        SELECT s.id, s.name, s.position, s.color, {_BUCKETS}
          FROM staff s
          LEFT JOIN activities a
                 ON a.assignee_id = s.id AND NOT a.is_deleted
                AND {_PLAN_END} BETWEEN %s AND %s {where}
         WHERE s.active
         GROUP BY s.id, s.name, s.position, s.color, s.sort_order
         ORDER BY s.sort_order, s.name
    """, [start, end] + params)
    return [_with_rate(r) for r in rows]


def by_category(conn, start: date, end: date, filters: dict | None = None) -> list[dict]:
    where, params = _filter_sql(filters or {})
    rows = fetchall(conn, f"""
        SELECT c.id, c.name, c.color, {_BUCKETS}
          FROM activity_categories c
          JOIN activities a
                 ON a.category_id = c.id AND NOT a.is_deleted
                AND {_PLAN_END} BETWEEN %s AND %s {where}
         GROUP BY c.id, c.name, c.color, c.sort_order
         ORDER BY c.sort_order, c.name
    """, [start, end] + params)
    return [_with_rate(r) for r in rows]


def rows_in_range(conn, start: date, end: date, filters: dict | None = None,
                  limit: int | None = 500) -> list[dict]:
    """รายการกิจกรรมในช่วง พร้อมป้ายว่าตรงแผนหรือไม่ — ใช้ทั้งบนหน้าจอและตอนส่งออก"""
    where, params = _filter_sql(filters or {})
    sql = f"""
        SELECT a.id, a.title, a.status, a.priority,
               a.planned_date, a.planned_end_date,
               a.planned_start_time, a.is_all_day,
               a.started_at, a.finished_at, a.actual_minutes,
               a.result_note, a.cancel_reason,
               c.name AS category_name, c.color AS category_color,
               s.name AS assignee_name,
               {_DONE_ON} AS done_on,
               CASE
                 WHEN a.status = 'done' AND {_DONE_ON} <= {_PLAN_END} THEN 'on_time'
                 WHEN a.status = 'done' THEN 'late'
                 ELSE a.status
               END AS outcome,
               CASE WHEN a.status = 'done' AND {_DONE_ON} > {_PLAN_END}
                    THEN ({_DONE_ON} - {_PLAN_END}) ELSE 0 END AS late_days
          FROM activities a
          LEFT JOIN activity_categories c ON c.id = a.category_id
          LEFT JOIN staff s ON s.id = a.assignee_id
         WHERE NOT a.is_deleted AND {_PLAN_END} BETWEEN %s AND %s
    """ + where + " ORDER BY a.planned_date DESC, a.planned_start_time NULLS LAST, a.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return fetchall(conn, sql, [start, end] + params)


OUTCOME_LABELS = {
    "on_time": "เสร็จตรงแผน",
    "late": "เสร็จช้ากว่าแผน",
    "missed": "ไม่ได้ทำ",
    "cancelled": "ยกเลิก",
    "planned": "ยังเป็นแผน",
    "in_progress": "กำลังทำ",
}
