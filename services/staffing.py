"""services/staffing.py — นิยามเรื่องคน: ใครลา ใครประจำจุดไหน ใครว่าง ขาดคนตรงไหน (v2)

ทุกหน้าที่ต้องรู้ว่า "วันนี้ใครลา / ใครว่าง / จุดไหนขาดคน" ต้องเรียกที่นี่ ห้ามเขียน query เอง
ไม่งั้นแต่ละหน้าจะนิยาม "ลา" ไม่ตรงกัน — บทเรียนเดียวกับที่ "งานค้าง" เคยนิยาม
ไม่ตรงกันสองที่แล้วป้ายบนจอกับตัวปิดอัตโนมัติเถียงกัน

นิยาม (§29.8):
    ลา(D)          staff_leaves ที่คาบวัน D (รวมครึ่งวัน)
    ประจำจุด(P,D)  duty_assignments ที่คาบวัน D (ทั้งประจำและคนแทน) − ลา(D)
    ขาดคน(P,D)     |ประจำจุด(P,D)| < required_n   (NULL = ต้องครบทุกคนประจำ)
    มีกิจกรรม(D)   กิจกรรมที่คาบวัน D ซึ่งคนนั้นเป็นผู้รับผิดชอบหรือผู้ปฏิบัติงาน
    ว่าง(D)        พนักงาน active − ลา(D) − ประจำจุดใดๆ(D) − มีกิจกรรม(D)

ส่วนที่เป็นตรรกะล้วน (roster_for_day / free_on / shortfalls) รับ rows เข้ามาแล้วคำนวณ
ทดสอบได้โดยไม่ต้องมี DB · ส่วนที่ต่อ DB คือตัวโหลด rows ให้
เฟส D ใช้ `on_leave_ids()` กันเลือกคนลาเป็นผู้ปฏิบัติงาน
"""
from datetime import date, timedelta

from database import execute, fetchall, fetchone
from services import thaidate

PART_LABELS = {"full": "ทั้งวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
# ป้ายสั้นบนแถบในปฏิทิน — ที่ว่างน้อย ต้องอ่านออกในสามตัวอักษร
PART_SHORT = {"full": "ลา", "am": "ลาเช้า", "pm": "ลาบ่าย"}

# ย้อนหลังกี่วันในหน้ารายการวันลา — พอให้ดูเดือนที่แล้วได้ ไม่ต้องดึงทั้งประวัติ
PAST_DAYS = 90

_SELECT = """
    SELECT l.*, s.name AS staff_name, s.color AS staff_color, s.code AS staff_code,
           s.department_id, d.name AS department_name,
           t.name AS type_name, t.color AS type_color,
           (l.date_to - l.date_from + 1) AS span_days
      FROM staff_leaves l
      JOIN staff s ON s.id = l.staff_id
      LEFT JOIN departments d ON d.id = s.department_id
      LEFT JOIN leave_types t ON t.id = l.leave_type_id
     WHERE NOT l.is_deleted
"""
_ORDER = " ORDER BY l.date_from, l.date_to, s.sort_order, s.name, l.id"


# ── อ่าน ─────────────────────────────────────────────────────

def get(conn, leave_id: int) -> dict | None:
    return fetchone(conn, _SELECT + " AND l.id = %s", (leave_id,))


def between(conn, start: date, end: date, staff_id: int | None = None) -> list[dict]:
    """การลาที่คาบเกี่ยวช่วง [start, end] — คิดแบบคาบเกี่ยว ไม่ใช่ BETWEEN

    ลา 5 วันที่เริ่มก่อนต้นช่วงแต่ยังลาอยู่ ต้องติดมาด้วย ไม่งั้นปฏิทินต้นเดือน
    จะไม่เห็นว่าคนนี้ยังลาอยู่
    """
    sql = _SELECT + " AND l.date_from <= %s AND l.date_to >= %s"
    params: list = [end, start]
    if staff_id:
        sql += " AND l.staff_id = %s"
        params.append(staff_id)
    return fetchall(conn, sql + _ORDER, params)


def listing(conn, staff_id: int | None = None, department_id: int | None = None,
            today: date | None = None) -> dict[str, list[dict]]:
    """สองกลุ่มสำหรับหน้าจัดการ: กำลังลา/จะลา (เรียงจากใกล้ไปไกล) · ที่ผ่านมา (ล่าสุดก่อน)"""
    today = today or thaidate.today()
    where, params = "", []
    if staff_id:
        where += " AND l.staff_id = %s"
        params.append(staff_id)
    if department_id:
        where += " AND s.department_id = %s"
        params.append(department_id)

    upcoming = fetchall(conn, _SELECT + where + " AND l.date_to >= %s" + _ORDER,
                        params + [today])
    past = fetchall(conn, _SELECT + where + " AND l.date_to < %s AND l.date_to >= %s"
                    " ORDER BY l.date_from DESC, l.id DESC",
                    params + [today, today - timedelta(days=PAST_DAYS)])
    return {"upcoming": upcoming, "past": past}


def on_leave_ids(conn, day: date) -> set[int]:
    """id ของคนที่ลาวันนั้น (รวมครึ่งวัน) — เฟส D ใช้กันไม่ให้เลือกเป็นผู้ปฏิบัติงาน"""
    rows = fetchall(conn, """
        SELECT DISTINCT staff_id FROM staff_leaves
         WHERE NOT is_deleted AND date_from <= %s AND date_to >= %s
    """, (day, day))
    return {r["staff_id"] for r in rows}


def leaves_on(leaves: list[dict], day: date) -> list[dict]:
    """กรองรายการที่ดึงมาแล้ว (จาก between) เอาเฉพาะที่คาบวันนี้ — ตรรกะล้วน ทดสอบได้"""
    return [l for l in leaves if l["date_from"] <= day <= l["date_to"]]


# ── เขียน ────────────────────────────────────────────────────

def overlap(conn, staff_id: int, date_from: date, date_to: date,
            exclude_id: int | None = None) -> dict | None:
    """การลาของคนเดียวกันที่ทับช่วงนี้ — คนเดียวลาซ้อนกันสองรายการไม่ได้

    ครึ่งวันเช้า + ครึ่งวันบ่ายวันเดียวกันก็ถือว่าซ้อน ให้บันทึกเป็นทั้งวันแทน
    """
    sql = _SELECT + " AND l.staff_id = %s AND l.date_from <= %s AND l.date_to >= %s"
    params: list = [staff_id, date_to, date_from]
    if exclude_id:
        sql += " AND l.id <> %s"
        params.append(exclude_id)
    return fetchone(conn, sql + _ORDER + " LIMIT 1", params)


def validate(conn, data: dict, exclude_id: int | None = None) -> str | None:
    """คืนข้อความผิดพลาด หรือ None ถ้าบันทึกได้

    ตรวจที่นี่ที่เดียว ทั้งฟอร์มบนหน้าวันลาและปุ่มลัดจากปฏิทินเรียกตัวเดียวกัน
    """
    if not data.get("staff_id"):
        return "ต้องเลือกพนักงาน"
    if not data.get("date_from") or not data.get("date_to"):
        return "ต้องระบุวันเริ่มและวันสิ้นสุดการลา"
    if data["date_to"] < data["date_from"]:
        return "วันสิ้นสุดต้องไม่ก่อนวันเริ่ม"
    if data.get("part", "full") not in PART_LABELS:
        return "รูปแบบการลาไม่ถูกต้อง"
    if data["part"] != "full" and data["date_from"] != data["date_to"]:
        return "ลาครึ่งวันต้องเป็นวันเดียว — ถ้าลาหลายวันแล้วมีครึ่งวันท้าย ให้บันทึกครึ่งวันแยกอีกรายการ"

    staff = fetchone(conn, "SELECT id, name, active FROM staff WHERE id = %s", (data["staff_id"],))
    if staff is None:
        return "ไม่พบพนักงานคนนี้ในทะเบียน"

    clash = overlap(conn, data["staff_id"], data["date_from"], data["date_to"], exclude_id)
    if clash:
        return (f"{staff['name']} มีการลาช่วง "
                f"{thaidate.span(clash['date_from'], clash['date_to'])} อยู่แล้ว — "
                "แก้รายการเดิมแทนการเพิ่มซ้อน")
    return None


def create(conn, data: dict, user: dict) -> int:
    return fetchone(conn, """
        INSERT INTO staff_leaves (staff_id, leave_type_id, date_from, date_to, part, note,
                                  created_by, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (data["staff_id"], data.get("leave_type_id"), data["date_from"], data["date_to"],
          data.get("part", "full"), data.get("note", ""), user["id"], user["id"]))["id"]


def update(conn, leave_id: int, data: dict, user: dict) -> None:
    execute(conn, """
        UPDATE staff_leaves
           SET staff_id = %s, leave_type_id = %s, date_from = %s, date_to = %s,
               part = %s, note = %s, updated_at = NOW(), updated_by = %s
         WHERE id = %s AND NOT is_deleted
    """, (data["staff_id"], data.get("leave_type_id"), data["date_from"], data["date_to"],
          data.get("part", "full"), data.get("note", ""), user["id"], leave_id))


def soft_delete(conn, leave_id: int, user: dict) -> None:
    """ลบแบบซ่อน — แถวยังอยู่ให้รายงานวันลาย้อนหลังนับได้"""
    execute(conn, """
        UPDATE staff_leaves SET is_deleted = TRUE, updated_at = NOW(), updated_by = %s
         WHERE id = %s
    """, (user["id"], leave_id))


# ── สำหรับปฏิทิน ─────────────────────────────────────────────

def bar_items(leaves: list[dict]) -> list[dict]:
    """แปลงการลาเป็น "แถบ" ที่ calgrid.build_weeks() วางลงตารางได้

    ใช้กลไกจัดชั้นเดียวกับกิจกรรม (ผู้ใช้อยากเห็นใครลาวันไหนทันทีจากปฏิทิน §29.4)
    แต่ติดธง kind='leave' ให้เทมเพลตวาดคนละแบบ และกดแล้วเปิดแถบพนักงาน
    ไม่ใช่รายละเอียดกิจกรรม เพราะมันไม่ใช่กิจกรรม

    id ใช้เลขติดลบ เพื่อไม่ให้ไปทับกับ id กิจกรรมใน _sort_key ของ calgrid
    (ตัวเทมเพลตไม่ได้ใช้ id นี้เทียบกับ pickedId อยู่แล้ว)

    lane_rank = 0 ให้การลาจองชั้นก่อนกิจกรรม — วันที่งานเยอะจนล้น MAX_LANES
    แถบลาต้องไม่ใช่ตัวที่หลุดไปอยู่ใน "+N" (ดู calgrid._sort_key)
    """
    return [{
        "kind": "leave",
        "lane_rank": 0,
        "id": -l["id"],
        "leave_id": l["id"],
        "planned_date": l["date_from"],
        "planned_end_date": l["date_to"],
        "span_days": l["span_days"],
        "priority": 3,
        "staff_id": l["staff_id"],
        "staff_name": l["staff_name"],
        "staff_color": l["staff_color"],
        "part": l["part"],
        "label": f"{PART_SHORT[l['part']]} {l['staff_name']}",
        "tooltip": " · ".join(x for x in (
            f"{PART_LABELS[l['part']]} {l['staff_name']}",
            l["type_name"] or "", thaidate.span(l["date_from"], l["date_to"]), l["note"]) if x),
    } for l in leaves]


def panel_data(leaves: list[dict]) -> list[dict]:
    """ข้อมูลการลาสำหรับแถบ "พนักงาน" ในกล่องข้าง — จัดรูปข้อความไทยที่ฝั่งเซิร์ฟเวอร์

    วัน ISO ดิบ (from/to) ส่งไปด้วยเพื่อให้ JS เทียบว่าคาบวันที่เลือกไหม
    เทียบเป็นข้อความ ISO ตรงๆ ได้เพราะ YYYY-MM-DD เรียงตามตัวอักษรตรงกับลำดับวัน
    """
    return [{
        "id": l["id"],
        "staff_id": l["staff_id"],
        "name": l["staff_name"],
        "color": l["staff_color"],
        "department": l["department_name"] or "",
        "type": l["type_name"] or "",
        "type_color": l["type_color"] or "#8592a6",
        "part": l["part"],
        "part_label": PART_LABELS[l["part"]],
        "from": l["date_from"].isoformat(),
        "to": l["date_to"].isoformat(),
        "when": thaidate.span(l["date_from"], l["date_to"]),
        "note": l["note"],
    } for l in leaves]


# ═══════════════════════════════════════════════════════════════
#  หน้าที่ประจำ (เฟส C) — จุดงาน · คนประจำ · คนแทน · ขาดคน
# ═══════════════════════════════════════════════════════════════

# มองไปข้างหน้ากี่วันเวลาหา "จุดที่กำลังจะขาดคน" (หน้าหน้าที่ประจำ + ป้ายเลขที่เมนู)
SHORTFALL_AHEAD_DAYS = 30

_POST_SELECT = """
    SELECT p.*, d.name AS department_name
      FROM duty_posts p
      LEFT JOIN departments d ON d.id = p.department_id
"""
_ASSIGN_SELECT = """
    SELECT a.*, p.name AS post_name,
           s.name AS staff_name, s.color AS staff_color, s.active AS staff_active,
           c.name AS covers_name
      FROM duty_assignments a
      JOIN duty_posts p ON p.id = a.post_id
      JOIN staff s ON s.id = a.staff_id
      LEFT JOIN staff c ON c.id = a.covers_staff_id
     WHERE NOT a.is_deleted
"""
_ASSIGN_ORDER = (" ORDER BY p.sort_order, p.name, (a.covers_staff_id IS NOT NULL), "
                 "a.starts_on, s.sort_order, s.name, a.id")


def _covers_day(row: dict, day: date) -> bool:
    return row["starts_on"] <= day and (row["ends_on"] is None or row["ends_on"] >= day)


# ── อ่าน ─────────────────────────────────────────────────────

def posts(conn, active_only: bool = True) -> list[dict]:
    sql = _POST_SELECT + (" WHERE p.active" if active_only else "")
    return fetchall(conn, sql + " ORDER BY p.sort_order, p.name")


def get_post(conn, post_id: int) -> dict | None:
    return fetchone(conn, _POST_SELECT + " WHERE p.id = %s", (post_id,))


def get_assignment(conn, assignment_id: int) -> dict | None:
    return fetchone(conn, _ASSIGN_SELECT + " AND a.id = %s", (assignment_id,))


def assignments_between(conn, start: date, end: date, post_id: int | None = None) -> list[dict]:
    """การมอบหมายที่คาบเกี่ยวช่วง [start, end] — ends_on NULL = ไม่มีกำหนด จึงคาบเสมอ"""
    sql = _ASSIGN_SELECT + " AND a.starts_on <= %s AND (a.ends_on IS NULL OR a.ends_on >= %s)"
    params: list = [end, start]
    if post_id:
        sql += " AND a.post_id = %s"
        params.append(post_id)
    return fetchall(conn, sql + _ASSIGN_ORDER, params)


def activities_by_staff(conn, start: date, end: date) -> dict[int, list[dict]]:
    """กิจกรรมที่คาบช่วง [start, end] แยกตามคน — ทั้งผู้รับผิดชอบหลักและผู้ปฏิบัติงาน

    ที่เดียวสำหรับทั้ง "ว่างไหม" ในแถบพนักงาน และป้าย "มีงานอื่น" ในฟอร์มกิจกรรม
    ไม่งั้นสองหน้าจะตอบไม่ตรงกัน

    ตัด cancelled/missed ออก — ถอนแผนหรือไม่ได้ทำ แปลว่าไม่มีใครลงแรงกับมัน
    ส่วน done ยังนับ เพราะย้อนดูวันที่ผ่านมาแล้วต้องเห็นว่าวันนั้นใครติดงานอะไร
    """
    out: dict[int, list[dict]] = {}
    for r in fetchall(conn, """
        SELECT a.id, a.title, a.status, a.planned_date, a.planned_end_date, x.staff_id
          FROM activities a
          JOIN LATERAL (
                SELECT a.assignee_id AS staff_id
                UNION SELECT h.staff_id FROM activity_helpers h WHERE h.activity_id = a.id
          ) x ON x.staff_id IS NOT NULL
         WHERE NOT a.is_deleted AND a.status NOT IN ('cancelled', 'missed')
           AND a.planned_date <= %s AND a.planned_end_date >= %s
         ORDER BY a.planned_date, a.id
    """, (end, start)):
        out.setdefault(r["staff_id"], []).append({
            "id": r["id"], "title": r["title"], "status": r["status"],
            "from": r["planned_date"].isoformat(), "to": r["planned_end_date"].isoformat()})
    return out


def active_staff(conn) -> list[dict]:
    return fetchall(conn, """
        SELECT s.id, s.name, s.color, s.code, s.department_id, d.name AS department_name
          FROM staff s LEFT JOIN departments d ON d.id = s.department_id
         WHERE s.active
         ORDER BY d.sort_order NULLS LAST, d.name, s.sort_order, s.name
    """)


def staff_groups(rows: list[dict]) -> list[dict]:
    """หั่นทะเบียนที่เรียงตามฝ่ายมาแล้วเป็นกลุ่มๆ — ใช้ทำตัวกรองฝ่ายในฟอร์ม

    ตรรกะล้วน รับ rows จาก `active_staff()` ซึ่ง ORDER BY ฝ่ายไว้แล้ว จึงแค่ไล่หั่น
    (แบบเดียวกับที่ฟอร์มกิจกรรมทำในเฟส D — ที่นี่ยกมาไว้ส่วนกลางเพื่อไม่ให้เขียนซ้ำสองที่)
    """
    groups: list[dict] = []
    for s in rows:
        key = s.get("department_id") or 0
        if not groups or groups[-1]["id"] != key:
            groups.append({"id": key, "name": s.get("department_name") or "ยังไม่ระบุฝ่าย",
                           "staff": []})
        groups[-1]["staff"].append({"id": s["id"], "name": s["name"],
                                    "position": s.get("position") or "",
                                    "department": s.get("department_name") or ""})
    return groups


def leave_ranges(conn, start: date, end: date) -> dict[int, list[dict]]:
    """ช่วงวันลาของแต่ละคนในหน้าต่างที่สนใจ — ให้ฟอร์มซ่อนคนที่ลาคาบช่วงที่กำลังกรอก

    ซ่อนบนหน้าจอเฉยๆ ส่วนการกันจริงยังอยู่ที่ `validate()` (ยิง POST ตรงได้)
    """
    out: dict[int, list[dict]] = {}
    for l in between(conn, start, end):
        out.setdefault(l["staff_id"], []).append({
            "id": l["id"], "from": l["date_from"].isoformat(), "to": l["date_to"].isoformat()})
    return out


def post_members(conn, today: date | None = None) -> dict[str, list[int]]:
    """ใครเป็น "คนประจำ" ของแต่ละจุดอยู่แล้วบ้าง (ที่ยังไม่จบ) — คีย์เป็น str ให้ JS ใช้ตรงๆ

    ฟอร์มใช้ซ่อนชื่อคนที่ถูกเลือกไปแล้ว จะได้ไม่เลือกซ้ำแล้วไปเจอ error ตอนกดบันทึก
    """
    today = today or thaidate.today()
    out: dict[str, list[int]] = {}
    for row in fetchall(conn, """
        SELECT post_id, staff_id FROM duty_assignments
         WHERE NOT is_deleted AND covers_staff_id IS NULL
           AND (ends_on IS NULL OR ends_on >= %s)
    """, (today,)):
        out.setdefault(str(row["post_id"]), []).append(row["staff_id"])
    return out


def load_roster_inputs(conn, start: date, end: date) -> dict:
    """ดึงทุกอย่างที่ตัวคำนวณล้วนต้องใช้สำหรับช่วง [start, end] ในครั้งเดียว"""
    return {
        "posts": posts(conn),
        "assignments": assignments_between(conn, start, end),
        "leaves": between(conn, start, end),
        "staff": active_staff(conn),
        "activities": activities_by_staff(conn, start, end),
    }


# ── ตรรกะล้วน ────────────────────────────────────────────────

def roster_for_day(posts_: list[dict], assignments: list[dict], leaves: list[dict],
                   day: date) -> list[dict]:
    """สภาพของทุกจุดงานในวันเดียว — ใครอยู่ ใครลา ใครมาแทน ขาดไหม

    คนแทนที่ลาเองก็ถือว่าไม่อยู่เหมือนกัน (ไม่งั้นจัดคนแทนที่ลาไปแล้วระบบจะบอกว่าครบ)
    ไม่นับคนที่ถูกปิดใช้งานแล้ว — ผังเก่าที่ยังไม่มีใครไปจบให้ ไม่ควรทำให้ระบบเห็นว่ามีคน
    """
    away = {l["staff_id"] for l in leaves if l["date_from"] <= day <= l["date_to"]}
    today_rows = [a for a in assignments if _covers_day(a, day) and a.get("staff_active", True)]
    result = []
    for post in posts_:
        rows = [a for a in today_rows if a["post_id"] == post["id"]]
        regular = [a for a in rows if a["covers_staff_id"] is None]
        covers = [a for a in rows if a["covers_staff_id"] is not None]
        present = [a for a in regular if a["staff_id"] not in away]
        absent = [a for a in regular if a["staff_id"] in away]
        covering = [a for a in covers if a["staff_id"] not in away]
        need = post["required_n"] if post["required_n"] is not None else len(regular)
        have = len(present) + len(covering)
        result.append({
            "post": post,
            "regular": regular,
            "present": present,
            "absent": absent,
            "covering": covering,
            "need": need,
            "have": have,
            "missing": max(0, need - have),
            "short": have < need,
        })
    return result


def working_on(activities: dict[int, list[dict]], day: date) -> dict[int, list[dict]]:
    """กิจกรรมของแต่ละคนที่คาบวันนั้น — คีย์คือ staff_id (ว่างเปล่าแปลว่าไม่มีใครติดงาน)"""
    iso = day.isoformat()
    out = {}
    for staff_id, rows in activities.items():
        hit = [r for r in rows if r["from"] <= iso <= r["to"]]
        if hit:
            out[staff_id] = hit
    return out


def free_on(staff: list[dict], assignments: list[dict], leaves: list[dict], day: date,
            activities: dict[int, list[dict]] | None = None) -> list[dict]:
    """คนที่ว่างจริงในวันนั้น — ไม่ลา ไม่ได้ประจำ/แทนจุดไหน และ**ไม่มีกิจกรรมที่ถูกมอบหมาย**

    ข้อสุดท้ายเพิ่มทีหลัง (2026-10-02) เพราะของเดิมหักแค่ลากับจุดงาน คนที่กำลังทำกิจกรรม
    จึงยังขึ้นว่าว่าง ทั้งที่ไม่ว่าง — ผู้ใช้เจอจากงาน "Test" ที่กดเริ่มไปแล้ว
    """
    away = {l["staff_id"] for l in leaves if l["date_from"] <= day <= l["date_to"]}
    busy = {a["staff_id"] for a in assignments if _covers_day(a, day)}
    busy |= set(working_on(activities or {}, day))
    return [s for s in staff if s["id"] not in away and s["id"] not in busy]


def shortfalls(posts_: list[dict], assignments: list[dict], leaves: list[dict],
               start: date, end: date, staff_id: int | None = None) -> list[dict]:
    """ช่วงที่แต่ละจุดขาดคน ในช่วง [start, end] — รวมวันติดกันที่ขาดเหมือนกันเป็นช่วงเดียว

    `staff_id` = สนใจเฉพาะจุดที่คนนี้เป็นคนประจำ (ใช้ตอนบันทึกการลาของเขา — §29.6)
    คืนรายการ {post, date_from, date_to, missing, need, have, absent_names}
    """
    found: list[dict] = []
    open_runs: dict[int, dict] = {}          # post_id -> ช่วงที่กำลังต่อเนื่องอยู่
    day = start
    while day <= end:
        for row in roster_for_day(posts_, assignments, leaves, day):
            pid = row["post"]["id"]
            wanted = row["short"] and (
                staff_id is None or any(a["staff_id"] == staff_id for a in row["regular"]))
            run = open_runs.get(pid)
            absent = sorted(row["absent"], key=lambda a: a["staff_name"])
            absent_names = [a["staff_name"] for a in absent]
            if wanted and run and run["date_to"] == day - timedelta(days=1) \
                    and run["missing"] == row["missing"] and run["absent_names"] == absent_names:
                run["date_to"] = day
            elif wanted:
                run = {"post": row["post"], "date_from": day, "date_to": day,
                       "missing": row["missing"], "need": row["need"], "have": row["have"],
                       "absent_names": absent_names,
                       "absent_ids": [a["staff_id"] for a in absent]}
                open_runs[pid] = run
                found.append(run)
            elif run:
                open_runs.pop(pid, None)
        day += timedelta(days=1)
    found.sort(key=lambda r: (r["date_from"], r["post"]["sort_order"], r["post"]["name"]))
    return found


# ── โหลด + คำนวณ (ทางลัดที่หน้าต่างๆ เรียก) ───────────────────

def shortfalls_between(conn, start: date, end: date, staff_id: int | None = None) -> list[dict]:
    data = load_roster_inputs(conn, start, end)
    return shortfalls(data["posts"], data["assignments"], data["leaves"], start, end, staff_id)


def shortfall_post_count(conn, today: date | None = None) -> int:
    """จำนวนจุดที่จะขาดคนภายใน SHORTFALL_AHEAD_DAYS — ป้ายเลขข้างเมนู "หน้าที่ประจำ" """
    today = today or thaidate.today()
    runs = shortfalls_between(conn, today, today + timedelta(days=SHORTFALL_AHEAD_DAYS))
    return len({r["post"]["id"] for r in runs})


def _person(a: dict) -> dict:
    return {"id": a["staff_id"], "name": a["staff_name"], "color": a["staff_color"]}


def roster_range(conn, start: date, end: date) -> dict:
    """ข้อมูลรายวันสำหรับปฏิทิน: {iso: {"posts": [...], "free": [...], "short": bool}}

    คำนวณที่ฝั่งเซิร์ฟเวอร์ทั้งหมด (นิยามขาดคนต้องอยู่ที่เดียว) แล้วส่งเฉพาะชื่อไป
    """
    data = load_roster_inputs(conn, start, end)
    out = {}
    day = start
    while day <= end:
        rows = roster_for_day(data["posts"], data["assignments"], data["leaves"], day)
        # คนที่ติดกิจกรรมวันนั้น — คนลาไม่นับ (ลาแล้วก็คือไม่อยู่ ไม่ว่าจะมีงานค้างอยู่หรือไม่)
        busy_today = working_on(data["activities"], day)
        away_today = {l["staff_id"] for l in data["leaves"] if l["date_from"] <= day <= l["date_to"]}
        out[day.isoformat()] = {
            "posts": [{
                "id": r["post"]["id"],
                "name": r["post"]["name"],
                "need": r["need"],
                "have": r["have"],
                "short": r["short"],
                "present": [_person(a) for a in r["present"]],
                "absent": [_person(a) for a in r["absent"]],
                "covering": [{**_person(a), "for": a["covers_name"] or ""} for a in r["covering"]],
            } for r in rows if r["regular"] or r["covering"] or r["need"]],
            "working": [{
                "id": s["id"], "name": s["name"], "color": s["color"],
                "department": s["department_name"] or "",
                "activities": [{"id": a["id"], "title": a["title"], "status": a["status"]}
                               for a in busy_today[s["id"]]],
            } for s in data["staff"] if s["id"] in busy_today and s["id"] not in away_today],
            "free": [{"id": s["id"], "name": s["name"], "color": s["color"],
                      "department": s["department_name"] or ""}
                     for s in free_on(data["staff"], data["assignments"], data["leaves"], day,
                                      data["activities"])],
            "short": any(r["short"] for r in rows),
            "short_names": [r["post"]["name"] for r in rows if r["short"]],
        }
        day += timedelta(days=1)
    return out


# ── เขียน: จุดงาน ────────────────────────────────────────────

def save_post(conn, data: dict, post_id: int | None = None) -> tuple[int | None, str | None]:
    if not data.get("name"):
        return None, "ต้องกรอกชื่อจุดงาน"
    if data.get("required_n") is not None and data["required_n"] < 0:
        return None, "จำนวนคนขั้นต่ำต้องไม่ติดลบ"
    dup = fetchone(conn, "SELECT id FROM duty_posts WHERE name = %s AND id <> %s",
                   (data["name"], post_id or 0))
    if dup:
        return None, f"มีจุดงานชื่อ \"{data['name']}\" อยู่แล้ว"
    values = (data["name"], data.get("department_id"), data.get("required_n"),
              data.get("description", ""), data.get("sort_order", 0), data.get("active", True))
    if post_id:
        execute(conn, """
            UPDATE duty_posts SET name = %s, department_id = %s, required_n = %s,
                   description = %s, sort_order = %s, active = %s, updated_at = NOW()
             WHERE id = %s
        """, values + (post_id,))
        return post_id, None
    row = fetchone(conn, """
        INSERT INTO duty_posts (name, department_id, required_n, description, sort_order, active)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, values)
    return row["id"], None


# ── เขียน: การมอบหมาย ────────────────────────────────────────

def validate_assignment(conn, data: dict, exclude_id: int | None = None) -> str | None:
    """ตรวจก่อนบันทึกคนประจำ/คนแทน — ที่เดียวสำหรับทุกทางเข้า

    คนแทนที่ลาอยู่ในช่วงนั้น → ปฏิเสธ (จัดคนลาไปแทนคนลา ไม่ช่วยอะไร)
    คนประจำซ้ำจุดเดิมช่วงทับกัน → ปฏิเสธ (แถวซ้ำ ไม่ใช่การย้าย)
    ประจำสองจุดพร้อมกัน → ยอม (หัวหน้าดูสองที่ได้จริง) ตาม §29.5 ที่ให้เตือนไม่ล็อก
    """
    if not data.get("post_id") or get_post(conn, data["post_id"]) is None:
        return "ต้องเลือกจุดงาน"
    if not data.get("staff_id"):
        return "ต้องเลือกพนักงาน"
    if not data.get("starts_on"):
        return "ต้องระบุวันเริ่ม"
    if data.get("ends_on") and data["ends_on"] < data["starts_on"]:
        return "วันสิ้นสุดต้องไม่ก่อนวันเริ่ม"
    if data.get("covers_staff_id") and data["covers_staff_id"] == data["staff_id"]:
        return "คนแทนต้องไม่ใช่คนเดียวกับคนที่ถูกแทน"
    staff = fetchone(conn, "SELECT id, name, active FROM staff WHERE id = %s", (data["staff_id"],))
    if staff is None or not staff["active"]:
        return "ไม่พบพนักงานคนนี้ หรือถูกปิดใช้งานแล้ว"

    if data.get("covers_staff_id"):
        # คนแทนต้องไม่ลาในช่วงที่มาแทน · ไม่มีกำหนดจบ → ดูแค่ช่วงข้างหน้าพอสมควร
        check_end = data.get("ends_on") or (data["starts_on"] + timedelta(days=SHORTFALL_AHEAD_DAYS))
        clash = between(conn, data["starts_on"], check_end, data["staff_id"])
        if clash:
            l = clash[0]
            return (f"{staff['name']} ลาช่วง {thaidate.span(l['date_from'], l['date_to'])} "
                    "จึงมาแทนช่วงนี้ไม่ได้")

        # คนประจำจุดนั้นอยู่แล้วมาเป็น "คนแทน" ของจุดเดียวกันไม่ได้ — เขาอยู่ตรงนั้นอยู่แล้ว
        # และ roster_for_day() นับ present + covering แยกกัน จะกลายเป็นนับคนเดียวสองรอบ
        # แล้วจุดที่ขาดคนจริงจะดูเหมือนครบ
        already = fetchone(conn, _ASSIGN_SELECT + """
            AND a.post_id = %s AND a.staff_id = %s AND a.covers_staff_id IS NULL
            AND a.starts_on <= %s AND (a.ends_on IS NULL OR a.ends_on >= %s)
            LIMIT 1
        """, (data["post_id"], data["staff_id"], check_end, data["starts_on"]))
        if already:
            return (f"{staff['name']} เป็นคนประจำ {already['post_name']} อยู่แล้ว "
                    "จึงไม่ต้องใส่เป็นคนแทนของจุดเดียวกัน")
        return None

    sql = _ASSIGN_SELECT + """
        AND a.post_id = %s AND a.staff_id = %s AND a.covers_staff_id IS NULL
        AND a.starts_on <= %s AND (a.ends_on IS NULL OR a.ends_on >= %s)
    """
    params: list = [data["post_id"], data["staff_id"], data.get("ends_on") or date.max,
                    data["starts_on"]]
    if exclude_id:
        sql += " AND a.id <> %s"
        params.append(exclude_id)
    dup = fetchone(conn, sql + " LIMIT 1", params)
    if dup:
        return (f"{staff['name']} ประจำ {dup['post_name']} ช่วงนี้อยู่แล้ว "
                f"(ตั้งแต่ {thaidate.short(dup['starts_on'])}) — แก้รายการเดิมแทน")
    return None


def create_assignment(conn, data: dict, user: dict) -> int:
    return fetchone(conn, """
        INSERT INTO duty_assignments (post_id, staff_id, starts_on, ends_on, covers_staff_id,
                                      note, created_by, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (data["post_id"], data["staff_id"], data["starts_on"], data.get("ends_on"),
          data.get("covers_staff_id"), data.get("note", ""), user["id"], user["id"]))["id"]


def update_assignment(conn, assignment_id: int, data: dict, user: dict) -> None:
    execute(conn, """
        UPDATE duty_assignments
           SET post_id = %s, staff_id = %s, starts_on = %s, ends_on = %s,
               covers_staff_id = %s, note = %s, updated_at = NOW(), updated_by = %s
         WHERE id = %s AND NOT is_deleted
    """, (data["post_id"], data["staff_id"], data["starts_on"], data.get("ends_on"),
          data.get("covers_staff_id"), data.get("note", ""), user["id"], assignment_id))


def end_assignment(conn, assignment_id: int, ends_on: date, user: dict) -> str | None:
    """จบการประจำ — ใช้ตอนย้ายคนไปจุดอื่นหรือลาออก ไม่ลบเพราะเป็นประวัติ"""
    row = get_assignment(conn, assignment_id)
    if row is None:
        return "ไม่พบรายการนี้"
    if ends_on < row["starts_on"]:
        return "วันสิ้นสุดต้องไม่ก่อนวันเริ่ม"
    execute(conn, "UPDATE duty_assignments SET ends_on = %s, updated_at = NOW(), updated_by = %s "
                  "WHERE id = %s", (ends_on, user["id"], assignment_id))
    return None


# ═══════════════════════════════════════════════════════════════
#  ผู้ปฏิบัติงานในกิจกรรม (เฟส D) — ใครเลือกได้ ใครเลือกไม่ได้
# ═══════════════════════════════════════════════════════════════
#
# §29.5 สองระดับ: ลา **ตลอดช่วงงาน** → ล็อกจริง (ทั้งหน้าจอและที่นี่) ·
# ลาบางวัน / ประจำจุดงาน / มีงานอื่นวันเดียวกัน → เตือนแต่เลือกได้
# ฟอร์มได้ข้อมูลดิบไปคำนวณป้ายเอง (วันงานเปลี่ยนได้ตอนกรอก) ส่วนการล็อกจริงตัดสินที่นี่

# ฟอร์มมองย้อนหลัง/ไปข้างหน้ากี่วันเวลาดึงข้อมูลความว่าง — งานส่วนมากวางไม่เกินนี้
AVAIL_BACK_DAYS = 30
AVAIL_AHEAD_DAYS = 400


def fully_on_leave(conn, staff_ids: list[int], start: date, end: date) -> list[str]:
    """ชื่อคนที่ลา **ทุกวัน** ในช่วง [start, end] — คนพวกนี้เป็นผู้ปฏิบัติงานไม่ได้จริงๆ

    ลาแค่บางวันไม่เข้าข่าย (ผู้ใช้ยืนยัน §29: ทีมยังทำวันที่เหลือได้)
    """
    if not staff_ids:
        return []
    rows = fetchall(conn, _SELECT + " AND l.staff_id = ANY(%s) AND l.date_from <= %s "
                    "AND l.date_to >= %s" + _ORDER, (list(staff_ids), end, start))
    days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    covered: dict[int, set] = {}
    names: dict[int, str] = {}
    for l in rows:
        names[l["staff_id"]] = l["staff_name"]
        span = {l["date_from"] + timedelta(days=i)
                for i in range((l["date_to"] - l["date_from"]).days + 1)}
        covered.setdefault(l["staff_id"], set()).update(span & days)
    return [names[sid] for sid, got in covered.items() if got >= days]


def availability_data(conn, today: date | None = None) -> dict:
    """ข้อมูลดิบให้ฟอร์มกิจกรรมคำนวณป้าย ลา/ประจำจุด/มีงานอื่น ต่อคน ตามวันที่กรอก

    ส่งเป็นช่วง ISO ต่อคน (เล็กมาก) ให้ JS เทียบเอง — วันของงานเปลี่ยนได้ระหว่างกรอก
    จึงยิงกลับเซิร์ฟเวอร์ทุกครั้งไม่คุ้ม · การล็อกจริงยังตัดสินที่ `fully_on_leave()`
    """
    today = today or thaidate.today()
    since = today - timedelta(days=AVAIL_BACK_DAYS)
    until = today + timedelta(days=AVAIL_AHEAD_DAYS)

    leaves: dict[int, list] = {}
    for l in between(conn, since, until):
        leaves.setdefault(l["staff_id"], []).append({
            "from": l["date_from"].isoformat(), "to": l["date_to"].isoformat(),
            "part": l["part"]})

    duty: dict[int, list] = {}
    for a in assignments_between(conn, since, until):
        if not a.get("staff_active", True):
            continue
        duty.setdefault(a["staff_id"], []).append({
            "from": a["starts_on"].isoformat(),
            "to": a["ends_on"].isoformat() if a["ends_on"] else "9999-12-31",
            "post": a["post_name"]})

    # งานอื่นที่คนนั้นถูกมอบหมายอยู่ — ตัวโหลดเดียวกับที่แถบพนักงานใช้ตัดสิน "ว่าง"
    return {"leaves": leaves, "duty": duty,
            "busy": activities_by_staff(conn, since, until)}


def delete_assignment(conn, assignment_id: int, user: dict) -> None:
    execute(conn, "UPDATE duty_assignments SET is_deleted = TRUE, updated_at = NOW(), "
                  "updated_by = %s WHERE id = %s", (user["id"], assignment_id))
