"""routers/master.py — ข้อมูลหลัก: ประเภทกิจกรรม และผู้รับผิดชอบ"""
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from psycopg2 import errors

from auth import require_role
from database import execute, fetchall, get_conn
from forms import as_bool, as_int, as_priority, as_text
from view import page

router = APIRouter(prefix="/master")


def _back(url: str, ok: str = "", err: str = "") -> RedirectResponse:
    if ok:
        url += f"?ok={quote(ok)}"
    elif err:
        url += f"?err={quote(err)}"
    return RedirectResponse(url, status_code=303)


# ── ประเภทกิจกรรม ────────────────────────────────────────────

@router.get("/categories")
def categories_page(request: Request, ok: str = "", err: str = ""):
    user = require_role(request, "manager")
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT c.*,
                   (SELECT COUNT(*) FROM activities a
                     WHERE a.category_id = c.id AND NOT a.is_deleted) AS used_n
              FROM activity_categories c
             ORDER BY c.sort_order, c.name
        """)
        return page(request, user, "master_categories.html", conn=conn, rows=rows)


@router.post("/categories/save")
def save_category(request: Request,
                  id: str = Form(""), name: str = Form(...),
                  color: str = Form("#2f7de1"), icon: str = Form(""),
                  default_priority: str = Form("3"),
                  default_duration_min: str = Form(""),
                  sort_order: str = Form("0"), active: str = Form(""),
                  needs_start: str = Form("")):
    require_role(request, "manager")
    values = (as_text(name), as_text(color) or "#2f7de1", as_text(icon)[:4],
              as_priority(default_priority), as_int(default_duration_min),
              as_int(sort_order, 0), as_bool(active), as_bool(needs_start))
    if not values[0]:
        return _back("/master/categories", err="ต้องกรอกชื่อประเภท")

    try:
        with get_conn() as conn:
            if as_int(id):
                execute(conn, """
                    UPDATE activity_categories SET name = %s, color = %s, icon = %s,
                           default_priority = %s, default_duration_min = %s,
                           sort_order = %s, active = %s, needs_start = %s,
                           updated_at = NOW()
                     WHERE id = %s
                """, values + (as_int(id),))
            else:
                execute(conn, """
                    INSERT INTO activity_categories
                        (name, color, icon, default_priority, default_duration_min,
                         sort_order, active, needs_start)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, values)
    except errors.UniqueViolation:
        return _back("/master/categories", err=f"มีประเภทชื่อ \"{values[0]}\" อยู่แล้ว")
    return _back("/master/categories", ok="บันทึกประเภทกิจกรรมแล้ว")


@router.post("/categories/{category_id}/delete")
def delete_category(request: Request, category_id: int):
    """ประเภทที่เคยถูกใช้จะไม่ถูกลบ แต่ปิดการใช้งานแทน

    ถ้าลบทิ้งจริง กิจกรรมเก่าจะเสียประเภทไปตลอดกาลและรายงานย้อนหลังจะเพี้ยน
    """
    require_role(request, "manager")
    with get_conn() as conn:
        used = fetchall(conn, "SELECT COUNT(*) AS n FROM activities "
                              "WHERE category_id = %s AND NOT is_deleted", (category_id,))[0]["n"]
        if used:
            execute(conn, "UPDATE activity_categories SET active = FALSE WHERE id = %s",
                    (category_id,))
            return _back("/master/categories",
                         ok=f"ประเภทนี้ถูกใช้ใน {used} กิจกรรมแล้ว จึงปิดการใช้งานแทนการลบ")
        execute(conn, "DELETE FROM activity_categories WHERE id = %s", (category_id,))
    return _back("/master/categories", ok="ลบประเภทกิจกรรมแล้ว")


# ── ผู้รับผิดชอบ ─────────────────────────────────────────────

@router.get("/staff")
def staff_page(request: Request, ok: str = "", err: str = ""):
    user = require_role(request, "manager")
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT s.*, u.username, u.role AS user_role,
                   (SELECT COUNT(*) FROM activities a
                     WHERE a.assignee_id = s.id AND NOT a.is_deleted
                       AND a.status IN ('planned', 'in_progress')) AS open_n
              FROM staff s
              LEFT JOIN users u ON u.id = s.user_id
             ORDER BY s.sort_order, s.name
        """)
        # บัญชีที่ยังไม่ถูกผูกกับใคร — ผูกได้คนละหนึ่งบัญชีเท่านั้น
        free_users = fetchall(conn, """
            SELECT u.id, u.username, u.display_name, u.role
              FROM users u
             WHERE u.active AND NOT EXISTS (SELECT 1 FROM staff s WHERE s.user_id = u.id)
             ORDER BY u.username
        """)
        return page(request, user, "master_staff.html", conn=conn,
                    rows=rows, free_users=free_users)


@router.post("/staff/save")
def save_staff(request: Request,
               id: str = Form(""), name: str = Form(...),
               position: str = Form(""), phone: str = Form(""),
               color: str = Form("#2f7de1"), user_id: str = Form(""),
               sort_order: str = Form("0"), active: str = Form(""),
               note: str = Form("")):
    require_role(request, "manager")
    values = (as_text(name), as_text(position), as_text(phone),
              as_text(color) or "#2f7de1", as_int(user_id),
              as_int(sort_order, 0), as_bool(active), as_text(note))
    if not values[0]:
        return _back("/master/staff", err="ต้องกรอกชื่อผู้รับผิดชอบ")

    try:
        with get_conn() as conn:
            if as_int(id):
                execute(conn, """
                    UPDATE staff SET name = %s, position = %s, phone = %s, color = %s,
                           user_id = %s, sort_order = %s, active = %s, note = %s,
                           updated_at = NOW()
                     WHERE id = %s
                """, values + (as_int(id),))
            else:
                execute(conn, """
                    INSERT INTO staff (name, position, phone, color, user_id,
                                       sort_order, active, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, values)
    except errors.UniqueViolation:
        return _back("/master/staff", err="บัญชีผู้ใช้นี้ถูกผูกกับผู้รับผิดชอบคนอื่นไปแล้ว")
    return _back("/master/staff", ok="บันทึกข้อมูลผู้รับผิดชอบแล้ว")


@router.post("/staff/{staff_id}/delete")
def delete_staff(request: Request, staff_id: int):
    """คนที่เคยมีงานจะไม่ถูกลบ แต่ปิดการใช้งานแทน เพื่อไม่ให้งานเก่าเสียชื่อเจ้าของ"""
    require_role(request, "manager")
    with get_conn() as conn:
        used = fetchall(conn, "SELECT COUNT(*) AS n FROM activities "
                              "WHERE assignee_id = %s AND NOT is_deleted", (staff_id,))[0]["n"]
        if used:
            execute(conn, "UPDATE staff SET active = FALSE WHERE id = %s", (staff_id,))
            return _back("/master/staff",
                         ok=f"คนนี้มีงานในระบบ {used} รายการ จึงปิดการใช้งานแทนการลบ")
        execute(conn, "DELETE FROM staff WHERE id = %s", (staff_id,))
    return _back("/master/staff", ok="ลบผู้รับผิดชอบแล้ว")
