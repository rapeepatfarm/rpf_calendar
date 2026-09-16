"""routers/users.py — จัดการบัญชีผู้ใช้ (เฉพาะผู้ดูแลระบบ)"""
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from psycopg2 import errors

from auth import (ROLES, count_active_admins, hash_password, password_problem,
                  require_admin)
from database import execute, fetchall, get_conn, fetchone
from forms import as_bool, as_int, as_text
from view import page

router = APIRouter(prefix="/settings/users")
URL = "/settings/users"


def _back(ok: str = "", err: str = "") -> RedirectResponse:
    url = URL
    if ok:
        url += f"?ok={quote(ok)}"
    elif err:
        url += f"?err={quote(err)}"
    return RedirectResponse(url, status_code=303)


@router.get("")
def users_page(request: Request, ok: str = "", err: str = ""):
    user = require_admin(request)
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT u.id, u.username, u.display_name, u.role, u.active, u.created_at,
                   s.name AS staff_name
              FROM users u
              LEFT JOIN staff s ON s.user_id = u.id
             ORDER BY u.active DESC, u.username
        """)
        return page(request, user, "settings_users.html", conn=conn, rows=rows, roles=ROLES)


@router.post("/create")
def create_user(request: Request,
                username: str = Form(...), password: str = Form(...),
                display_name: str = Form(""), role: str = Form("viewer")):
    require_admin(request)
    username = as_text(username).lower()
    if not username:
        return _back(err="ต้องกรอกชื่อผู้ใช้")
    if role not in ROLES:
        return _back(err="สิทธิ์ที่เลือกไม่ถูกต้อง")
    problem = password_problem(password)
    if problem:
        return _back(err=problem)

    try:
        with get_conn() as conn:
            # must_change_password = TRUE เสมอ — รหัสที่ผู้ดูแลตั้งให้ถือเป็นรหัสชั่วคราว
            execute(conn, """
                INSERT INTO users (username, password_hash, display_name, role,
                                   must_change_password)
                VALUES (%s, %s, %s, %s, TRUE)
            """, (username, hash_password(password), as_text(display_name), role))
    except errors.UniqueViolation:
        return _back(err=f"มีชื่อผู้ใช้ \"{username}\" อยู่แล้ว")
    return _back(ok=f"สร้างบัญชี {username} แล้ว — อย่าลืมผูกกับทะเบียนพนักงาน")


@router.post("/{user_id}/update")
def update_user(request: Request, user_id: int,
                display_name: str = Form(""), role: str = Form("viewer"),
                active: str = Form("")):
    me = require_admin(request)
    if role not in ROLES:
        return _back(err="สิทธิ์ที่เลือกไม่ถูกต้อง")
    is_active = as_bool(active)

    with get_conn() as conn:
        target = fetchone(conn, "SELECT * FROM users WHERE id = %s", (user_id,))
        if target is None:
            return _back(err="ไม่พบบัญชีนี้")

        # กันไม่ให้ผู้ดูแลระบบคนสุดท้ายถูกลดสิทธิ์หรือปิดบัญชี จนไม่มีใครเข้าไปแก้ได้อีก
        losing_admin = target["role"] == "admin" and (role != "admin" or not is_active)
        if losing_admin and count_active_admins(conn, exclude_id=user_id) == 0:
            return _back(err="นี่คือผู้ดูแลระบบคนสุดท้าย เปลี่ยนสิทธิ์หรือปิดบัญชีไม่ได้")

        execute(conn, """
            UPDATE users SET display_name = %s, role = %s, active = %s WHERE id = %s
        """, (as_text(display_name), role, is_active, user_id))

    note = " (คุณเปลี่ยนสิทธิ์ของบัญชีตัวเอง)" if user_id == me["id"] else ""
    return _back(ok=f"บันทึกบัญชี {target['username']} แล้ว{note}")


@router.post("/{user_id}/password")
def reset_password(request: Request, user_id: int, password: str = Form(...)):
    require_admin(request)
    problem = password_problem(password)
    if problem:
        return _back(err=problem)
    with get_conn() as conn:
        execute(conn, """
            UPDATE users SET password_hash = %s, must_change_password = TRUE WHERE id = %s
        """, (hash_password(password), user_id))
    return _back(ok="ตั้งรหัสผ่านใหม่แล้ว — ระบบจะบังคับให้เจ้าของบัญชีตั้งรหัสของตัวเอง"
                    "ตอนล็อกอินครั้งถัดไป")


@router.post("/{user_id}/delete")
def delete_user(request: Request, user_id: int):
    """ลบบัญชี — ทะเบียนพนักงานที่ผูกไว้ยังอยู่ (FK เป็น ON DELETE SET NULL)"""
    me = require_admin(request)
    if user_id == me["id"]:
        return _back(err="ลบบัญชีของตัวเองไม่ได้")
    with get_conn() as conn:
        target = fetchone(conn, "SELECT username, role FROM users WHERE id = %s", (user_id,))
        if target is None:
            return _back(err="ไม่พบบัญชีนี้")
        if target["role"] == "admin" and count_active_admins(conn, exclude_id=user_id) == 0:
            return _back(err="นี่คือผู้ดูแลระบบคนสุดท้าย ลบไม่ได้")

        # กิจกรรมอ้าง users ผ่าน created_by/started_by/finished_by ที่ไม่มี ON DELETE
        # จึงต้องตัดการอ้างอิงก่อน ไม่งั้นลบไม่ผ่านและประวัติจะพังถ้าลบตาม
        for column in ("created_by", "updated_by", "started_by", "finished_by"):
            execute(conn, f"UPDATE activities SET {column} = NULL WHERE {column} = %s", (user_id,))
        execute(conn, "UPDATE activity_log SET by_user_id = NULL WHERE by_user_id = %s", (user_id,))
        execute(conn, "DELETE FROM users WHERE id = %s", (user_id,))
    return _back(ok=f"ลบบัญชี {target['username']} แล้ว")
