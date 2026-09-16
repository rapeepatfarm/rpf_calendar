"""scripts/seed_master.py — ใส่ประเภทกิจกรรมตั้งต้น

รันได้ซ้ำโดยไม่เกิดของซ้ำ (ข้ามชื่อที่มีอยู่แล้ว) และไม่ทับค่าที่ผู้ใช้แก้ไปแล้ว
รัน: python scripts\\seed_master.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import execute, get_conn  # noqa: E402

# (ชื่อ, สี, ไอคอน, ความสำคัญตั้งต้น, นาทีตั้งต้น)
CATEGORIES = [
    ("ทำวัคซีน",            "#d92d20", "💉", 1, 180),
    ("ตรวจสุขภาพไก่",       "#c2790a", "🩺", 2, 60),
    ("ให้อาหาร",            "#1f9254", "🌾", 2, 90),
    ("เก็บไข่",             "#e0a800", "🥚", 2, 120),
    ("ชั่งน้ำหนัก",          "#7b5cd6", "⚖", 3, 90),
    ("ทำความสะอาดโรงเรือน",  "#0e9dab", "🧹", 3, 240),
    ("ซ่อมบำรุง",           "#5b6b82", "🔧", 2, 120),
    ("งานเอกสาร/บัญชี",     "#2f7de1", "📋", 4, 60),
    ("อื่นๆ",               "#8592a6", "•",  3, None),
]


def main():
    added = 0
    with get_conn() as conn:
        for order, (name, color, icon, priority, minutes) in enumerate(CATEGORIES, start=1):
            added += execute(conn, """
                INSERT INTO activity_categories
                    (name, color, icon, default_priority, default_duration_min, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO NOTHING
            """, (name, color, icon, priority, minutes, order))
    print(f"เพิ่มประเภทกิจกรรมใหม่ {added} รายการ "
          f"(ข้ามที่มีอยู่แล้ว {len(CATEGORIES) - added} รายการ)")


if __name__ == "__main__":
    main()
