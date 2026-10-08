"""services/farm_link.py — ผูกกิจกรรมในปฏิทินกับฝูงไก่ใน RPF Farm

ใช้กับประเภทกิจกรรมที่ติ๊ก "ส่งไป RPF Farm" (activity_categories.farm_sync)
ฟอร์มกิจกรรมเลือกฝูง + วัคซีน/กิจกรรมจากทะเบียนฟาร์ม แล้วเก็บไว้ที่ตัวกิจกรรม
ฟาร์มเป็นฝ่ายมาดึงไปสร้างแผนเอง (rpf_farm/services/calendar_pull.pull_calendar_activities)

อ่านฟาร์มผ่าน get_farm_conn() ซึ่งเป็นบัญชี rpf_readonly — ไฟล์นี้ไม่เขียนลงฟาร์ม
"""
from database import fetchall, fetchone, get_farm_conn

KINDS = ("vaccine", "activity")


class FarmUnavailable(Exception):
    """ติดต่อฐานข้อมูลฟาร์มไม่ได้ — แยกออกมาให้ router บอกผู้ใช้ตรงๆ ไม่ใช่หน้า 500"""


def options() -> dict:
    """ตัวเลือกสำหรับฟอร์ม: ฝูงที่ยังเลี้ยงอยู่ + ทะเบียนวัคซีน + ทะเบียนกิจกรรม"""
    try:
        with get_farm_conn() as farm:
            flocks = fetchall(farm, """
                SELECT f.id, f.flock_code, f.breed,
                       CURRENT_DATE - f.start_date::date AS age_days,
                       COALESCE((
                         SELECT string_agg(h.name, ', ' ORDER BY h.name)
                           FROM flock_house_assignments a
                           JOIN chicken_houses h ON h.id = a.house_id
                          WHERE a.flock_id = f.id AND a.removed_date IS NULL
                       ), '') AS houses
                  FROM chicken_flocks f
                 WHERE f.active = 1
                 ORDER BY f.start_date DESC, f.flock_code
            """)
            vaccines = fetchall(farm, """
                SELECT id, name FROM vaccines WHERE active ORDER BY name
            """)
            types = fetchall(farm, """
                SELECT id, name FROM activity_types WHERE active ORDER BY sort_order, name
            """)
    except Exception as exc:
        raise FarmUnavailable(str(exc)) from exc
    return {"flocks": flocks, "vaccines": vaccines, "activity_types": types}


def parse_item(value: str | None) -> tuple[str | None, int | None]:
    """"vaccine:3" → ("vaccine", 3) · รูปแบบเดียวกับ dropdown ฝั่งฟาร์ม (_split_target)"""
    kind, _, raw = (value or "").partition(":")
    if kind not in KINDS or not raw.isdigit():
        return None, None
    return kind, int(raw)


def resolve(flock_id: int | None, kind: str | None, item_id: int | None) -> dict:
    """ตรวจกับฐานข้อมูลฟาร์มจริง แล้วคืนชุดฟิลด์ farm_* ที่พร้อมบันทึก

    ชื่อฝูง/ชื่อวัคซีนอ่านจากฟาร์มเสมอ ไม่เชื่อค่าที่ฟอร์มส่งมา
    โยน ValueError พร้อมข้อความไทยถ้าเลือกไม่ครบหรือไม่พบในฟาร์ม
    """
    if not flock_id:
        raise ValueError("ประเภทนี้ส่งไป RPF Farm ต้องเลือกฝูงไก่ก่อน — กด \"ดึงฝูงไก่ปัจจุบัน\"")
    if kind not in KINDS or not item_id:
        raise ValueError("ประเภทนี้ส่งไป RPF Farm ต้องเลือกวัคซีนหรือกิจกรรมจากทะเบียนฟาร์ม")

    table = "vaccines" if kind == "vaccine" else "activity_types"
    try:
        with get_farm_conn() as farm:
            # ไม่บังคับ active — งานเดิมที่ผูกกับฝูงซึ่งปลดไปแล้วต้องยังแก้ฟิลด์อื่นได้
            flock = fetchone(farm, "SELECT id, flock_code FROM chicken_flocks WHERE id = %s",
                             (flock_id,))
            item = fetchone(farm, f"SELECT id, name FROM {table} WHERE id = %s", (item_id,))
    except Exception as exc:
        raise FarmUnavailable(str(exc)) from exc

    if flock is None:
        raise ValueError("ไม่พบฝูงไก่นี้ใน RPF Farm แล้ว — เลือกฝูงใหม่")
    if item is None:
        raise ValueError("ไม่พบวัคซีน/กิจกรรมนี้ในทะเบียนของ RPF Farm แล้ว — เลือกใหม่")
    return {"farm_flock_id": flock["id"], "farm_flock_code": flock["flock_code"],
            "farm_kind": kind, "farm_item_id": item["id"], "farm_item_name": item["name"]}


EMPTY = {"farm_flock_id": None, "farm_flock_code": None, "farm_kind": None,
         "farm_item_id": None, "farm_item_name": None}


def category_syncs(conn, category_id: int | None) -> bool:
    if not category_id:
        return False
    row = fetchone(conn, "SELECT farm_sync FROM activity_categories WHERE id = %s",
                   (category_id,))
    return bool(row and row["farm_sync"])


def fill(conn, form, data: dict, existing: dict | None = None) -> str | None:
    """เติมฟิลด์ farm_* ลง data ตามประเภทที่เลือก — คืนข้อความไทยถ้ากรอกไม่ครบ

    ใช้ร่วมกันทั้งฟอร์มกิจกรรมและฟอร์มแผนงานประจำ (แผนประจำส่งต่อให้ทุกรอบที่สร้าง)

    - งานที่ซิงค์มาจากฟาร์มอยู่แล้ว (source_system) → คงค่าเดิม ไม่ส่งกลับ
      มันมีแผนในฟาร์มอยู่แล้ว ถ้าส่งอีกจะกลายเป็นแผนซ้ำสองแถว
    - ประเภทที่ไม่ได้ติ๊กส่ง → ล้างการผูกทิ้ง แล้วฟาร์มจะยกเลิกแผนที่เคยสร้างให้เองในรอบดึงถัดไป
    """
    if existing and existing.get("source_system"):
        data.update({k: existing.get(k) for k in EMPTY})
        return None
    if not category_syncs(conn, data["category_id"]):
        data.update(EMPTY)
        return None
    kind, item_id = parse_item(form.get("farm_item"))
    raw_flock = (form.get("farm_flock_id") or "").strip()
    try:
        data.update(resolve(int(raw_flock) if raw_flock.isdigit() else None, kind, item_id))
    except FarmUnavailable:
        return "ติดต่อฐานข้อมูล RPF Farm ไม่ได้ จึงตรวจฝูงไก่ไม่ได้ — ลองใหม่อีกครั้ง"
    except ValueError as exc:
        return str(exc)
    return None
