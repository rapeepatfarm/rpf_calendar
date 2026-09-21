"""routers/duty.py — หน้าที่ประจำ: จุดงาน · คนประจำจุด · คนแทน · จุดที่ขาดคน (v2 เฟส C)

ไม่ใช่กิจกรรม ไม่ขึ้นปฏิทิน ไม่มีกดเริ่ม/จบ (§29.1) · หัวหน้างานขึ้นไปเท่านั้น
ตรรกะทั้งหมด (ใครอยู่ ใครขาด ตรวจก่อนบันทึก) อยู่ใน services/staffing.py
"""
from datetime import timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from auth import require_role
from database import execute, fetchall, get_conn
from forms import OptInt, as_bool, as_date, as_int, as_text
from services import staffing, thaidate
from view import page

router = APIRouter(prefix="/duty")

SAFE_PREFIXES = ("/duty", "/calendar", "/leaves", "/master/staff")


def _safe_next(value: str) -> str:
    value = (value or "").strip()
    if value.startswith(SAFE_PREFIXES) and "//" not in value:
        return value
    return "/duty"


def _redirect(target: str, ok: str = "", err: str = "") -> RedirectResponse:
    params = {}
    if ok:
        params["ok"] = ok
    elif err:
        params["err"] = err
    if params:
        target += ("&" if "?" in target else "?") + urlencode(params, quote_via=quote)
    return RedirectResponse(target, status_code=303)


@router.get("")
def duty_page(request: Request, department_id: OptInt = None, all: str = "",
              ask: OptInt = None, next: str = ""):
    """`ask` = id การลาที่เพิ่งบันทึก — ขึ้นกล่องบอกว่าการลานั้นทำให้จุดไหนขาดคน (§29.6)

    `all=1` = แสดงคนที่จบการประจำไปแล้วด้วย (ปกติซ่อน ให้ผังอ่านง่าย)
    """
    user = require_role(request, "manager")
    today = thaidate.today()
    horizon = today + timedelta(days=staffing.SHORTFALL_AHEAD_DAYS)

    with get_conn() as conn:
        posts = staffing.posts(conn, active_only=False)
        if department_id:
            posts = [p for p in posts if p["department_id"] == department_id]

        # ผังปัจจุบัน+อนาคต — ที่จบไปแล้วดึงมาเฉพาะเมื่อขอ
        if all == "1":
            rows = fetchall(conn, staffing._ASSIGN_SELECT + staffing._ASSIGN_ORDER)
        else:
            rows = fetchall(conn, staffing._ASSIGN_SELECT
                            + " AND (a.ends_on IS NULL OR a.ends_on >= %s)"
                            + staffing._ASSIGN_ORDER, (today,))
        by_post: dict[int, dict] = {p["id"]: {"regular": [], "covers": []} for p in posts}
        for a in rows:
            bucket = by_post.get(a["post_id"])
            if bucket is None:
                continue
            (bucket["covers"] if a["covers_staff_id"] else bucket["regular"]).append(a)

        # สภาพวันนี้ของแต่ละจุด (มีกี่คน ขาดไหม) ใช้นิยามกลาง
        data = staffing.load_roster_inputs(conn, today, horizon)
        today_state = {r["post"]["id"]: r
                       for r in staffing.roster_for_day(data["posts"], data["assignments"],
                                                        data["leaves"], today)}
        runs = staffing.shortfalls(data["posts"], data["assignments"], data["leaves"],
                                   today, horizon)

        # การลาที่เพิ่งบันทึก → เน้นเฉพาะจุดที่ได้รับผลกระทบจากคนนั้น
        asked = staffing.get(conn, ask) if ask else None
        asked_runs = []
        if asked:
            asked_runs = staffing.shortfalls(data["posts"], data["assignments"], data["leaves"],
                                             max(asked["date_from"], today),
                                             min(asked["date_to"], horizon),
                                             staff_id=asked["staff_id"])

        absent_today = {pid: [a["staff_id"] for a in r["absent"]] for pid, r in today_state.items()}
        return page(request, user, "duty.html", conn=conn,
                    posts=posts, by_post=by_post, today_state=today_state,
                    absent_today=absent_today, runs=runs,
                    asked=asked, asked_runs=asked_runs,
                    staff=staffing.active_staff(conn),
                    departments=fetchall(conn, "SELECT id, name FROM departments WHERE active "
                                               "ORDER BY sort_order, name"),
                    flt={"department_id": department_id}, show_all=all == "1",
                    today_iso=today.isoformat(), ahead_days=staffing.SHORTFALL_AHEAD_DAYS,
                    next_url=_safe_next(next))


# ── จุดงาน ───────────────────────────────────────────────────

@router.post("/posts/save")
def save_post(request: Request, id: str = Form(""), name: str = Form(...),
              department_id: str = Form(""), required_n: str = Form(""),
              description: str = Form(""), sort_order: str = Form("0"),
              active: str = Form("")):
    require_role(request, "manager")
    with get_conn() as conn:
        _, problem = staffing.save_post(conn, {
            "name": as_text(name), "department_id": as_int(department_id),
            "required_n": as_int(required_n), "description": as_text(description),
            "sort_order": as_int(sort_order, 0), "active": as_bool(active),
        }, as_int(id))
    if problem:
        return _redirect("/duty", err=problem)
    return _redirect("/duty", ok="บันทึกจุดงานแล้ว")


@router.post("/posts/{post_id}/delete")
def delete_post(request: Request, post_id: int):
    """จุดที่เคยมีคนประจำจะไม่ถูกลบ แต่ปิดใช้งานแทน — ผังในอดีตต้องยังอ้างถึงมันได้"""
    require_role(request, "manager")
    with get_conn() as conn:
        used = fetchall(conn, "SELECT COUNT(*) AS n FROM duty_assignments "
                              "WHERE post_id = %s AND NOT is_deleted", (post_id,))[0]["n"]
        if used:
            execute(conn, "UPDATE duty_posts SET active = FALSE, updated_at = NOW() WHERE id = %s",
                    (post_id,))
            return _redirect("/duty", ok=f"จุดงานนี้มีการมอบหมาย {used} รายการ จึงปิดการใช้งานแทนการลบ")
        execute(conn, "DELETE FROM duty_posts WHERE id = %s", (post_id,))
    return _redirect("/duty", ok="ลบจุดงานแล้ว")


# ── การมอบหมาย (คนประจำ / คนแทน) ─────────────────────────────

@router.post("/assign/save")
def save_assignment(request: Request, id: str = Form(""), post_id: str = Form(""),
                    staff_id: str = Form(""), starts_on: str = Form(""),
                    ends_on: str = Form(""), covers_staff_id: str = Form(""),
                    note: str = Form(""), next: str = Form("")):
    user = require_role(request, "manager")
    back = _safe_next(next)
    data = {
        "post_id": as_int(post_id), "staff_id": as_int(staff_id),
        "starts_on": as_date(starts_on), "ends_on": as_date(ends_on),
        "covers_staff_id": as_int(covers_staff_id), "note": as_text(note),
    }
    assignment_id = as_int(id)
    with get_conn() as conn:
        if assignment_id and staffing.get_assignment(conn, assignment_id) is None:
            return _redirect(back, err="ไม่พบรายการนี้ (อาจถูกลบไปแล้ว)")
        problem = staffing.validate_assignment(conn, data, exclude_id=assignment_id)
        if problem:
            return _redirect(back, err=problem)
        if assignment_id:
            staffing.update_assignment(conn, assignment_id, data, user)
            msg = "แก้ไขการมอบหมายแล้ว"
        else:
            staffing.create_assignment(conn, data, user)
            msg = "บันทึกคนแทนแล้ว" if data["covers_staff_id"] else "บันทึกคนประจำแล้ว"
    return _redirect(back, ok=msg)


@router.post("/assign/{assignment_id}/end")
def end_assignment(request: Request, assignment_id: int, ends_on: str = Form(""),
                   next: str = Form("")):
    user = require_role(request, "manager")
    back = _safe_next(next)
    when = as_date(ends_on)
    if when is None:
        return _redirect(back, err="ต้องระบุวันสิ้นสุด")
    with get_conn() as conn:
        problem = staffing.end_assignment(conn, assignment_id, when, user)
    if problem:
        return _redirect(back, err=problem)
    return _redirect(back, ok=f"จบการประจำ ณ {thaidate.short(when)} แล้ว")


@router.post("/assign/{assignment_id}/delete")
def delete_assignment(request: Request, assignment_id: int, next: str = Form("")):
    user = require_role(request, "manager")
    back = _safe_next(next)
    with get_conn() as conn:
        if staffing.get_assignment(conn, assignment_id) is None:
            return _redirect(back, err="ไม่พบรายการนี้")
        staffing.delete_assignment(conn, assignment_id, user)
    return _redirect(back, ok="ลบการมอบหมายแล้ว")
