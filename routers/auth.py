"""routers/auth.py — เข้าสู่ระบบ ออกจากระบบ และบัญชีของฉัน"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from auth import (authenticate, hash_password, password_problem, require_login,
                  verify_password)
from database import execute, fetchall, get_conn
from services import loginguard
from view import page, templates

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/calendar", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


def _client_ip(request: Request) -> str:
    """ไอพีของผู้ใช้ — เมื่ออยู่หลัง Cloudflare Tunnel ไอพีจริงมาใน header

    ถ้าไม่อ่าน header ทุกคนที่เข้าผ่าน tunnel จะถูกนับเป็นไอพีเดียวกัน
    แล้วคนหนึ่งเดารหัสผิดจะล็อกคนอื่นไปด้วย
    """
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header, "")
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _login_error(request: Request, message: str, status: int = 401):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": message}, status_code=status)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = _client_ip(request)

    waiting = loginguard.locked_for(username, ip)
    if waiting:
        return _login_error(request, loginguard.wait_message(waiting), status=429)

    user = authenticate(username.strip(), password)
    if not user:
        loginguard.record_failure(username, ip)
        return _login_error(request, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    loginguard.clear(username, ip)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/calendar", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/account")
def account(request: Request, ok: str = "", err: str = "", force: str = ""):
    user = require_login(request)
    with get_conn() as conn:
        # ผู้ใช้ควรเห็นว่าตัวเองถูกผูกกับพนักงานคนไหน เพราะมันตัดสินว่าเห็น "งานของฉัน" อะไรบ้าง
        linked = fetchall(conn, "SELECT name, position FROM staff WHERE user_id = %s", (user["id"],))
        return page(request, user, "account.html", conn=conn,
                    linked=linked[0] if linked else None,
                    forced=bool(user.get("must_change_password")))


@router.post("/account/password")
def change_password(request: Request,
                    current: str = Form(...),
                    new_password: str = Form(...),
                    confirm: str = Form(...)):
    user = require_login(request)

    if not verify_password(current, user["password_hash"]):
        return RedirectResponse("/account?err=รหัสผ่านเดิมไม่ถูกต้อง", status_code=303)
    if new_password != confirm:
        return RedirectResponse("/account?err=รหัสผ่านใหม่สองช่องไม่ตรงกัน", status_code=303)
    problem = password_problem(new_password)
    if problem:
        return RedirectResponse(f"/account?err={problem}", status_code=303)

    if new_password == current:
        return RedirectResponse("/account?err=รหัสผ่านใหม่ต้องไม่ซ้ำกับรหัสเดิม",
                                status_code=303)

    with get_conn() as conn:
        execute(conn, """
            UPDATE users SET password_hash = %s, must_change_password = FALSE WHERE id = %s
        """, (hash_password(new_password), user["id"]))

    # ถ้าเพิ่งถูกบังคับเปลี่ยน ให้พาเข้าหน้าใช้งานเลย จะได้ไม่ต้องกดเองอีกที
    if user.get("must_change_password"):
        return RedirectResponse("/calendar?ok=ตั้งรหัสผ่านใหม่เรียบร้อย ใช้งานได้เลย",
                                status_code=303)
    return RedirectResponse("/account?ok=เปลี่ยนรหัสผ่านเรียบร้อยแล้ว", status_code=303)
