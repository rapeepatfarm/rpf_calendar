"""auth.py — ล็อกอินด้วย bcrypt + session และสิทธิ์ 4 ระดับ"""
import bcrypt
from fastapi import HTTPException, Request

from database import fetchone, get_conn

ROLES = ("admin", "manager", "worker", "viewer")
ROLE_LABELS = {
    "admin": "ผู้ดูแลระบบ — ทำได้ทุกอย่าง รวมถึงจัดการผู้ใช้และการเชื่อมต่อ",
    "manager": "หัวหน้างาน — วางแผน แก้ไข ยกเลิกงานได้ทุกงาน และแก้ข้อมูลหลัก",
    "worker": "พนักงาน — กดเริ่ม/สิ้นสุดได้เฉพาะงานที่ตัวเองรับผิดชอบ",
    "viewer": "ผู้ดูอย่างเดียว — ดูปฏิทินและรายงานได้ แก้ไขไม่ได้",
}
MIN_PASSWORD_LENGTH = 8

# หน้าที่ยังเข้าได้ทั้งที่ยังไม่ได้เปลี่ยนรหัส — ต้องมีอย่างน้อยหน้าเปลี่ยนรหัส
# กับทางออกจากระบบ ไม่งั้นผู้ใช้จะติดอยู่ในวงวนไม่มีทางออก
PASSWORD_CHANGE_EXEMPT = ("/account", "/logout", "/login", "/static")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def _load_user(conn, where: str, param) -> dict | None:
    """โหลดผู้ใช้พร้อมชื่อในทะเบียนพนักงานที่ผูกไว้

    staff_id ติดมาด้วยเสมอเพราะทุกหน้าต้องใช้ตัดสินว่า "งานนี้ของฉันไหม"
    """
    return fetchone(conn, f"""
        SELECT u.*, s.id AS staff_id, s.name AS staff_name
          FROM users u
          LEFT JOIN staff s ON s.user_id = u.id AND s.active
         WHERE {where} AND u.active
    """, (param,))


def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        return _load_user(conn, "u.username = %s", username)


def authenticate(username: str, password: str) -> dict | None:
    user = get_user_by_username(username)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


def get_current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with get_conn() as conn:
        return _load_user(conn, "u.id = %s", user_id)


def require_login(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # ผู้ดูแลระบบตั้งรหัสให้แล้วยังไม่เคยเปลี่ยน — ต้องเปลี่ยนก่อนถึงจะใช้หน้าอื่นได้
    # ตรวจที่นี่ที่เดียวเพราะทุกหน้าเรียกผ่านฟังก์ชันนี้ ไม่มีทางลืมหน้าใดหน้าหนึ่ง
    if user.get("must_change_password") and not request.url.path.startswith(
            PASSWORD_CHANGE_EXEMPT):
        raise HTTPException(status_code=303, headers={"Location": "/account?force=1"})
    return user


def require_role(request: Request, *roles: str) -> dict:
    user = require_login(request)
    if user["role"] == "admin" or user["role"] in roles:
        return user
    raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงหน้านี้")


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="หน้านี้สำหรับผู้ดูแลระบบเท่านั้น")
    return user


def can_manage(user: dict) -> bool:
    """แก้ข้อมูลหลักและวางแผนงานให้คนอื่นได้ไหม"""
    return user["role"] in ("admin", "manager")


def can_create(user: dict) -> bool:
    """สร้างกิจกรรมได้ไหม — พนักงานสร้างงานของตัวเองได้"""
    return user["role"] in ("admin", "manager", "worker")


def owns_activity(user: dict, activity: dict) -> bool:
    """งานนี้เป็นของผู้ใช้คนนี้ไหม — เป็นผู้รับผิดชอบหลักหรือผู้ช่วยก็นับ

    ผู้ใช้ที่ไม่ได้ผูก staff ไว้ (staff_id = None) ต้องไม่ถือว่าเป็นเจ้าของ
    งานที่ยังไม่ระบุผู้รับผิดชอบ (assignee_id = None) ไม่งั้น None == None
    จะกลายเป็นว่าทุกคนเป็นเจ้าของงานที่ยังไม่มอบหมาย

    helper_ids มาจาก activities.attach_helpers() — ถ้าผู้เรียกไม่ได้เติมมา
    จะถือว่าไม่มีผู้ช่วย (ปลอดภัยกว่าการเดาว่ามี)
    """
    staff_id = user.get("staff_id")
    if staff_id is None:
        return False
    return (activity.get("assignee_id") == staff_id
            or staff_id in (activity.get("helper_ids") or []))


def can_run_activity(user: dict, activity: dict) -> bool:
    """กดเริ่ม/สิ้นสุดงานนี้ได้ไหม"""
    if user["role"] in ("admin", "manager"):
        return True
    return user["role"] == "worker" and owns_activity(user, activity)


def can_edit_activity(user: dict, activity: dict) -> bool:
    """แก้ไข/ยกเลิกงานนี้ได้ไหม

    พนักงานแก้ได้เฉพาะงานที่ตัวเองสร้างและยังไม่มีใครเริ่มทำ — พองานเริ่มแล้ว
    การแก้แผนย้อนหลังจะทำให้รายงาน "ทำตรงแผนไหม" เชื่อถือไม่ได้
    """
    if user["role"] in ("admin", "manager"):
        return True
    if user["role"] != "worker":
        return False
    return activity.get("created_by") == user["id"] and activity.get("status") == "planned"


def password_problem(password: str) -> str | None:
    """คืนข้อความบอกปัญหาถ้ารหัสผ่านใช้ไม่ได้ หรือ None ถ้าผ่าน"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร"
    if password.strip() != password:
        return "รหัสผ่านต้องไม่ขึ้นต้นหรือลงท้ายด้วยช่องว่าง"
    return None


def count_active_admins(conn, exclude_id: int | None = None) -> int:
    """นับผู้ดูแลระบบที่ยังใช้งานอยู่ — กันไม่ให้เหลือ admin ศูนย์คนจนล็อกตัวเองออก"""
    sql = "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active"
    params: tuple = ()
    if exclude_id is not None:
        sql += " AND id <> %s"
        params = (exclude_id,)
    return fetchone(conn, sql, params)["n"]
