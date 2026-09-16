"""ทะเบียน adapter ของแหล่งข้อมูล

ตอนเพิ่มแหล่งใหม่ ให้ import คลาสแล้วใส่ลง SOURCES โดยใช้ .code เป็นกุญแจ
แล้วเพิ่มแถวใน sync_sources พร้อม category_id ที่ต้องการให้งานตกลงไป
"""
from sync.sources.farm_activities import FarmActivitySource

SOURCES: dict = {
    FarmActivitySource.code: FarmActivitySource(),
}


# ชื่อโปรแกรมต้นทางแบบสั้น สำหรับแสดงบนหน้าจอ ("งานนี้ซิงค์มาจาก ...")
# กุญแจคือ .system ไม่ใช่ .code เพราะโปรแกรมเดียวอาจมี adapter หลายตัวในอนาคต
# เพิ่ม adapter ใหม่แล้วอย่าลืมเติมบรรทัดที่นี่ ไม่งั้นหน้าจอจะโชว์รหัสดิบให้ผู้ใช้เห็น
SYSTEM_LABELS: dict[str, str] = {
    "rpf_farm": "RPF Farm",
}


def get(code: str):
    return SOURCES.get(code)
