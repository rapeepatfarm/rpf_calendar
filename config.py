"""config.py — การตั้งค่าโปรแกรม RPF Calendar"""
import os
import secrets
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_CONFIG = {
    "host": os.environ.get("PG_HOST", "127.0.0.1"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DBNAME", "rpf_calendar"),
    "user": os.environ.get("PG_USER", "postgres"),
    "password": os.environ.get("PG_PASSWORD", ""),
}

# rpf_farm DB — ต้นทางของแผนกิจกรรมฝูงไก่ (sync/sources/farm_activities.py)
#
# บัญชี rpf_readonly มีสิทธิ์ SELECT อย่างเดียว ตามกติกาข้อ 4 ใน sync/runner.py
# ปฏิทินอ่านต้นทางเท่านั้น ไม่เขียนกลับ — บังคับที่ระดับ PostgreSQL ไม่ใช่แค่ในโค้ด
FARM_DB_CONFIG = {
    "host": os.environ.get("FARM_PG_HOST", "127.0.0.1"),
    "port": int(os.environ.get("FARM_PG_PORT", "5432")),
    "dbname": os.environ.get("FARM_PG_DBNAME", "rpf_farm"),
    "user": os.environ.get("FARM_PG_USER", "rpf_readonly"),
    "password": os.environ.get("FARM_PG_PASSWORD", ""),
}

APP_PORT = int(os.environ.get("APP_PORT", "8200"))
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

# แผนงานฟาร์มเป็นเรื่อง "วันที่ตามปฏิทินไทย" ไม่ใช่จุดเวลาสัมบูรณ์
# ถ้าปล่อยให้ใช้เวลาเครื่อง วันจะเพี้ยนได้ 1 วันเมื่อเซิร์ฟเวอร์ตั้ง timezone อื่น
#
# ไทยใช้ UTC+7 คงที่ ไม่มี DST จึงเขียนเป็น offset ตรงๆ ได้
# (แบบเดียวกับ rpf_power) ไม่ต้องพึ่ง ZoneInfo ซึ่งบน Windows ต้องลง tzdata เพิ่ม
THAI_TZ = timezone(timedelta(hours=7))

# เปิดให้เข้าจากนอกสถานที่หรือไม่ — ตั้ง ONLINE=1 ใน .env เมื่อต่อผ่าน Tailscale/tunnel
# เมื่อเปิดโหมดนี้ อายุ session จะสั้นลง และบังคับให้ SESSION_SECRET ต้องแข็งแรงจริง
ONLINE = os.environ.get("ONLINE", "0") == "1"

# บังคับให้ cookie เดินทางเฉพาะบน HTTPS หรือไม่ — ดูเหตุผลใน docs/online-access.md
# Tailscale ธรรมดาใช้ http จึงต้องปิดไว้ ไม่งั้นล็อกอินไม่ได้
SESSION_HTTPS_ONLY = os.environ.get("SESSION_HTTPS_ONLY", "0") == "1"

SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", "43200" if ONLINE else "1209600"))

# วางแผนงานประจำล่วงหน้ากี่เดือน (ใช้ในเฟส 3) — ค่าใน settings ของ DB ทับค่านี้ได้
PLAN_HORIZON_MONTHS = int(os.environ.get("PLAN_HORIZON_MONTHS", "12"))

# ค่าที่เคยแจกมากับโปรเจกต์ — ห้ามใช้จริงเด็ดขาด เพราะใครก็ตามที่รู้ค่านี้
# สามารถปลอม session cookie เข้าเป็นผู้ดูแลระบบได้โดยไม่ต้องรู้รหัสผ่าน
WEAK_SECRETS = {"", "dev-only-secret", "change-me-before-production", "secret", "changeme"}


def check_session_secret() -> str | None:
    """คืนข้อความเตือนถ้า SESSION_SECRET ยังอ่อนแอ หรือ None ถ้าปลอดภัยดี"""
    if SESSION_SECRET in WEAK_SECRETS or len(SESSION_SECRET) < 32:
        return ("SESSION_SECRET ยังเป็นค่าเริ่มต้นหรือสั้นเกินไป — "
                "ใครที่รู้ค่านี้จะปลอม session เข้าเป็นผู้ดูแลระบบได้ "
                "สร้างค่าใหม่ด้วย: python scripts\\new_secret.py")
    return None


def generate_secret() -> str:
    return secrets.token_urlsafe(48)
