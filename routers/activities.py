"""routers/activities.py — สร้าง แก้ไข ดูรายละเอียด และเปลี่ยนสถานะกิจกรรม

ทุกการเปลี่ยนแปลงเรียกผ่าน services/activities.py เท่านั้น
router นี้ทำหน้าที่แค่ตรวจสิทธิ์ แปลงค่าจากฟอร์ม แล้วส่งต่อ
"""
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from auth import (can_create, can_edit_activity, can_manage, can_run_activity,
                  require_login)
from database import fetchall, get_conn
from forms import as_bool, as_date, as_int, as_priority, as_text, as_time
from services import activities as act
from services import thaidate
from view import page

router = APIRouter(prefix="/activities")

# หน้าที่อนุญาตให้ย้อนกลับไปได้หลังกดปุ่ม — กันไม่ให้ค่า next ที่ถูกยัดมาใน URL
# พาผู้ใช้ออกไปเว็บอื่น (open redirect)
SAFE_PREFIXES = ("/next", "/calendar", "/activities", "/plans")


def _safe_next(value: str, fallback: str) -> str:
    value = (value or "").strip()
    if value.startswith(SAFE_PREFIXES) and "//" not in value:
        return value
    return fallback


def _redirect(target: str, ok: str = "", err: str = "") -> RedirectResponse:
    joiner = "&" if "?" in target else "?"
    if ok:
        target += f"{joiner}ok={quote(ok)}"
    elif err:
        target += f"{joiner}err={quote(err)}"
    return RedirectResponse(target, status_code=303)


def _load(conn, activity_id: int) -> dict:
    activity = act.get(conn, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="ไม่พบกิจกรรมนี้")
    # ต้องเติมผู้ช่วยก่อนตรวจสิทธิ์ทุกครั้ง ไม่งั้นผู้ช่วยจะกดเริ่มงานตัวเองไม่ได้
    act.attach_helpers(conn, [activity])
    return activity


def _master(conn) -> dict:
    cats = fetchall(conn, "SELECT id, name, color, default_priority, "
                          "default_duration_min, needs_start FROM activity_categories "
                          "WHERE active ORDER BY sort_order, name")
    return {
        "staff": fetchall(conn, "SELECT id, name, position FROM staff "
                                "WHERE active ORDER BY sort_order, name"),
        "categories": cats,
        # ค่าตั้งต้นของช่อง "ต้องกดเริ่มงานไหม" แยกตามประเภท ส่งไปให้ฟอร์มทั้งชุด
        # กุญแจเป็น string เพราะ <select> คืนค่าเป็น string เสมอ
        "cat_needs_start": {str(c["id"]): c["needs_start"] for c in cats},
    }


def _form_data(form) -> dict:
    """แปลงค่าจากฟอร์มเป็นชุดข้อมูลที่ service ใช้ — ใช้ร่วมกันทั้งสร้างและแก้ไข"""
    all_day = as_bool(form.get("is_all_day"))
    return {
        "title": as_text(form.get("title")),
        "category_id": as_int(form.get("category_id")),
        "description": as_text(form.get("description")),
        "assignee_id": as_int(form.get("assignee_id")),
        "priority": as_priority(form.get("priority")),
        "planned_date": as_date(form.get("planned_date")),
        # เว้นว่าง = งานวันเดียว · service จะหนีบให้เท่ากับวันเริ่มถ้ากรอกย้อนหลัง
        "planned_end_date": as_date(form.get("planned_end_date")),
        "is_all_day": all_day,
        # งานทั้งวันไม่ควรมีเวลาค้างอยู่ใน DB ไม่งั้นปฏิทินจะแสดงเวลาที่ผู้ใช้ยกเลิกไปแล้ว
        "planned_start_time": None if all_day else as_time(form.get("planned_start_time")),
        "planned_end_time": None if all_day else as_time(form.get("planned_end_time")),
        "duration_min": None if all_day else as_int(form.get("duration_min")),
        "carry_over": as_bool(form.get("carry_over")),
        "needs_start": as_bool(form.get("needs_start")),
        "auto_skip_after_days": as_int(form.get("auto_skip_after_days")),
    }


def _helper_ids(form) -> list[int]:
    return [i for i in (as_int(v) for v in form.getlist("helper_ids")) if i]


# ── สร้าง / แก้ไข ────────────────────────────────────────────

@router.get("/new")
def new_form(request: Request, date: str = ""):
    user = require_login(request)
    if not can_create(user):
        raise HTTPException(status_code=403, detail="บัญชีนี้สร้างกิจกรรมไม่ได้")
    with get_conn() as conn:
        return page(request, user, "activity_form.html", conn=conn,
                    activity=None, default_date=as_date(date) or thaidate.today(),
                    **_master(conn))


@router.post("/new")
async def create(request: Request):
    user = require_login(request)
    if not can_create(user):
        raise HTTPException(status_code=403, detail="บัญชีนี้สร้างกิจกรรมไม่ได้")

    form = await request.form()
    data = _form_data(form)
    if not data["title"] or not data["planned_date"]:
        return _redirect("/activities/new", err="ต้องกรอกชื่องานและวันที่วางแผน")

    # พนักงานสร้างงานได้เฉพาะของตัวเอง — ป้องกันการมอบหมายงานให้คนอื่นข้ามหัวหน้า
    if not can_manage(user):
        data["assignee_id"] = user["staff_id"]

    with get_conn() as conn:
        activity_id = act.create(conn, data, user)
        if can_manage(user):
            act.set_helpers(conn, activity_id, _helper_ids(form))
    return _redirect(f"/activities/{activity_id}", ok="สร้างกิจกรรมเรียบร้อยแล้ว")


@router.get("/{activity_id}/edit")
def edit_form(request: Request, activity_id: int):
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_edit_activity(user, activity):
            raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์แก้ไขกิจกรรมนี้")
        return page(request, user, "activity_form.html", conn=conn,
                    activity=activity, default_date=activity["planned_date"], **_master(conn))


@router.post("/{activity_id}/edit")
async def edit(request: Request, activity_id: int):
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_edit_activity(user, activity):
            raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์แก้ไขกิจกรรมนี้")

        form = await request.form()
        data = _form_data(form)
        if not data["title"] or not data["planned_date"]:
            return _redirect(f"/activities/{activity_id}/edit",
                             err="ต้องกรอกชื่องานและวันที่วางแผน")
        if not can_manage(user):
            data["assignee_id"] = activity["assignee_id"]

        act.update(conn, activity, data, user)
        if can_manage(user):
            act.set_helpers(conn, activity_id, _helper_ids(form))
    return _redirect(f"/activities/{activity_id}", ok="บันทึกการแก้ไขแล้ว")


# ── รายละเอียด ───────────────────────────────────────────────

@router.get("/{activity_id}")
def detail(request: Request, activity_id: int, ask_shift: str = ""):
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        act.annotate([activity], user)

        # คิดรายการรอบที่ต้องขยับ เฉพาะตอนที่เพิ่งกดเริ่มแล้วเจอการชน
        # (ธงมาจาก query string ไม่ได้เก็บสถานะไว้ในฐานข้อมูล — ถ้าผู้ใช้ปิดไป
        #  ก็ถือว่าไม่เลื่อน จะได้ไม่มีกล่องยืนยันค้างตามหลอกทุกครั้งที่เปิดหน้านี้)
        shift = None
        if as_bool(ask_shift) and activity["status"] == "in_progress":
            shift = act.shift_chain(conn, activity, thaidate.today())

        return page(request, user, "activity_detail.html", conn=conn,
                    a=activity, log=act.log_entries(conn, activity_id),
                    can_reopen=can_manage(user), shift=shift)


# ── เปลี่ยนสถานะ ─────────────────────────────────────────────

def _run_action(request: Request, activity_id: int, next_url: str, handler):
    """โครงร่วมของทุกปุ่มเปลี่ยนสถานะ — ตรวจสิทธิ์แล้วเรียก service"""
    user = require_login(request)
    back = _safe_next(next_url, f"/activities/{activity_id}")
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_run_activity(user, activity):
            raise HTTPException(
                status_code=403,
                detail="กดได้เฉพาะงานที่คุณรับผิดชอบ — ถ้าต้องกดแทนคนอื่น ให้แจ้งหัวหน้างาน")
        problem = handler(conn, activity, user)
    return _redirect(back, err=problem) if problem else _redirect(back)


@router.post("/{activity_id}/start")
def start(request: Request, activity_id: int,
          next: str = Form(""), confirm: str = Form("")):
    """กดเริ่มงาน

    ถ้าเลื่อนวันมาวันนี้แล้วจะไปชนรอบอื่นของแผนประจำเดียวกัน จะยังไม่เลื่อนให้
    แต่พาไปหน้ารายละเอียดพร้อมธง ask_shift เพื่อถามยืนยันอีกชั้นว่า
    จะให้เลื่อนรอบถัดไปออกไปตามคาบของแผนหรือไม่ (ผู้ใช้กำหนดให้เป็นสองจังหวะ)
    """
    user = require_login(request)
    confirmed = as_bool(confirm)
    back = _safe_next(next, f"/activities/{activity_id}")
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_run_activity(user, activity):
            raise HTTPException(
                status_code=403,
                detail="กดได้เฉพาะงานที่คุณรับผิดชอบ — ถ้าต้องกดแทนคนอื่น ให้แจ้งหัวหน้างาน")
        problem = act.start(conn, activity, user, confirmed=confirmed)
        ask = (problem is None
               and act.shift_chain(conn, activity, thaidate.today()) is not None)

    if problem:
        return _redirect(back, err=problem)
    if ask:
        # ต้องกลับไปหน้ารายละเอียดเสมอ เพราะกล่องยืนยันชั้นที่สองอยู่ที่นั่น
        return _redirect(f"/activities/{activity_id}?ask_shift=1")
    return _redirect(back)


@router.post("/{activity_id}/shift-plan")
def shift_plan(request: Request, activity_id: int, next: str = Form("")):
    """ยืนยันชั้นที่สอง — เลื่อนรอบถัดไปออกไป แล้วเลื่อนงานนี้มาวันที่ลงมือจริง"""
    return _run_action(request, activity_id, next, act.apply_shift)


@router.post("/{activity_id}/unstart")
def unstart(request: Request, activity_id: int, next: str = Form("")):
    """ยกเลิกการเริ่มงาน — คนที่กดเริ่มได้ก็ถอนได้ เพราะเป็นการแก้ที่กดผิด"""
    return _run_action(request, activity_id, next, act.unstart)


@router.post("/{activity_id}/start-date")
def start_date(request: Request, activity_id: int,
               started_on: str = Form(""), next: str = Form("")):
    """แก้วันเริ่มงานย้อนหลัง — ลงมือจริงไปแล้วแต่ลืมกดปุ่ม"""
    when = as_date(started_on)
    if when is None:
        return _redirect(_safe_next(next, f"/activities/{activity_id}"),
                         err="ใส่วันที่เริ่มงานให้ถูกต้องด้วย")
    return _run_action(request, activity_id, next,
                       lambda c, a, u: act.set_start_date(c, a, u, when))


@router.post("/{activity_id}/finish")
def finish(request: Request, activity_id: int,
           next: str = Form(""), result_note: str = Form("")):
    return _run_action(request, activity_id, next,
                       lambda c, a, u: act.finish(c, a, u, as_text(result_note)))


@router.post("/{activity_id}/note")
def note(request: Request, activity_id: int, result_note: str = Form("")):
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_run_activity(user, activity):
            raise HTTPException(status_code=403, detail="บันทึกผลได้เฉพาะงานที่คุณรับผิดชอบ")
        act.add_note(conn, activity, user, as_text(result_note))
    return _redirect(f"/activities/{activity_id}", ok="บันทึกผลงานแล้ว")


@router.post("/{activity_id}/cancel")
def cancel(request: Request, activity_id: int,
           reason: str = Form(""), next: str = Form("")):
    user = require_login(request)
    back = _safe_next(next, f"/activities/{activity_id}")
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_edit_activity(user, activity):
            raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ยกเลิกกิจกรรมนี้")
        problem = act.cancel(conn, activity, user, as_text(reason))
    return _redirect(back, err=problem) if problem else _redirect(back, ok="ยกเลิกกิจกรรมแล้ว")


@router.post("/{activity_id}/missed")
def missed(request: Request, activity_id: int,
           reason: str = Form(""), next: str = Form("")):
    """ปิดงานค้างว่าไม่ได้ทำ — คนละเรื่องกับยกเลิกแผน จึงต้องเป็นสิทธิ์หัวหน้า"""
    user = require_login(request)
    back = _safe_next(next, f"/activities/{activity_id}")
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_manage(user):
            raise HTTPException(status_code=403, detail="เฉพาะหัวหน้างานที่ปิดงานค้างได้")
        problem = act.mark_missed(conn, activity, user, as_text(reason))
    return _redirect(back, err=problem) if problem else _redirect(back, ok="ปิดงานว่าไม่ได้ทำแล้ว")


@router.post("/{activity_id}/reopen")
def reopen(request: Request, activity_id: int):
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_manage(user):
            raise HTTPException(status_code=403, detail="เฉพาะหัวหน้างานที่เปิดงานที่ปิดแล้วได้")
        problem = act.reopen(conn, activity, user)
    target = f"/activities/{activity_id}"
    return _redirect(target, err=problem) if problem else _redirect(target, ok="เปิดงานกลับมาแล้ว")


@router.post("/{activity_id}/delete")
def delete(request: Request, activity_id: int, next: str = Form("")):
    """ลบกิจกรรม (แบบซ่อน ประวัติยังอยู่) — เฉพาะหัวหน้างานขึ้นไป

    เช็คสิทธิ์ที่นี่ด้วยเสมอ ไม่ใช่แค่ซ่อนปุ่มบนหน้าจอ เพราะยิง POST ตรงๆ ได้
    """
    user = require_login(request)
    with get_conn() as conn:
        activity = _load(conn, activity_id)
        if not can_manage(user):
            raise HTTPException(status_code=403, detail="เฉพาะหัวหน้างานที่ลบกิจกรรมได้")
        act.soft_delete(conn, activity, user)
    # กลับไปหน้าที่กดมา (ปฏิทินเดือนเดิม) ไม่ใช่โยนไปหน้าอื่นให้ผู้ใช้หลงทาง
    return _redirect(_safe_next(next, "/calendar"), ok="ลบกิจกรรมแล้ว")
