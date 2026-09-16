"""routers/master.py — ข้อมูลหลัก: ประเภทกิจกรรม · พนักงาน · ฝ่าย"""
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from psycopg2 import errors

from auth import require_role
from database import execute, fetchall, get_conn
from forms import OptInt, as_bool, as_int, as_priority, as_text
from view import page

router = APIRouter(prefix="/master")


def _back(url: str, ok: str = "", err: str = "", keep: dict | None = None) -> RedirectResponse:
    """เด้งกลับหน้ารายการพร้อมข้อความ · `keep` = ตัวกรองที่ต้องคงไว้หลังบันทึก

    ถ้าไม่คงตัวกรอง คนที่กรองดู "ฝ่ายเลี้ยงไก่" อยู่ แก้คนหนึ่งเสร็จจะเด้งกลับไป
    เห็นทุกฝ่ายรวมกัน แล้วต้องกรองใหม่ทุกครั้ง
    """
    params = {k: v for k, v in (keep or {}).items() if v not in (None, "")}
    if ok:
        params["ok"] = ok
    elif err:
        params["err"] = err
    if params:
        url += "?" + urlencode(params, quote_via=quote)
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


# ── พนักงาน ──────────────────────────────────────────────────
# ตาราง staff เดิม (เคยเรียกว่า "ผู้รับผิดชอบ") — v2 ขยายเป็นทะเบียนพนักงานทั้งฟาร์ม
# มีรหัส ฝ่าย ตำแหน่ง · คำว่า "ผู้รับผิดชอบ" ยังใช้กับ *ช่อง* ในกิจกรรมเหมือนเดิม

def _staff_filters(department_id: OptInt, position: str) -> dict:
    return {"department_id": department_id, "position": as_text(position)}


@router.get("/staff")
def staff_page(request: Request, ok: str = "", err: str = "",
               department_id: OptInt = None, position: str = ""):
    user = require_role(request, "manager")
    f = _staff_filters(department_id, position)

    where, params = [], []
    if f["department_id"]:
        where.append("s.department_id = %s")
        params.append(f["department_id"])
    if f["position"]:
        where.append("s.position = %s")
        params.append(f["position"])

    with get_conn() as conn:
        rows = fetchall(conn, f"""
            SELECT s.*, u.username, u.role AS user_role, d.name AS department_name,
                   (SELECT COUNT(*) FROM activities a
                     WHERE a.assignee_id = s.id AND NOT a.is_deleted
                       AND a.status IN ('planned', 'in_progress')) AS open_n
              FROM staff s
              LEFT JOIN users u ON u.id = s.user_id
              LEFT JOIN departments d ON d.id = s.department_id
             {'WHERE ' + ' AND '.join(where) if where else ''}
             ORDER BY d.sort_order NULLS LAST, d.name, s.sort_order, s.name
        """, params)
        # บัญชีที่ยังไม่ถูกผูกกับใคร — ผูกได้คนละหนึ่งบัญชีเท่านั้น
        free_users = fetchall(conn, """
            SELECT u.id, u.username, u.display_name, u.role
              FROM users u
             WHERE u.active AND NOT EXISTS (SELECT 1 FROM staff s WHERE s.user_id = u.id)
             ORDER BY u.username
        """)
        departments = fetchall(conn, "SELECT id, name, active FROM departments "
                                     "ORDER BY sort_order, name")
        # ตำแหน่งยังเป็นข้อความอิสระ ตัวกรองจึงดึงจากค่าที่มีคนกรอกไว้จริง
        positions = [r["position"] for r in fetchall(conn, """
            SELECT DISTINCT position FROM staff WHERE position <> '' ORDER BY position
        """)]
        # ส่งตัวกรองเป็น `flt` ไม่ใช่ `f` — ในเทมเพลต `f` เป็นฟอร์มของ Alpine อยู่แล้ว
        return page(request, user, "master_staff.html", conn=conn,
                    rows=rows, free_users=free_users, departments=departments,
                    positions=positions, flt=f,
                    total_n=fetchall(conn, "SELECT COUNT(*) AS n FROM staff")[0]["n"])


@router.post("/staff/save")
def save_staff(request: Request,
               id: str = Form(""), name: str = Form(...),
               code: str = Form(""), department_id: str = Form(""),
               position: str = Form(""), phone: str = Form(""),
               color: str = Form("#2f7de1"), user_id: str = Form(""),
               sort_order: str = Form("0"), active: str = Form(""),
               note: str = Form(""),
               f_department_id: str = Form(""), f_position: str = Form("")):
    require_role(request, "manager")
    keep = {"department_id": f_department_id, "position": f_position}
    values = (as_text(name), as_text(code).upper(), as_int(department_id),
              as_text(position), as_text(phone),
              as_text(color) or "#2f7de1", as_int(user_id),
              as_int(sort_order, 0), as_bool(active), as_text(note))
    if not values[0]:
        return _back("/master/staff", err="ต้องกรอกชื่อพนักงาน", keep=keep)

    try:
        with get_conn() as conn:
            if as_int(id):
                execute(conn, """
                    UPDATE staff SET name = %s, code = %s, department_id = %s,
                           position = %s, phone = %s, color = %s,
                           user_id = %s, sort_order = %s, active = %s, note = %s,
                           updated_at = NOW()
                     WHERE id = %s
                """, values + (as_int(id),))
            else:
                execute(conn, """
                    INSERT INTO staff (name, code, department_id, position, phone, color,
                                       user_id, sort_order, active, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, values)
    except errors.UniqueViolation as e:
        # มี unique สองตัวบนตารางนี้ ต้องบอกให้ถูกว่าชนตัวไหน
        if (e.diag.constraint_name or "") == "staff_code_uq":
            return _back("/master/staff", keep=keep,
                         err=f"รหัสพนักงาน \"{values[1]}\" มีคนใช้อยู่แล้ว")
        return _back("/master/staff", keep=keep,
                     err="บัญชีผู้ใช้นี้ถูกผูกกับพนักงานคนอื่นไปแล้ว")
    return _back("/master/staff", ok="บันทึกข้อมูลพนักงานแล้ว", keep=keep)


@router.post("/staff/{staff_id}/delete")
def delete_staff(request: Request, staff_id: int,
                 f_department_id: str = Form(""), f_position: str = Form("")):
    """คนที่เคยมีงานจะไม่ถูกลบ แต่ปิดการใช้งานแทน เพื่อไม่ให้งานเก่าเสียชื่อเจ้าของ"""
    require_role(request, "manager")
    keep = {"department_id": f_department_id, "position": f_position}
    with get_conn() as conn:
        used = fetchall(conn, "SELECT COUNT(*) AS n FROM activities "
                              "WHERE assignee_id = %s AND NOT is_deleted", (staff_id,))[0]["n"]
        if used:
            execute(conn, "UPDATE staff SET active = FALSE WHERE id = %s", (staff_id,))
            return _back("/master/staff", keep=keep,
                         ok=f"คนนี้มีงานในระบบ {used} รายการ จึงปิดการใช้งานแทนการลบ")
        execute(conn, "DELETE FROM staff WHERE id = %s", (staff_id,))
    return _back("/master/staff", ok="ลบพนักงานออกจากทะเบียนแล้ว", keep=keep)


# ── ฝ่าย ─────────────────────────────────────────────────────
# ไม่มีเมนูของตัวเอง — เข้าจากปุ่ม "จัดการฝ่าย" บนหน้าพนักงาน (กติกา 12c: ต้องมีทางเข้า)
# เพราะเป็นทะเบียนเล็กที่นานๆ แตะที ไม่คุ้มพื้นที่ในเมนู

@router.get("/departments")
def departments_page(request: Request, ok: str = "", err: str = ""):
    user = require_role(request, "manager")
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT d.*,
                   (SELECT COUNT(*) FROM staff s
                     WHERE s.department_id = d.id AND s.active) AS staff_n
              FROM departments d
             ORDER BY d.sort_order, d.name
        """)
        return page(request, user, "master_departments.html", conn=conn, rows=rows)


@router.post("/departments/save")
def save_department(request: Request,
                    id: str = Form(""), name: str = Form(...),
                    sort_order: str = Form("0"), active: str = Form(""),
                    note: str = Form("")):
    require_role(request, "manager")
    values = (as_text(name), as_int(sort_order, 0), as_bool(active), as_text(note))
    if not values[0]:
        return _back("/master/departments", err="ต้องกรอกชื่อฝ่าย")

    try:
        with get_conn() as conn:
            if as_int(id):
                execute(conn, """
                    UPDATE departments SET name = %s, sort_order = %s, active = %s,
                           note = %s, updated_at = NOW()
                     WHERE id = %s
                """, values + (as_int(id),))
            else:
                execute(conn, """
                    INSERT INTO departments (name, sort_order, active, note)
                    VALUES (%s, %s, %s, %s)
                """, values)
    except errors.UniqueViolation:
        return _back("/master/departments", err=f"มีฝ่ายชื่อ \"{values[0]}\" อยู่แล้ว")
    return _back("/master/departments", ok="บันทึกฝ่ายแล้ว")


@router.post("/departments/{department_id}/delete")
def delete_department(request: Request, department_id: int):
    """ฝ่ายที่ยังมีคนอยู่จะไม่ถูกลบ แต่ปิดการใช้งานแทน — ลบจริงแล้วคนจะหลุดฝ่ายเงียบๆ"""
    require_role(request, "manager")
    with get_conn() as conn:
        used = fetchall(conn, "SELECT COUNT(*) AS n FROM staff WHERE department_id = %s",
                        (department_id,))[0]["n"]
        if used:
            execute(conn, "UPDATE departments SET active = FALSE WHERE id = %s",
                    (department_id,))
            return _back("/master/departments",
                         ok=f"ฝ่ายนี้มีพนักงาน {used} คน จึงปิดการใช้งานแทนการลบ")
        execute(conn, "DELETE FROM departments WHERE id = %s", (department_id,))
    return _back("/master/departments", ok="ลบฝ่ายแล้ว")
