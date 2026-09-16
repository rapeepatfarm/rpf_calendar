"""services/activities.py — ตรรกะกิจกรรมทั้งหมด และที่เดียวที่เขียน activity_log

กติกาสำคัญของไฟล์นี้
  • router ห้าม UPDATE activities เองตรงๆ ต้องเรียกผ่านฟังก์ชันในไฟล์นี้เท่านั้น
    ไม่งั้นจะมีเส้นทางที่เปลี่ยนสถานะแล้วประวัติไม่ถูกบันทึก
  • ห้ามแก้ planned_date อัตโนมัติ — งานค้างใช้วิธี "คำนวณให้โผล่ในวันนี้"
    การเลื่อนวันจริงต้องมาจากคนกด (reschedule) และบันทึกลง log เสมอ
"""
from datetime import date, timedelta

from database import execute, fetchall, fetchone
from services import recurrence, thaidate

STATUS_LABELS = {
    "planned": "ยังเป็นแผน",
    "in_progress": "กำลังทำ",
    "done": "เสร็จแล้ว",
    "cancelled": "ยกเลิก",
    "missed": "ไม่ได้ทำ",
}
# งานที่ปิดจบแล้ว — ไม่ต้องตามไปเตือนอีก
CLOSED_STATUSES = ("done", "cancelled", "missed")

PRIORITY_LABELS = {1: "ด่วนมาก", 2: "สูง", 3: "ปกติ", 4: "ต่ำ"}
PRIORITY_COLORS = {1: "#e5484d", 2: "#e08c00", 3: "#2f7de1", 4: "#8b96a8"}

# วันนี้อยู่ตรงไหนของช่วงที่วางแผนไว้ — ใช้เลือกข้อความตอนถามยืนยันก่อนเริ่มงาน
START_EARLY = "early"      # ยังไม่ถึงวันเริ่ม
START_ONTIME = "ontime"    # อยู่ในช่วงที่ต้องทำพอดี
START_LATE = "late"        # เลยช่วงมาแล้ว

ACTION_LABELS = {
    "created": "สร้างกิจกรรม",
    "edited": "แก้ไขข้อมูล",
    "started": "กดเริ่มงาน",
    "finished": "กดสิ้นสุดงาน",
    "reopened": "เปิดงานใหม่",
    "cancelled": "ยกเลิกงาน",
    "rescheduled": "เลื่อนวัน",
    "missed": "ปิดว่าไม่ได้ทำ",
    "unstarted": "ยกเลิกการเริ่มงาน",
    "noted": "บันทึกผลงาน",
    "synced": "ซิงค์จากต้นทาง",
    "deleted": "ลบกิจกรรม",
}

# ฟิลด์ที่ทุกหน้าจอต้องใช้เหมือนกัน — รวมไว้ที่เดียวกันลืมและกัน query เพี้ยนกันคนละหน้า
# days_late คำนวณสดจาก planned_date เสมอ ไม่เก็บลงตาราง จะได้ไม่มีวันค้างกับความจริง
_SELECT = """
    SELECT a.*,
           c.name  AS category_name,
           c.color AS category_color,
           c.icon  AS category_icon,
           s.name  AS assignee_name,
           s.color AS assignee_color,
           -- นับจาก planned_date (วันที่ "ต้องเริ่ม") ตามที่ผู้ใช้กำหนด
           -- ตัวเลขนี้ตอบว่า "ควรลงมือไปแล้วกี่วันแต่ยังไม่ได้เริ่ม"
           -- งานหลายวันจึงขึ้นว่าค้างตั้งแต่วันที่สองของช่วง ซึ่งถูกต้องแล้ว
           -- เพราะถ้าเลยวันเริ่มมาแล้วยังไม่กด แปลว่าช้าไปจากแผนจริงๆ
           -- งานที่ไม่ต้องกดเริ่ม (แจ้งให้ทราบ/ลาหยุด) ไม่มีวันเป็นงานค้าง
           -- เพราะจะไม่มีใครมากดเริ่มอยู่แล้ว ถ้านับด้วยมันจะกองสะสมตลอดไป
           CASE WHEN a.status = 'planned' AND a.needs_start
                     AND a.planned_date < CURRENT_DATE
                THEN (CURRENT_DATE - a.planned_date) ELSE 0 END AS days_late,
           (a.planned_end_date - a.planned_date + 1) AS span_days
      FROM activities a
      LEFT JOIN activity_categories c ON c.id = a.category_id
      LEFT JOIN staff s ON s.id = a.assignee_id
     WHERE NOT a.is_deleted
"""

# เรียงงานในรายการ: ด่วนก่อน แล้วตามเวลาที่นัดไว้ (งานทั้งวันไปท้ายกลุ่ม)
_ORDER = " ORDER BY a.priority, a.planned_start_time NULLS LAST, a.id"


# ── การอ่าน ──────────────────────────────────────────────────

def get(conn, activity_id: int) -> dict | None:
    return fetchone(conn, _SELECT + " AND a.id = %s", (activity_id,))


def _filter_sql(filters: dict) -> tuple[str, list]:
    """แปลงตัวกรองจากหน้าจอเป็นเงื่อนไข SQL — ใช้ร่วมกันทุกมุมมอง"""
    sql, params = "", []
    if filters.get("assignee_id"):
        # นับงานที่เป็นผู้ช่วยด้วย ไม่งั้นคนที่ถูกใส่เป็นผู้ช่วยจะไม่เห็นงานตัวเอง
        # ในตัวกรอง "งานของฉัน" ทั้งที่ต้องไปทำ
        sql += (" AND (a.assignee_id = %s OR EXISTS (SELECT 1 FROM activity_helpers h"
                " WHERE h.activity_id = a.id AND h.staff_id = %s))")
        params.extend([filters["assignee_id"], filters["assignee_id"]])
    if filters.get("category_id"):
        sql += " AND a.category_id = %s"
        params.append(filters["category_id"])
    if filters.get("status"):
        sql += " AND a.status = %s"
        params.append(filters["status"])
    return sql, params


def list_between(conn, start: date, end: date, filters: dict | None = None) -> list[dict]:
    """งานที่ "คาบเกี่ยว" ช่วงวันที่ — ใช้ในปฏิทิน ดึงเฉพาะช่วงที่แสดง

    ต้องเป็นการคาบเกี่ยว ไม่ใช่ BETWEEN ธรรมดา เพราะงานหลายวันที่เริ่มก่อนต้นช่วง
    แต่ยังไม่จบ ต้องโผล่ในปฏิทินเดือนนี้ด้วย
    """
    where, params = _filter_sql(filters or {})
    return fetchall(conn,
                    _SELECT + " AND a.planned_date <= %s AND a.planned_end_date >= %s" + where +
                    " ORDER BY a.planned_date, a.planned_end_date DESC,"
                    " a.priority, a.planned_start_time NULLS LAST",
                    [end, start] + params)


def today_groups(conn, filters: dict | None = None) -> dict[str, list[dict]]:
    """งานของวันนี้ 3 กลุ่ม ตามที่ออกแบบไว้ในแผน (ข้อ 4.2)

    งานค้างไม่ได้ถูกย้ายวัน แต่ถูกดึงขึ้นมาแสดงร่วมกับงานวันนี้
    planned_date ในฐานข้อมูลยังเป็นวันเดิม ประวัติจึงไม่เพี้ยน
    """
    where, params = _filter_sql(filters or {})
    today = thaidate.today()

    overdue = fetchall(conn, _SELECT + """
          AND a.status = 'planned'
          AND a.needs_start
          AND a.planned_date < %s
          AND a.carry_over
    """ + where + " ORDER BY a.planned_date, a.priority, a.planned_start_time NULLS LAST",
                       [today] + params)

    # งานที่เริ่มเมื่อวานแล้วยังไม่กดจบต้องเห็นวันนี้ด้วย ไม่งั้นจะไม่มีใครไปกดปิด
    running = fetchall(conn, _SELECT + " AND a.status = 'in_progress'" + where +
                       " ORDER BY a.started_at", params)

    # งานหลายวันต้องอยู่ในรายการทุกวันที่อยู่ในช่วง ไม่ใช่เฉพาะวันแรก
    #
    # ต้องตัดตัวที่ไปโผล่ในกลุ่มงานค้างแล้วออก ไม่งั้นงานหลายวันที่เลยวันเริ่มมา
    # จะขึ้นสองที่พร้อมกัน (ค้างเพราะ planned_date < วันนี้ และอยู่ในช่วงของวันนี้ด้วย)
    # เงื่อนไขต้องตรงกับกลุ่ม overdue ข้างบนเป๊ะ รวมถึง carry_over
    # — งานที่ไม่ตามมา (carry_over = FALSE) ไม่ได้อยู่ในกลุ่มค้าง จึงต้องยังเห็นที่นี่
    #   จนกว่าจะหมดช่วง ไม่งั้นมันจะหายไปเฉยๆ ตั้งแต่วันที่สอง
    planned = fetchall(conn, _SELECT + """
          AND a.planned_date <= %s AND a.planned_end_date >= %s
          AND a.status <> 'in_progress'
          AND NOT (a.status = 'planned' AND a.needs_start
                   AND a.planned_date < %s AND a.carry_over)
    """ + where + _ORDER, [today, today, today] + params)

    return {"overdue": overdue, "running": running, "planned": planned}


def upcoming(conn, days: int = 14, filters: dict | None = None) -> list[dict]:
    """งานที่จะถึงในอีก N วัน (ไม่รวมวันนี้ — วันนี้อยู่ในหน้างานวันนี้แล้ว)"""
    where, params = _filter_sql(filters or {})
    today = thaidate.today()
    return fetchall(conn, _SELECT + """
          AND a.planned_date > %s
          AND a.planned_date <= %s
          AND a.status = 'planned'
    """ + where + " ORDER BY a.planned_date, a.priority, a.planned_start_time NULLS LAST",
                    [today, today + timedelta(days=days)] + params)


def month_activities(conn, start: date, end: date, filters: dict | None = None) -> list[dict]:
    """ข้อมูลที่หน้าปฏิทินส่งให้ฝั่งเบราว์เซอร์ใช้ทำแผงรายละเอียด

    ส่งไปทั้งชุดครั้งเดียวตอนโหลดหน้า แล้วให้ Alpine เลือกแสดงเอง
    การกดวันหรือกดกิจกรรมจึงตอบสนองทันทีโดยไม่ต้องยิงกลับมาที่เซิร์ฟเวอร์
    """
    return list_between(conn, start, end, filters)


def log_entries(conn, activity_id: int) -> list[dict]:
    return fetchall(conn, """
        SELECT l.*, u.display_name, u.username
          FROM activity_log l
          LEFT JOIN users u ON u.id = l.by_user_id
         WHERE l.activity_id = %s
         ORDER BY l.at, l.id
    """, (activity_id,))


def day_counts(conn, start: date, end: date, filters: dict | None = None) -> dict:
    """จำนวนงานต่อวัน แยกตามสถานะ — ใช้ทำจุดสรุปในช่องปฏิทินรายเดือน"""
    where, params = _filter_sql(filters or {})
    rows = fetchall(conn, """
        SELECT a.planned_date, a.status, COUNT(*) AS n
          FROM activities a
         WHERE NOT a.is_deleted AND a.planned_date BETWEEN %s AND %s
    """ + where + " GROUP BY a.planned_date, a.status", [start, end] + params)
    out: dict = {}
    for row in rows:
        out.setdefault(row["planned_date"], {})[row["status"]] = row["n"]
    return out


# ── ผู้ช่วย ──────────────────────────────────────────────────
# assignee_id ยังเป็นผู้รับผิดชอบหลัก · ผู้ช่วยคือคนที่มาลงมือทำด้วย
# จึงกดเริ่ม/สิ้นสุดได้ และเห็นงานนี้ใน "งานของฉัน"

def attach_helpers(conn, rows: list[dict]) -> list[dict]:
    """เติมรายชื่อผู้ช่วยให้กิจกรรมหลายรายการด้วย query เดียว

    ถ้าดึงทีละแถวในลูป หน้าปฏิทินที่มี 40 กิจกรรมจะยิง 40 query
    """
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    grouped: dict[int, list[dict]] = {}
    for row in fetchall(conn, """
        SELECT h.activity_id, s.id, s.name, s.color
          FROM activity_helpers h JOIN staff s ON s.id = h.staff_id
         WHERE h.activity_id = ANY(%s)
         ORDER BY s.sort_order, s.name
    """, (ids,)):
        grouped.setdefault(row["activity_id"], []).append(row)

    for row in rows:
        helpers = grouped.get(row["id"], [])
        row["helpers"] = helpers
        row["helper_ids"] = [h["id"] for h in helpers]
        row["helper_names"] = [h["name"] for h in helpers]
    return rows


def set_helpers(conn, activity_id: int, staff_ids: list[int]):
    """แทนที่รายชื่อผู้ช่วยทั้งชุด — ผู้รับผิดชอบหลักไม่ต้องอยู่ในนี้ซ้ำ"""
    execute(conn, "DELETE FROM activity_helpers WHERE activity_id = %s", (activity_id,))
    for staff_id in dict.fromkeys(staff_ids):          # กันซ้ำ รักษาลำดับ
        if staff_id:
            execute(conn, """
                INSERT INTO activity_helpers (activity_id, staff_id) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (activity_id, staff_id))


# ── การเขียน ─────────────────────────────────────────────────

def _log(conn, activity_id: int, action: str, user: dict | None,
         from_status: str | None = None, to_status: str | None = None,
         detail: str = ""):
    execute(conn, """
        INSERT INTO activity_log (activity_id, action, from_status, to_status, detail, by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (activity_id, action, from_status, to_status, detail,
          user["id"] if user else None))


def _advance_series(conn, activity: dict, anchor: date):
    """แผนงานประจำโหมด "นับจากวันที่ทำเสร็จจริง" — สร้างรอบถัดไปทันทีที่ปิดงานรอบนี้

    เรียกหลังปิดงานทุกแบบ (เสร็จ / ยกเลิก / ไม่ได้ทำ) ไม่งั้นสายของแผนจะขาด
    ถ้ารอบหนึ่งถูกยกเลิกแล้วไม่มีใครสร้างรอบต่อ

    import ในฟังก์ชันเพราะ scheduler เป็นชั้นที่อยู่เหนือกว่า — วางไว้บนหัวไฟล์
    จะกลายเป็น import วนกันเมื่อ scheduler ต้องใช้ตรรกะจากไฟล์นี้ในอนาคต
    """
    if not activity.get("series_id"):
        return
    from services import recurrence, scheduler

    series = fetchone(conn, "SELECT * FROM activity_series WHERE id = %s",
                      (activity["series_id"],))
    if series and series.get("anchor_mode") == recurrence.ANCHOR_AFTER_DONE:
        scheduler.ensure_next_occurrence(conn, series, anchor=anchor)


def _end_time(data: dict) -> None:
    """เติมเวลาสิ้นสุดจากเวลาเริ่ม + ระยะเวลา ถ้าผู้ใช้กรอกมาอย่างใดอย่างหนึ่ง

    ผู้ใช้บางคนกรอก "เริ่ม 8 โมง ใช้เวลา 2 ชม." บางคนกรอก "8 โมง ถึง 10 โมง"
    เก็บทั้งสองแบบให้ครบเพื่อให้ปฏิทินและรายงานใช้ได้เหมือนกัน
    """
    start, end, minutes = data["planned_start_time"], data["planned_end_time"], data["duration_min"]
    if start and minutes and not end:
        total = start.hour * 60 + start.minute + minutes
        if total < 24 * 60:                       # งานข้ามเที่ยงคืนไม่เติมให้ เดี๋ยวเวลาย้อนกลับ
            data["planned_end_time"] = start.replace(hour=total // 60, minute=total % 60)
    elif start and end and not minutes:
        diff = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        if diff > 0:
            data["duration_min"] = diff


def _normalise_dates(data: dict) -> None:
    """วันสิ้นสุดต้องไม่มาก่อนวันเริ่ม และงานวันเดียวเก็บสองค่าเท่ากัน

    ทำที่นี่ที่เดียวแทนที่จะพึ่ง CHECK constraint อย่างเดียว เพราะผู้ใช้กรอกวันสลับกัน
    ได้ง่ายมาก และการเด้ง error ฐานข้อมูลใส่หน้าเขาไม่ช่วยอะไร
    """
    end = data.get("planned_end_date")
    if end is None or end < data["planned_date"]:
        data["planned_end_date"] = data["planned_date"]


def _span_text(data: dict) -> str:
    start, end = data["planned_date"], data["planned_end_date"]
    if start == end:
        return f"วางแผนไว้วันที่ {thaidate.short(start)}"
    days = (end - start).days + 1
    return f"วางแผนไว้ {thaidate.short(start)} – {thaidate.short(end)} ({days} วัน)"


def create(conn, data: dict, user: dict) -> int:
    _normalise_dates(data)
    _end_time(data)
    row = fetchone(conn, """
        INSERT INTO activities
            (title, category_id, description, assignee_id, priority,
             planned_date, planned_end_date, is_all_day, planned_start_time,
             planned_end_time, duration_min,
             carry_over, needs_start, auto_skip_after_days, source,
             created_by, updated_by)
        VALUES (%(title)s, %(category_id)s, %(description)s, %(assignee_id)s, %(priority)s,
                %(planned_date)s, %(planned_end_date)s, %(is_all_day)s,
                %(planned_start_time)s, %(planned_end_time)s, %(duration_min)s,
                %(carry_over)s, %(needs_start)s, %(auto_skip_after_days)s,
                'manual', %(user_id)s, %(user_id)s)
        RETURNING id
    """, {**data, "user_id": user["id"]})
    _log(conn, row["id"], "created", user, to_status="planned", detail=_span_text(data))
    return row["id"]


def update(conn, activity: dict, data: dict, user: dict):
    """แก้ไขข้อมูลแผน — บันทึกลง log ว่าอะไรเปลี่ยนไปบ้าง"""
    _normalise_dates(data)
    _end_time(data)
    changes = []
    if data["title"] != activity["title"]:
        changes.append(f"ชื่องาน: {activity['title']} → {data['title']}")
    if data["planned_date"] != activity["planned_date"]:
        changes.append(f"วันที่: {thaidate.short(activity['planned_date'])}"
                       f" → {thaidate.short(data['planned_date'])}")
    if data["planned_end_date"] != activity["planned_end_date"]:
        changes.append(f"วันสิ้นสุด: {thaidate.short(activity['planned_end_date'])}"
                       f" → {thaidate.short(data['planned_end_date'])}")
    if data["assignee_id"] != activity["assignee_id"]:
        changes.append("เปลี่ยนผู้รับผิดชอบ")
    if data["priority"] != activity["priority"]:
        changes.append(f"ความสำคัญ: {PRIORITY_LABELS[activity['priority']]}"
                       f" → {PRIORITY_LABELS[data['priority']]}")

    # งานที่ซิงค์มาจากโปรแกรมอื่น ถ้าคนที่นี่แก้วันเอง ให้ปักธงไว้
    # รอบซิงค์ถัดไปจะได้ไม่เอาวันจากต้นทางมาทับ (ดู sync/runner._update_plan_only)
    # และฝั่งต้นทางจะมาดึงวันนี้กลับไปใช้เอง
    date_changed = (data["planned_date"] != activity["planned_date"]
                    or data["planned_end_date"] != activity["planned_end_date"])
    overridden = bool(activity.get("source_system")) and (
        date_changed or activity.get("date_overridden", False))

    execute(conn, """
        UPDATE activities SET
            title = %(title)s, category_id = %(category_id)s, description = %(description)s,
            assignee_id = %(assignee_id)s, priority = %(priority)s,
            planned_date = %(planned_date)s, planned_end_date = %(planned_end_date)s,
            date_overridden = %(overridden)s,
            -- คนแก้วันเองแล้ว ถือว่าเป็นเจ้าของวันนั้น ระบบต้องไม่ไปดึงกลับทีหลัง
            -- (ตัดสายจาก shift_source_id ที่ตั้งไว้ตอนถูกดันออกไปตาม migration 009)
            shift_source_id = CASE WHEN %(date_changed)s THEN NULL ELSE shift_source_id END,
            is_all_day = %(is_all_day)s,
            planned_start_time = %(planned_start_time)s, planned_end_time = %(planned_end_time)s,
            duration_min = %(duration_min)s, carry_over = %(carry_over)s,
            needs_start = %(needs_start)s,
            auto_skip_after_days = %(auto_skip_after_days)s,
            updated_at = NOW(), updated_by = %(user_id)s
         WHERE id = %(id)s
    """, {**data, "id": activity["id"], "user_id": user["id"],
          "overridden": overridden, "date_changed": date_changed})

    # การเลื่อนวันโดยตั้งใจต้องแยกออกจากการแก้ข้อมูลทั่วไป เพราะเป็นคนละเรื่องกันในรายงาน
    if overridden and date_changed:
        changes.append("วันที่นี้จะถูกส่งกลับไปใช้ที่โปรแกรมต้นทาง")

    action = "rescheduled" if data["planned_date"] != activity["planned_date"] else "edited"
    _log(conn, activity["id"], action, user, detail=" · ".join(changes) or "แก้ไขรายละเอียด")


def start(conn, activity: dict, user: dict, confirmed: bool = False) -> str | None:
    """กดเริ่มงาน

    confirmed มาจากกล่องยืนยันบนหน้าจอ · **บังคับเฉพาะกรณีที่ยังไม่ถึงวันเริ่ม**
    เพราะการเริ่มงานก่อนกำหนดทำให้ข้อมูลเวลาที่ใช้จริงเพี้ยน จึงต้องกันจริงที่เซิร์ฟเวอร์
    ไม่ใช่กันแค่บนหน้าจอ · ส่วนงานที่ถึงกำหนดแล้ว กล่องยืนยันมีไว้กันกดพลาดเฉยๆ
    จึงไม่บังคับที่นี่ เผื่อกรณีเบราว์เซอร์ปิด JavaScript จะยังกดเริ่มงานตามปกติได้
    """
    if activity["status"] != "planned":
        return f"งานนี้{STATUS_LABELS[activity['status']]}อยู่แล้ว กดเริ่มซ้ำไม่ได้"
    if not activity.get("needs_start", True):
        return "งานนี้ตั้งไว้ว่าไม่ต้องกดเริ่ม — เป็นรายการแจ้งให้ทราบเฉยๆ"

    state = start_state(activity)
    if state["start_state"] == START_EARLY and not confirmed:
        return (f"งานนี้ยังไม่ถึงกำหนด (เริ่ม {thaidate.short(activity['planned_date'])} "
                f"อีก {state['start_days']} วัน) — กดเริ่มจากหน้ารายละเอียดเพื่อยืนยัน")

    execute(conn, """
        UPDATE activities SET status = 'in_progress', started_at = NOW(), started_by = %s,
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (user["id"], user["id"], activity["id"]))

    if state["start_state"] == START_EARLY:
        detail = (f"เริ่มก่อนกำหนด {state['start_days']} วัน "
                  f"(แผนเริ่ม {thaidate.short(activity['planned_date'])})")
    elif state["start_state"] == START_LATE:
        detail = (f"เริ่มช้ากว่าแผน {state['start_days']} วัน "
                  f"(แผนเดิม {thaidate.short(activity['planned_date'])})")
    else:
        detail = ""
    _log(conn, activity["id"], "started", user, activity["status"], "in_progress", detail)

    _shift_to_actual_start(conn, activity, user)
    return None


MAX_CHAIN = 60          # กันวนไม่รู้จบถ้าข้อมูลผิดปกติ


def shift_chain(conn, activity: dict, target: date) -> dict | None:
    """ถ้าจะย้ายงานนี้ไปวันที่ target ต้องขยับรอบอื่นของแผนประจำอะไรบ้าง

    คืน None = ย้ายได้เลย ไม่ชนใคร
    คืน dict = มีรอบอื่นขวางอยู่ ต้องให้ผู้ใช้ยืนยันก่อน

    รอบที่ขวางจะถูกเลื่อนออกไป "ตามคาบของแผน" (period_after) ซึ่งอาจไปชน
    รอบถัดไปอีกต่อหนึ่ง จึงต้องไล่เป็นลูกโซ่จนกว่าจะเจอวันว่าง

    ถ้าลูกโซ่ไปเจอรอบที่เริ่มไปแล้ว/ปิดไปแล้ว จะขยับไม่ได้ — คืน blocked
    เพราะการไปขยับงานที่ลงมือไปแล้วคือการแก้ประวัติ
    """
    if not activity.get("series_id"):
        return None

    series = fetchone(conn, "SELECT * FROM activity_series WHERE id = %s",
                      (activity["series_id"],))
    if series is None:
        return None

    moves: list[dict] = []
    seen: set[int] = {activity["id"]}
    cur = target

    for _ in range(MAX_CHAIN):
        row = fetchone(conn, """
            SELECT id, title, planned_date, planned_end_date, status
              FROM activities
             WHERE series_id = %s AND planned_date = %s AND id <> %s AND NOT is_deleted
        """, (activity["series_id"], cur, activity["id"]))
        if row is None:
            break
        if row["id"] in seen:        # กันวนซ้ำที่เดิม
            break
        seen.add(row["id"])

        if row["status"] != "planned":
            return {"moves": moves,
                    "blocked": f"รอบวันที่ {thaidate.short(cur)} "
                               f"{STATUS_LABELS[row['status']]}แล้ว จึงขยับไม่ได้"}

        nxt = recurrence.period_after(series, row["planned_date"])
        span = (row["planned_end_date"] or row["planned_date"]) - row["planned_date"]
        moves.append({
            "id": row["id"], "title": row["title"],
            "from": row["planned_date"], "to": nxt,
            "from_end": row["planned_end_date"], "to_end": nxt + span,
        })
        cur = nxt

    if not moves:
        return None
    return {"moves": moves, "blocked": None,
            "period": recurrence.describe(series)}


def apply_shift(conn, activity: dict, user: dict) -> str | None:
    """ยืนยันแล้ว — ขยับรอบที่ขวางออกไป แล้วเลื่อนงานนี้มาวันที่ลงมือจริง

    ต้องอัปเดต **จากปลายลูกโซ่ย้อนกลับมา** เพราะ UNIQUE (series_id, planned_date)
    ตรวจทีละคำสั่ง ไม่ได้รอถึงตอน commit · ถ้าขยับตัวต้นก่อน มันจะไปทับตัวถัดไป
    ที่ยังไม่ได้ขยับ แล้วพังทันที
    """
    if activity["status"] != "in_progress":
        return "ยืนยันการเลื่อนได้เฉพาะงานที่กดเริ่มไปแล้ว"

    today = thaidate.today()
    plan = shift_chain(conn, activity, today)
    if plan is None:
        return None                      # ไม่มีอะไรขวางแล้ว (อาจมีคนจัดการไปก่อน)
    if plan["blocked"]:
        return plan["blocked"]

    for mv in reversed(plan["moves"]):
        # เก็บวันเดิมกับ "ใครเป็นคนทำให้ต้องย้าย" ไว้ด้วย เพื่อให้ถอนการเริ่มงาน
        # แล้วดึงกลับมาได้ · COALESCE กันไม่ให้วันเดิมถูกเขียนทับถ้าโดนดันซ้ำรอบสอง
        execute(conn, """
            UPDATE activities
               SET planned_date = %s, planned_end_date = %s,
                   planned_date_original     = COALESCE(planned_date_original, planned_date),
                   planned_end_date_original = COALESCE(planned_end_date_original,
                                                        planned_end_date),
                   shift_source_id = COALESCE(shift_source_id, %s),
                   updated_at = NOW(), updated_by = %s
             WHERE id = %s AND status = 'planned'
        """, (mv["to"], mv["to_end"], activity["id"], user["id"], mv["id"]))
        _log(conn, mv["id"], "rescheduled", user, None, None,
             f"เลื่อนออกไปตามคาบของแผน {thaidate.short(mv['from'])} → "
             f"{thaidate.short(mv['to'])} "
             f"(เพราะรอบก่อนหน้าถูกเลื่อนมาลงวันที่ {thaidate.short(today)})")

    _shift_to_actual_start(conn, activity, user)
    return None


def _shift_to_actual_start(conn, activity: dict, user: dict,
                           target: date | None = None) -> None:
    """เลื่อนวันในแผนให้ตรงกับวันที่ลงมือจริง

    `target` ว่าง = วันนี้ (ตอนกดเริ่มงาน) · ส่งวันมาเอง = ตอนแก้วันเริ่มย้อนหลัง
    ใช้ตัวเดียวกันทั้งสองทาง กติกาการคงระยะเวลาและการเก็บวันเดิมจะได้ไม่แยกร่าง

    งานหลายวันเลื่อนทั้งแผง — ระยะเวลาที่วางไว้ไม่เปลี่ยน ย้ายแค่จุดเริ่ม
    (แผน 3 วัน เริ่มช้า 5 วัน ก็ยังเป็นงาน 3 วัน ไม่ใช่ 8 วัน)

    เก็บวันเดิมไว้ที่ planned_date_original ครั้งแรกครั้งเดียว ด้วย COALESCE
    ถ้าเขียนทับทุกรอบ พอมีคนกดเริ่ม-ถอน-เริ่มใหม่ "แผนเดิม" จะกลายเป็น
    วันที่เพิ่งเลื่อนไปเมื่อกี้ แล้วรายงานจะบอกว่าทำตรงแผนทั้งที่ช้าไปหลายวัน
    """
    today = target or thaidate.today()
    old_start = activity["planned_date"]
    if old_start == today:
        return  # ตรงวันที่วางไว้อยู่แล้ว ไม่มีอะไรต้องเลื่อน

    old_end = activity.get("planned_end_date") or old_start
    span = old_end - old_start          # timedelta — คงระยะเวลาเดิมไว้
    new_end = today + span

    # แผนงานประจำมี UNIQUE (series_id, planned_date) — ถ้าเลื่อนไปชนรอบอื่น
    # ของสายเดียวกัน UPDATE จะพังทั้งคำสั่ง แล้วการกดเริ่มงานจะล้มไปด้วย
    #
    # กรณีนี้ยังไม่เลื่อนตรงนี้ แต่ไปถามผู้ใช้ก่อนว่าจะให้เลื่อนรอบถัดไปออกไป
    # ตามคาบของแผนหรือไม่ (shift_chain / apply_shift) · พอรอบถัดไปขยับหลบแล้ว
    # การชนก็หายไปเอง ไม่ต้องแก้โครงสร้างฐานข้อมูล
    if shift_chain(conn, activity, today):
        _log(conn, activity["id"], "rescheduled", user, None, None,
             f"ยังไม่เลื่อนวัน — วันที่ {thaidate.short(today)} มีงานรอบอื่นของแผนประจำนี้อยู่ "
             f"รอผู้ใช้ยืนยันว่าจะเลื่อนรอบถัดไปออกไปหรือไม่")
        return

    execute(conn, """
        UPDATE activities
           SET planned_date = %(start)s,
               planned_end_date = %(end)s,
               planned_date_original     = COALESCE(planned_date_original, %(old_start)s),
               planned_end_date_original = COALESCE(planned_end_date_original, %(old_end)s),
               date_overridden = CASE WHEN source_system IS NOT NULL
                                      THEN TRUE ELSE date_overridden END,
               updated_at = NOW(), updated_by = %(user_id)s
         WHERE id = %(id)s
    """, {"start": today, "end": new_end, "old_start": old_start, "old_end": old_end,
          "user_id": user["id"], "id": activity["id"]})

    span_note = f" (ยาว {span.days + 1} วัน เลื่อนทั้งแผง)" if span.days else ""
    _log(conn, activity["id"], "rescheduled", user, None, None,
         f"เลื่อนแผนตามวันที่ลงมือจริง {thaidate.short(old_start)} → "
         f"{thaidate.short(today)}{span_note}")


def set_start_date(conn, activity: dict, user: dict, new_date: date) -> str | None:
    """แก้วันที่เริ่มงานย้อนหลัง — ใช้ตอนลงมือจริงไปแล้วแต่ลืมกดปุ่ม

    ตัวอย่างที่ผู้ใช้ยกมา: ลงมือจริง 5 ก.ย. แต่มากดเริ่มวันที่ 6 ก.ย.
    ต้องแก้ให้ตรงความจริงทั้งสองอย่าง ไม่ใช่อย่างเดียว:
      1. `started_at` — เพราะ `finish()` คิด `actual_minutes` จากค่านี้
         ถ้าไม่แก้ เวลาที่ใช้จริงจะสั้นกว่าความจริงไป 1 วัน
      2. วันในแผน — เพราะกติกาข้อ 1 บอกว่าปฏิทินต้องสะท้อนวันที่ลงมือจริง
         ถ้าแก้แต่ `started_at` ปฏิทินจะยังโชว์วันที่กดผิดอยู่

    **เก็บเวลานาฬิกาเดิมไว้ เปลี่ยนแค่วัน** — ผู้ใช้ขอแก้ "วัน" เท่านั้น
    การเดาเวลาให้ใหม่จะทำให้ตัวเลขเวลาที่ใช้จริงมั่วกว่าเดิม
    """
    if activity["status"] != "in_progress":
        return "แก้วันเริ่มงานได้เฉพาะงานที่กำลังทำอยู่"
    if activity["started_at"] is None:
        return "งานนี้ไม่มีเวลาเริ่มบันทึกไว้"

    today = thaidate.today()
    if new_date > today:
        return "วันเริ่มงานเป็นวันในอนาคตไม่ได้"

    old_started = activity["started_at"]
    if thaidate.local_date(old_started) == new_date:
        return None                     # ตรงอยู่แล้ว ไม่ต้องทำอะไร

    # วันปลายทางอาจชนรอบอื่นของแผนประจำ — ถ้าปล่อยไป UPDATE จะพังทั้งคำสั่ง
    # ที่นี่ไม่มีขั้นตอนยืนยันแบบตอนกดเริ่มงาน จึงบอกเหตุผลแล้วไม่ทำ
    clash = shift_chain(conn, activity, new_date)
    if clash:
        return (f"เลื่อนไปวันที่ {thaidate.short(new_date)} ไม่ได้ "
                f"เพราะมีงานรอบอื่นของแผนประจำนี้อยู่วันนั้นแล้ว")

    # ประกอบวันใหม่กับเวลานาฬิกาเดิม แล้วแปลงกลับเป็น timestamptz
    # ทำใน SQL เพราะ PostgreSQL มีฐานข้อมูลเขตเวลาของตัวเอง ไม่ต้องพึ่ง Windows
    execute(conn, """
        UPDATE activities
           SET started_at = (%s::date
                             + (started_at AT TIME ZONE 'Asia/Bangkok')::time)
                            AT TIME ZONE 'Asia/Bangkok',
               updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (new_date, user["id"], activity["id"]))

    _log(conn, activity["id"], "rescheduled", user, None, None,
         f"แก้วันเริ่มงานจริง {thaidate.short(thaidate.local_date(old_started))} → "
         f"{thaidate.short(new_date)}")

    _shift_to_actual_start(conn, activity, user, target=new_date)
    return None


def unstart(conn, activity: dict, user: dict) -> str | None:
    """ยกเลิกการเริ่มงาน — กลับไปเป็นแผนเหมือนยังไม่ได้กด

    ใช้ตอนกดผิด · ล้าง started_at ทิ้งเพราะเวลาที่กดผิดไม่ใช่เวลาเริ่มงานจริง
    ถ้าเก็บไว้ รายงาน "เวลาที่ใช้จริง" จะยาวเกินความจริง
    แต่ประวัติใน activity_log ยังอยู่ครบ — เห็นได้ว่าเคยกดเริ่มแล้วถอน
    """
    if activity["status"] != "in_progress":
        return "ยกเลิกการเริ่มงานได้เฉพาะงานที่กำลังทำอยู่"
    execute(conn, """
        UPDATE activities SET status = 'planned', started_at = NULL, started_by = NULL,
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (user["id"], activity["id"]))
    detail = ""
    if activity["started_at"]:
        detail = f"เดิมกดเริ่มไว้เมื่อ {thaidate.stamp(activity['started_at'])}"
    _log(conn, activity["id"], "unstarted", user, "in_progress", "planned", detail)

    _restore_planned_dates(conn, activity, user)
    return None


def _restore_planned_dates(conn, activity: dict, user: dict) -> None:
    """คืนวันในแผนกลับเป็นวันเดิม หลังถอนการเริ่มงาน

    ด้วยเหตุผลเดียวกับที่ล้าง started_at ทิ้ง — ถอนการเริ่ม แปลว่า "ไม่ได้เริ่มจริง"
    วันที่ถูกเลื่อนมาเพราะการกดผิดจึงไม่ใช่วันจริงเหมือนกัน ถ้าปล่อยไว้
    แผนจะถูกย้ายถาวรทั้งที่ไม่มีใครได้ลงมือทำอะไรเลย

    ล้าง _original ทิ้งด้วย เพื่อให้กลับไปเป็นเหมือนไม่เคยถูกเลื่อน
    ถ้าเก็บไว้ รายงานจะยังเทียบกับ "แผนเดิม" ทั้งที่วันปัจจุบันก็คือแผนเดิมนั้นแล้ว
    """
    orig_start = activity.get("planned_date_original")
    if not orig_start:
        return                      # ไม่เคยถูกเลื่อน ไม่มีอะไรต้องคืน

    orig_end = activity.get("planned_end_date_original") or orig_start

    # วันเดิมอาจถูกรอบอื่นของแผนประจำเข้าไปจับจองระหว่างนี้ — ถ้าคืนไปจะชน
    # UNIQUE (series_id, planned_date) แล้วการกดถอนจะพังทั้งที่ผู้ใช้แค่กดถอน
    if activity.get("series_id"):
        clash = fetchone(conn, """
            SELECT id FROM activities
             WHERE series_id = %s AND planned_date = %s AND id <> %s AND NOT is_deleted
        """, (activity["series_id"], orig_start, activity["id"]))
        if clash:
            _log(conn, activity["id"], "rescheduled", user, None, None,
                 f"คืนวันเดิม ({thaidate.short(orig_start)}) ไม่ได้ "
                 f"เพราะมีงานรอบอื่นของแผนประจำนี้อยู่วันนั้นแล้ว")
            return

    execute(conn, """
        UPDATE activities
           SET planned_date = %s, planned_end_date = %s,
               planned_date_original = NULL, planned_end_date_original = NULL,
               updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (orig_start, orig_end, user["id"], activity["id"]))

    _log(conn, activity["id"], "rescheduled", user, None, None,
         f"คืนวันเดิมหลังถอนการเริ่มงาน {thaidate.short(activity['planned_date'])} → "
         f"{thaidate.short(orig_start)}")

    _restore_pushed_rounds(conn, activity, user)


def _restore_pushed_rounds(conn, activity: dict, user: dict) -> None:
    """ดึงรอบของแผนประจำที่ถูกดันออกไปเพราะงานนี้ กลับมาที่เดิม

    ตรรกะเดียวกับการคืนวันของงานตัวเองเป๊ะ — ระบบย้ายวันไหนไป ก็ย้ายกลับได้หมด
    ถ้าคืนแค่ครึ่งเดียว ตารางจะค้างอยู่ในสภาพที่ไม่มีใครตั้งใจ:
    งานกลับไปวันเดิมแล้ว แต่รอบถัดไปยังถูกดันออกไปอีก 6 เดือนอยู่

    **ลำดับสำคัญ** — เรียงตาม planned_date_original จากน้อยไปมาก คือไล่จาก
    ต้นลูกโซ่ไปหาปลาย · ปลายทางของแต่ละตัวจะถูกปล่อยว่างโดยตัวก่อนหน้าพอดี
    ถ้าคืนสลับลำดับจะไปชน UNIQUE (series_id, planned_date) แล้วพังกลางคัน
    (ตอนนี้งานตัวเองคืนวันไปแล้ว วันที่มันเคยยึดไว้จึงว่างพอดีสำหรับตัวแรก)
    """
    pushed = fetchall(conn, """
        SELECT id, title, planned_date, planned_end_date, series_id,
               planned_date_original, planned_end_date_original
          FROM activities
         WHERE shift_source_id = %s AND NOT is_deleted
           AND status = 'planned' AND planned_date_original IS NOT NULL
         ORDER BY planned_date_original
    """, (activity["id"],))

    for row in pushed:
        back_to = row["planned_date_original"]
        back_end = row["planned_end_date_original"] or back_to

        # วันเดิมอาจมีคนอื่นเข้าไปอยู่แล้ว — ข้ามตัวนั้นไป อย่าให้ทั้งชุดพัง
        clash = fetchone(conn, """
            SELECT id FROM activities
             WHERE series_id = %s AND planned_date = %s AND id <> %s AND NOT is_deleted
        """, (row["series_id"], back_to, row["id"]))
        if clash:
            _log(conn, row["id"], "rescheduled", user, None, None,
                 f"คืนวันเดิม ({thaidate.short(back_to)}) ไม่ได้ "
                 f"เพราะมีงานรอบอื่นอยู่วันนั้นแล้ว")
            continue

        execute(conn, """
            UPDATE activities
               SET planned_date = %s, planned_end_date = %s,
                   planned_date_original = NULL, planned_end_date_original = NULL,
                   shift_source_id = NULL, updated_at = NOW(), updated_by = %s
             WHERE id = %s
        """, (back_to, back_end, user["id"], row["id"]))
        _log(conn, row["id"], "rescheduled", user, None, None,
             f"ดึงกลับมาที่เดิม {thaidate.short(row['planned_date'])} → "
             f"{thaidate.short(back_to)} (เพราะรอบที่มาทับถูกถอนการเริ่มงาน)")


def finish(conn, activity: dict, user: dict | None, result_note: str = "") -> str | None:
    """user เป็น None ได้ เมื่อรอบซิงค์อัตโนมัติเป็นคนปิดงาน ไม่ใช่คนกด"""
    if activity["status"] not in ("planned", "in_progress"):
        return f"งาน{STATUS_LABELS[activity['status']]}แล้ว กดสิ้นสุดไม่ได้"
    uid = user["id"] if user else None

    # เก็บนาทีที่ใช้จริงไว้เลย ไม่คำนวณสดตอนเปิดรายงาน — ไม่งั้นตัวเลขเก่าจะขยับ
    # เมื่อมีคนแก้เวลาย้อนหลัง และรายงานที่พิมพ์ไปแล้วจะไม่ตรงกับหน้าจอ
    started = activity["started_at"]
    forgot_start = started is None
    minutes = None
    if not forgot_start:
        minutes = max(0, int((thaidate.now() - started).total_seconds() // 60))

    execute(conn, """
        UPDATE activities SET status = 'done', finished_at = NOW(), finished_by = %s,
                              actual_minutes = %s,
                              result_note = CASE WHEN %s = '' THEN result_note ELSE %s END,
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (uid, minutes, result_note, result_note, uid, activity["id"]))

    if forgot_start:
        detail = "ปิดงานโดยไม่ได้กดเริ่ม — ไม่มีเวลาที่ใช้จริง"
    else:
        detail = f"ใช้เวลา {thaidate.duration(minutes)}"
    _log(conn, activity["id"], "finished", user, activity["status"], "done", detail)
    # รอบถัดไปของแผนแบบ after_done นับจากวันนี้ (วันที่กดเสร็จ)
    _advance_series(conn, activity, thaidate.today())
    return None


def reopen(conn, activity: dict, user: dict) -> str | None:
    """เปิดงานที่ปิดไปแล้วกลับมาทำต่อ (admin/manager เท่านั้น)"""
    if activity["status"] not in CLOSED_STATUSES:
        return "งานนี้ยังไม่ได้ปิด ไม่ต้องเปิดใหม่"
    back_to = "in_progress" if activity["started_at"] else "planned"
    execute(conn, """
        UPDATE activities SET status = %s, finished_at = NULL, finished_by = NULL,
                              actual_minutes = NULL, cancel_reason = '',
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (back_to, user["id"], activity["id"]))
    _log(conn, activity["id"], "reopened", user, activity["status"], back_to)
    return None


def cancel(conn, activity: dict, user: dict | None, reason: str) -> str | None:
    """user เป็น None ได้ เมื่อต้นทางลบแผนแล้วรอบซิงค์เป็นคนยกเลิกให้"""
    if activity["status"] in CLOSED_STATUSES:
        return f"งานนี้{STATUS_LABELS[activity['status']]}อยู่แล้ว"
    execute(conn, """
        UPDATE activities SET status = 'cancelled', cancel_reason = %s,
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (reason, user["id"] if user else None, activity["id"]))
    _log(conn, activity["id"], "cancelled", user, activity["status"], "cancelled",
         reason or "ไม่ได้ระบุเหตุผล")
    # ยกเลิกแปลว่าไม่ได้ลงมือทำ จึงนับรอบถัดไปจากวันที่วางแผนไว้ ไม่ใช่วันนี้
    _advance_series(conn, activity, activity["planned_end_date"])
    return None


def mark_missed(conn, activity: dict, user: dict, reason: str = "") -> str | None:
    """ปิดงานค้างว่า 'ไม่ได้ทำ' — ต่างจากยกเลิก เพราะแผนยังถูกต้องแต่ทำไม่ทัน"""
    if activity["status"] in CLOSED_STATUSES:
        return f"งานนี้{STATUS_LABELS[activity['status']]}อยู่แล้ว"
    execute(conn, """
        UPDATE activities SET status = 'missed', cancel_reason = %s,
                              updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (reason, user["id"], activity["id"]))
    _log(conn, activity["id"], "missed", user, activity["status"], "missed",
         reason or f"ค้างมา {activity['days_late']} วัน")
    _advance_series(conn, activity, activity["planned_end_date"])
    return None


def add_note(conn, activity: dict, user: dict, note: str):
    execute(conn, """
        UPDATE activities SET result_note = %s, updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (note, user["id"], activity["id"]))
    _log(conn, activity["id"], "noted", user, detail=note[:200])


def soft_delete(conn, activity: dict, user: dict):
    """ลบแบบซ่อน ไม่ลบจริง — ประวัติของงานที่เคยทำต้องอยู่ครบ"""
    execute(conn, "UPDATE activities SET is_deleted = TRUE, updated_by = %s WHERE id = %s",
            (user["id"], activity["id"]))
    _log(conn, activity["id"], "deleted", user, activity["status"])


# ── สิทธิ์ที่ติดไปกับข้อมูล ──────────────────────────────────
# template ตัดสินใจว่าจะแสดงปุ่มไหนจากธงสองตัวนี้ ไม่ต้องรู้กฎสิทธิ์เอง
# ถ้าปล่อยให้ template คิดเอง กฎจะกระจายไปหลายไฟล์แล้วหลุดกันคนละหน้า

def annotate(rows: list[dict], user: dict) -> list[dict]:
    from auth import can_edit_activity, can_run_activity
    today = thaidate.today()
    for row in rows:
        row["can_run"] = can_run_activity(user, row)
        row["can_edit"] = can_edit_activity(user, row)
        row.update(start_state(row, today))
    return rows


def start_state(activity: dict, today: date | None = None) -> dict:
    """วันนี้อยู่ตรงไหนของช่วงที่วางแผนไว้

    ใช้เลือกข้อความในกล่องยืนยันก่อนกดเริ่มงาน · คำนวณที่ฝั่งเซิร์ฟเวอร์
    เพื่อให้หน้าจอกับการตรวจสอบตอนรับ POST ใช้เกณฑ์เดียวกันเป๊ะ
    ถ้าคำนวณซ้ำใน JavaScript อีกชุด สองฝั่งจะเพี้ยนกันได้เมื่อเครื่องผู้ใช้ตั้งวันผิด
    """
    today = today or thaidate.today()
    start = activity["planned_date"]
    end = activity.get("planned_end_date") or start

    if today < start:
        return {"start_state": START_EARLY, "start_days": (start - today).days}
    if today > end:
        return {"start_state": START_LATE, "start_days": (today - end).days}
    return {"start_state": START_ONTIME, "start_days": 0}
