"""scripts/create_user.py — สร้างบัญชีผู้ใช้จากบรรทัดคำสั่ง

ใช้ตอนตั้งระบบครั้งแรก (ยังไม่มี admin ให้ล็อกอินเข้าไปสร้างในหน้าเว็บ)
หรือตอนกู้บัญชีผู้ดูแลระบบที่ถูกล็อกออก

รัน:
  python scripts\\create_user.py --username admin --role admin --display-name "ผู้ดูแลระบบ"
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import ROLES, hash_password, password_problem  # noqa: E402
from database import execute, fetchone, get_conn  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="สร้างหรือแก้ไขบัญชีผู้ใช้ RPF Calendar")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="viewer", choices=ROLES)
    parser.add_argument("--display-name", default="")
    parser.add_argument("--password", help="ถ้าไม่ใส่ จะถามตอนรัน (ปลอดภัยกว่า)")
    args = parser.parse_args()

    password = args.password or getpass.getpass("รหัสผ่าน: ")
    problem = password_problem(password)
    if problem:
        sys.exit(f"ไม่ผ่าน: {problem}")

    with get_conn() as conn:
        existing = fetchone(conn, "SELECT id FROM users WHERE username = %s", (args.username,))
        if existing:
            execute(conn, """
                UPDATE users SET password_hash = %s, role = %s, active = TRUE,
                       must_change_password = TRUE,
                       display_name = COALESCE(NULLIF(%s, ''), display_name)
                 WHERE id = %s
            """, (hash_password(password), args.role, args.display_name, existing["id"]))
            print(f"อัปเดตบัญชี {args.username} (สิทธิ์ {args.role}) เรียบร้อย")
            print("ระบบจะบังคับให้ตั้งรหัสใหม่ตอนล็อกอินครั้งถัดไป")
            return

        execute(conn, """
            INSERT INTO users (username, password_hash, display_name, role,
                               must_change_password)
            VALUES (%s, %s, %s, %s, TRUE)
        """, (args.username, hash_password(password), args.display_name, args.role))
    print(f"สร้างบัญชี {args.username} (สิทธิ์ {args.role}) เรียบร้อย")
    print("ระบบจะบังคับให้ตั้งรหัสของตัวเองตอนล็อกอินครั้งแรก")


if __name__ == "__main__":
    main()
