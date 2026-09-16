"""routers/calendar.py — ปฏิทินรายเดือน + แผงงานต่อไป/งานค้าง

มุมมองรายสัปดาห์ถูกถอดออกตามที่ผู้ใช้สั่ง — ปุ่มสลับเดือน/สัปดาห์กินพื้นที่แถบบน
โดยที่คนใช้จริงดูเป็นเดือนอย่างเดียว · `calgrid.build_week()` ยังอยู่ในโค้ดและมีเทสต์คุม
เผื่อวันหนึ่งอยากได้กลับมา แต่ไม่มีหน้าจอไหนเรียกใช้แล้ว
"""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from auth import require_login
from forms import OptInt
from database import fetchall, get_conn
from services import activities as act
from services import calgrid, thaidate
from view import page, panel_data

router = APIRouter()


def _filters(assignee_id: OptInt, category_id: OptInt, status: str) -> dict:
    return {"assignee_id": assignee_id, "category_id": category_id, "status": status or None}


def _master(conn) -> dict:
    return {
        "staff": fetchall(conn, "SELECT id, name FROM staff WHERE active ORDER BY sort_order, name"),
        "categories": fetchall(conn, "SELECT id, name, color FROM activity_categories "
                                     "WHERE active ORDER BY sort_order, name"),
    }


# แผงข้างมองไปข้างหน้ากี่วัน — ยาวกว่าหน้า "งานต่อไป" (14 วัน) เพราะที่นี่คนกำลัง
# มองภาพรวมทั้งเดือนอยู่แล้ว รายการที่สั้นเกินไปจะดูขัดกับปฏิทินที่เห็นตรงหน้า
PANEL_AHEAD_DAYS = 30


@router.get("/calendar")
def calendar_page(request: Request, y: int = 0, m: int = 0, d: str = "", a: int = 0,
                  assignee_id: OptInt = None, category_id: OptInt = None,
                  status: str = ""):
    """`a` = id ของกิจกรรมที่ให้กางรายละเอียดไว้ตั้งแต่โหลดหน้า

    ใช้ตอนผู้ใช้กดกิจกรรมในลิสต์ที่อยู่คนละเดือนกับปฏิทินที่เปิดอยู่ —
    ต้องโหลดหน้าใหม่เพื่อไปเดือนนั้น แล้วกางรายละเอียดต่อให้เหมือนไม่มีอะไรเกิดขึ้น
    """
    user = require_login(request)
    today = thaidate.today()
    filters = _filters(assignee_id, category_id, status)

    year, month = (y or today.year), (m or today.month)
    if not 1 <= month <= 12:
        return RedirectResponse("/calendar", status_code=303)

    first, last, grid_start, grid_end = calgrid.month_bounds(year, month)

    with get_conn() as conn:
        # เติมผู้ช่วยก่อน annotate เสมอ — annotate คิด can_run จาก helper_ids
        items = act.attach_helpers(conn, act.list_between(conn, grid_start, grid_end, filters))
        act.annotate(items, user)
        weeks = calgrid.build_weeks(year, month, items, today)

        # วันที่ถูกเลือกไว้ (ไฮไลต์ในตาราง + ใช้เป็นวันตั้งต้นของปุ่มเพิ่มงาน)
        selected = thaidate.parse_iso(d)
        if selected is None and first <= today <= last:
            selected = today

        # ── สองแถบในแผงข้าง ────────────────────────────────
        # ไม่ผูกกับเดือนที่กำลังดูอยู่โดยตั้งใจ — งานค้างส่วนมากอยู่เดือนก่อนหน้า
        # ถ้ากรองตามเดือนที่เปิดอยู่ พอเลื่อนไปดูเดือนอื่นงานค้างจะหายไปเฉยๆ
        groups = act.today_groups(conn, filters)
        for rows in groups.values():
            act.annotate(act.attach_helpers(conn, rows), user)
        later = act.annotate(
            act.attach_helpers(conn, act.upcoming(conn, PANEL_AHEAD_DAYS, filters)), user)

        # เรียงเป็นลิสต์เดียวไม่แยกหัวข้อ: กำลังทำ -> ของวันนี้ -> วันถัดๆ ไป
        next_items = groups["running"] + groups["planned"] + later

        return page(request, user, "calendar.html", conn=conn,
                    weeks=weeks, month_date=first,
                    prev_month=thaidate.add_months(first, -1),
                    next_month=thaidate.add_months(first, 1),
                    items_json=panel_data(items),
                    next_json=panel_data(next_items),
                    overdue_json=panel_data(groups["overdue"]),
                    ahead_days=PANEL_AHEAD_DAYS,
                    picked_id=a or 0,
                    day_index=calgrid.day_index(items),
                    selected=selected.isoformat() if selected else "",
                    f=filters, **_master(conn))


@router.get("/calendar/day/{day}")
def day_page(request: Request, day: str,
             assignee_id: OptInt = None, category_id: OptInt = None,
             status: str = ""):
    """ลิงก์เก่าที่เคยเป็นหน้าแยก — พาไปที่ปฏิทินเดือนนั้นพร้อมเลือกวันไว้ให้

    แผงรายละเอียดอยู่ในหน้าปฏิทินแล้ว จึงไม่ต้องมีหน้าแยกอีก
    """
    target = thaidate.parse_iso(day)
    if target is None:
        return RedirectResponse("/calendar", status_code=303)
    query = f"?y={target.year}&m={target.month}&d={target.isoformat()}"
    for key, value in (("assignee_id", assignee_id), ("category_id", category_id),
                       ("status", status)):
        if value:
            query += f"&{key}={value}"
    return RedirectResponse("/calendar" + query, status_code=303)
