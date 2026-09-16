"""sync/sources/_example.py — แม่แบบสำหรับเขียน adapter ตัวจริง

ไฟล์นี้ไม่ถูกเรียกใช้ (ขึ้นต้นด้วย _ และไม่ได้ลงทะเบียนใน __init__.py)
มีไว้ให้คัดลอกตอนต่อแหล่งใหม่

แหล่งจริงตัวแรกคือ farm_activities.py (แผนกิจกรรมฝูงไก่จาก rpf_farm) ดูตัวนั้นประกอบ:
    flock_activity_plans — id, flock_id, house_id, vaccine_id, planned_date,
                          status (pending/done/skipped), is_deleted
    flock_activity_records — plan_id, actual_date  (ใช้ปิดงานเป็น done)
    vaccines            — id, name

ขั้นตอนตอนต่อจริง
  1. เพิ่ม <SRC>_DB_CONFIG + pool ใน config.py / database.py
     ใช้บัญชี PostgreSQL แบบ **read-only** (กติกาข้อ 4 — ปฏิทินไม่เขียนกลับ)
  2. คัดลอกไฟล์นี้แล้วเติม SQL จริง
  3. ลงทะเบียนใน sources/__init__.py
  4. เพิ่มแถวใน sync_sources พร้อม category_id ที่ต้องการให้งานตกลงไป
"""
from datetime import date

from sync.base import ExternalActivity


class ExampleSource:
    code = "example"
    name = "ตัวอย่าง (ไม่ใช้งานจริง)"
    system = "example"

    def fetch(self, config: dict, since: date) -> list[ExternalActivity]:
        # ── ของจริงจะหน้าตาประมาณนี้ ──────────────────────────
        #
        # with get_farm_conn() as farm:
        #     rows = fetchall(farm, """
        #         SELECT p.id, p.planned_date, p.status, p.note,
        #                v.name AS vaccine_name,
        #                f.flock_code, h.name AS house_name,
        #                r.actual_date
        #           FROM flock_activity_plans p
        #           JOIN vaccines v ON v.id = p.vaccine_id
        #           LEFT JOIN chicken_flocks f ON f.id = p.flock_id
        #           LEFT JOIN chicken_houses h ON h.id = p.house_id
        #           LEFT JOIN flock_activity_records r ON r.plan_id = p.id
        #          WHERE NOT p.is_deleted AND p.planned_date >= %s
        #     """, (since,))
        #
        # ต้องคืน "ทุกแถวที่ยังมีอยู่" ในช่วงนั้น ไม่ใช่เฉพาะที่เพิ่งเปลี่ยน
        # เพราะ runner ใช้ชุดนี้ตัดสินว่าอะไรถูกลบจากต้นทางไปแล้ว
        #
        # return [ExternalActivity(
        #     external_id=str(r["id"]),                 # ★ id ตัวเลข ไม่ใช่ชื่อ
        #     title=f"ทำวัคซีน {r['vaccine_name']} — {r['house_name'] or r['flock_code']}",
        #     planned_date=r["planned_date"],
        #     priority=1,                                # วัคซีนเลื่อนไม่ได้
        #     description=r["note"] or "",
        #     source_status="done" if r["actual_date"] else "pending",
        #     done_on=r["actual_date"],
        #     payload={"flock_code": r["flock_code"]},
        # ) for r in rows]
        return []
