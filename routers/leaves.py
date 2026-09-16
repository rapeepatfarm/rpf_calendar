"""routers/leaves.py — วันลาของพนักงาน (v2 เฟส B)

หน้าจัดการอยู่ที่ /leaves เข้าจากปุ่ม "วันลา" บนหน้าจัดการพนักงาน และจากแถบ
"พนักงาน" ในกล่องข้างของปฏิทิน · หัวหน้างานขึ้นไปเท่านั้น (ผู้ใช้ยืนยัน §29)

ตรรกะทั้งหมด (ตรวจซ้อน ครึ่งวัน) อยู่ใน services/staffing.py — ที่นี่แค่รับฟอร์มและเด้งกลับ
"""
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from auth import require_role
from database import fetchall, get_conn
from forms import OptInt, as_date, as_int, as_text
from services import staffing, thaidate
from view import page

router = APIRouter(prefix="/leaves")

# ปลายทางที่ยอมให้กลับไปหลังบันทึก — ปุ่มลัดจากปฏิทินส่ง next มาเป็นหน้าปฏิทินเดือนนั้น
SAFE_PREFIXES = ("/calendar", "/leaves", "/master/staff")


def _safe_next(value: str) -> str:
    value = (value or "").strip()
    if value.startswith(SAFE_PREFIXES) and "//" not in value:
        return value
    return "/leaves"


def _redirect(target: str, ok: str = "", err: str = "", keep: dict | None = None) -> RedirectResponse:
    params = {k: v for k, v in (keep or {}).items() if v not in (None, "")}
    if ok:
        params["ok"] = ok
    elif err:
        params["err"] = err
    if params:
        target += ("&" if "?" in target else "?") + urlencode(params, quote_via=quote)
    return RedirectResponse(target, status_code=303)


def _master(conn) -> dict:
    return {
        "staff": fetchall(conn, """
            SELECT s.id, s.name, s.color, s.code, d.name AS department_name
              FROM staff s LEFT JOIN departments d ON d.id = s.department_id
             WHERE s.active
             ORDER BY d.sort_order NULLS LAST, d.name, s.sort_order, s.name
        """),
        "departments": fetchall(conn, "SELECT id, name FROM departments WHERE active "
                                      "ORDER BY sort_order, name"),
        "leave_types": fetchall(conn, "SELECT id, name, color FROM leave_types WHERE active "
                                      "ORDER BY sort_order, name"),
    }


@router.get("")
def leaves_page(request: Request, staff_id: OptInt = None, department_id: OptInt = None,
                add: str = "", date: str = "", next: str = ""):
    """`add=1` = เปิดฟอร์มเพิ่มทันที (ปุ่มลัดจากปฏิทิน) · `date` = วันตั้งต้นของฟอร์ม

    `next` = หน้าที่จะกลับไปหลังบันทึก — ปฏิทินส่งมาเพื่อให้กลับไปเดือนเดิมที่ดูอยู่
    """
    user = require_role(request, "manager")
    with get_conn() as conn:
        groups = staffing.listing(conn, staff_id, department_id)
        preset_date = thaidate.parse_iso(date) or thaidate.today()
        return page(request, user, "leaves.html", conn=conn,
                    upcoming=groups["upcoming"], past=groups["past"],
                    flt={"staff_id": staff_id, "department_id": department_id},
                    open_add=add == "1", preset_date=preset_date.isoformat(),
                    preset_staff=staff_id or "",
                    next_url=_safe_next(next), past_days=staffing.PAST_DAYS,
                    PART_LABELS=staffing.PART_LABELS, **_master(conn))


@router.post("/save")
def save_leave(request: Request,
               id: str = Form(""), staff_id: str = Form(""), leave_type_id: str = Form(""),
               date_from: str = Form(""), date_to: str = Form(""), part: str = Form("full"),
               note: str = Form(""), next: str = Form(""),
               f_staff_id: str = Form(""), f_department_id: str = Form("")):
    user = require_role(request, "manager")
    back = _safe_next(next)
    keep = {"staff_id": f_staff_id, "department_id": f_department_id} if back == "/leaves" else {}

    data = {
        "staff_id": as_int(staff_id),
        "leave_type_id": as_int(leave_type_id),
        "date_from": as_date(date_from),
        # เว้นวันสิ้นสุด = ลาวันเดียว ไม่ต้องบังคับกรอกซ้ำ
        "date_to": as_date(date_to) or as_date(date_from),
        "part": as_text(part) or "full",
        "note": as_text(note),
    }
    leave_id = as_int(id)

    with get_conn() as conn:
        if leave_id and staffing.get(conn, leave_id) is None:
            return _redirect(back, err="ไม่พบรายการลานี้ (อาจถูกลบไปแล้ว)", keep=keep)
        problem = staffing.validate(conn, data, exclude_id=leave_id)
        if problem:
            return _redirect(back, err=problem, keep=keep)
        if leave_id:
            staffing.update(conn, leave_id, data, user)
            msg = "แก้ไขการลาแล้ว"
        else:
            staffing.create(conn, data, user)
            msg = "บันทึกการลาแล้ว"
    return _redirect(back, ok=msg, keep=keep)


@router.post("/{leave_id}/delete")
def delete_leave(request: Request, leave_id: int, next: str = Form(""),
                 f_staff_id: str = Form(""), f_department_id: str = Form("")):
    user = require_role(request, "manager")
    back = _safe_next(next)
    keep = {"staff_id": f_staff_id, "department_id": f_department_id} if back == "/leaves" else {}
    with get_conn() as conn:
        if staffing.get(conn, leave_id) is None:
            return _redirect(back, err="ไม่พบรายการลานี้", keep=keep)
        staffing.soft_delete(conn, leave_id, user)
    return _redirect(back, ok="ลบการลาแล้ว", keep=keep)
