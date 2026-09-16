"""sync/sources/farm_activities.py — ดึงแผนกิจกรรมฝูงไก่จาก RPF Farm

ครอบทั้งวัคซีนและกิจกรรมอื่น (ย้ายไก่ · ชั่งน้ำหนัก · คัดเกรด) เพราะฝั่งฟาร์ม
วางแผนทุกอย่างด้วยหน่วยเดียวกันคือ "อายุไก่กี่วัน" (กรอกเป็นสัปดาห์ก็ได้)
และระบุได้ว่ากิจกรรมกินเวลากี่วัน — ส่งเป็นงานหลายวันให้ปฏิทินตามกติกาข้อ 6

ฝั่งฟาร์มคำนวณวันนัดไว้แล้วในตาราง flock_activity_plans
ที่นี่แค่อ่านออกมาแปลงเป็น ExternalActivity ไม่คำนวณวันเอง
ถ้าคำนวณซ้ำที่นี่ วันจะเพี้ยนทันทีที่สูตรสองฝั่งไม่ตรงกัน

external_id = flock_activity_plans.id (เลขนิ่ง ไม่ใช่ชื่อวัคซีน/ชื่อฝูง) ตามกติกาข้อ 1

เปลี่ยนโปรแกรมกลางคันแล้วเกิดอะไรขึ้น
    ฝั่งฟาร์ม  แผนอนาคตของโปรแกรมเก่าถูกตั้ง is_deleted = TRUE
    ที่นี่      แถวนั้นหลุดจากผลลัพธ์ fetch()
    runner     ไม่เห็น external_id นั้นในรอบนี้ จึงปิดกิจกรรมเป็น cancelled ให้เอง
ไม่ต้องเขียนโค้ดลบอะไรเพิ่ม — กติกาข้อ 2 ใน runner.py จัดการให้ครบแล้ว
"""
from datetime import date

from database import fetchall, get_farm_conn
from sync.base import ExternalActivity


def _age_text(r: dict) -> str:
    """อายุไก่ตอนถึงกำหนด — พูดหน่วยเดียวกับที่ผู้ใช้กรอกไว้ฝั่งฟาร์ม

    คนอ่านงานในปฏิทินคือคนเดียวกับที่วางแผนในฟาร์ม ถ้าสองที่พูดคนละหน่วย
    (ฟาร์มบอกสัปดาห์ 3 ปฏิทินบอกวันที่ 21) จะต้องแปลงในหัวทุกครั้ง
    """
    if r["unit"] == "week" and r["age_day"] % 7 == 0:
        return f"อายุสัปดาห์ที่ {r['age_day'] // 7}"
    return f"อายุวันที่ {r['age_day']}"


class FarmActivitySource:
    code = "farm_activities"
    name = "แผนกิจกรรมฝูงไก่จาก RPF Farm"
    system = "rpf_farm"

    def fetch(self, config: dict, since: date) -> list[ExternalActivity]:
        with get_farm_conn() as farm:
            rows = fetchall(farm, """
                SELECT p.id, p.planned_date, p.age_day, p.unit, p.duration_days,
                       p.planned_date + (p.duration_days - 1) AS end_date,
                       p.status, p.note, p.route, p.kind,
                       COALESCE(v.name, at.name) AS item_name,
                       f.flock_code,
                       r.actual_date,
                       COALESCE((
                         SELECT string_agg(h.name, ', ' ORDER BY h.name)
                           FROM flock_house_assignments a
                           JOIN chicken_houses h ON h.id = a.house_id
                          WHERE a.flock_id = p.flock_id AND a.removed_date IS NULL
                       ), '') AS houses
                  FROM flock_activity_plans p
                  JOIN chicken_flocks f       ON f.id  = p.flock_id
                  LEFT JOIN vaccines v        ON v.id  = p.vaccine_id
                  LEFT JOIN activity_types at ON at.id = p.activity_type_id
                  LEFT JOIN flock_activity_records r ON r.plan_id = p.id
                 WHERE NOT p.is_deleted
                   -- คาบเกี่ยวช่วง ไม่ใช่ planned_date >= since เฉยๆ
                   -- งานหลายวันที่เริ่มก่อน since แต่ยังทำอยู่ ต้องคืนมาด้วย
                   -- ไม่งั้น runner จะไม่เห็นแล้วปิดเป็น cancelled ทั้งที่ยังทำค้างอยู่
                   AND p.planned_date + (p.duration_days - 1) >= %s
                 ORDER BY p.planned_date, f.flock_code
            """, (since,))

        return [self._to_activity(r) for r in rows]

    @staticmethod
    def _to_activity(r: dict) -> ExternalActivity:
        where = r["houses"] or f"ฝูง {r['flock_code']}"
        # วัคซีนเติมคำนำหน้าให้ชัดว่าเป็นการทำวัคซีน ส่วนกิจกรรมอื่นชื่อมันบอกตัวเองอยู่แล้ว
        # ("ย้ายไก่ — A8" อ่านรู้เรื่องกว่า "ทำย้ายไก่ — A8")
        label = f"ทำวัคซีน {r['item_name']}" if r["kind"] == "vaccine" else r["item_name"]
        title = f"{label} — {where}"

        detail = [f"ฝูง {r['flock_code']} · {_age_text(r)}"]
        if r["houses"]:
            detail.append(f"โรงเรือน {r['houses']}")
        if r["route"]:
            detail.append(f"วิธีให้ {r['route']}" if r["kind"] == "vaccine" else r["route"])
        if r["note"]:
            detail.append(r["note"])

        return ExternalActivity(
            external_id=str(r["id"]),
            title=title,
            planned_date=r["planned_date"],
            end_date=r["end_date"],
            # วัคซีนเลื่อนไม่ได้ตามใจ ช้าไปสัปดาห์เดียวภูมิคุ้มกันก็ไม่ทันโรค
            # กิจกรรมอื่นยืดหยุ่นกว่า จึงไม่ต้องเร่งเท่ากัน
            priority=1 if r["kind"] == "vaccine" else 2,
            description="\n".join(detail),
            source_status="done" if r["actual_date"] else "pending",
            done_on=r["actual_date"],
            payload={"flock_code": r["flock_code"], "age_day": r["age_day"],
                     "kind": r["kind"], "duration_days": r["duration_days"]},
        )
