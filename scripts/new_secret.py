"""scripts/new_secret.py — สร้าง SESSION_SECRET ใหม่สำหรับใส่ใน .env

รัน: python scripts\\new_secret.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import generate_secret  # noqa: E402

print("คัดลอกบรรทัดนี้ไปวางใน .env แล้วรีสตาร์ทโปรแกรม:\n")
print(f"SESSION_SECRET={generate_secret()}")
