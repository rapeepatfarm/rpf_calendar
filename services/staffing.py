"""services/staffing.py — นิยามเรื่องคน: ใครลา ใครมาทำงาน (v2 เฟส B)

ทุกหน้าที่ต้องรู้ว่า "วันนี้ใครลา / ใครว่าง" ต้องเรียกที่นี่ ห้ามเขียน query เอง
ไม่งั้นแต่ละหน้าจะนิยาม "ลา" ไม่ตรงกัน — บทเรียนเดียวกับที่ "งานค้าง" เคยนิยาม
ไม่ตรงกันสองที่แล้วป้ายบนจอกับตัวปิดอัตโนมัติเถียงกัน

เฟส C จะเพิ่ม "ประจำจุดงาน / ขาดคน" ลงไฟล์นี้ · เฟส D ใช้ `on_leave_ids()` กันเลือกคนลา
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
