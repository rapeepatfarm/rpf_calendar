"""routers/next_work.py — หน้า "งานต่อไป" (รวมหน้างานวันนี้กับงานที่จะถึงเข้าด้วยกัน)

เดิมแยกเป็นสองเมนู แต่คนใช้ต้องสลับไปมาเพื่อตอบคำถามเดียวกันคือ
"ตอนนี้ต้องทำอะไรบ้าง" · รวมเป็นหน้าเดียวเรียงจากด่วนที่สุดไล่ลงไปตามเวลา
"""
from fastapi import APIRouter, Request

from auth import require_login
from forms import OptInt
from database import fetchall, get_conn
from services import activities as act
from services import thaidate
from view import page

router = APIRouter()

# ช่วงที่ให้เลือกดูล่วงหน้า — ค่าเริ่มต้น 14 วันพอดีกับที่หน้าจอแสดงได้
# โดยไม่ต้องเลื่อนยาว และยาวพอเห็นงานรายเดือนรอบถัดไป
RANGES = ((7, "7 วัน"), (14, "14 วัน"), (30, "30 วัน"), (90, "3 เดือน"))
DEFAULT_DAYS = 14


@router.get("/next")
def next_page(request: Request, days: int = DEFAULT_DAYS, mine: int = 0,
              assignee_id: OptInt = None, category_id: OptInt = None,
              status: str = ""):
    user = require_login(request)
    if days not in [d for d, _ in RANGES]:
        days = DEFAULT_DAYS

    filters = {"assignee_id": assignee_id, "category_id": category_id,
               "status": status or None}
    # ปุ่ม "เฉพาะงานของฉัน" ใช้ได้เมื่อบัญชีถูกผูกกับทะเบียนพนักงานแล้วเท่านั้น
    # ถ้าไม่ผูกแล้วยังกรอง จะได้ผลลัพธ์ว่างเปล่าโดยไม่มีคำอธิบาย
    if mine and user["staff_id"]:
        filters["assignee_id"] = user["staff_id"]

    with get_conn() as conn:
        groups = act.today_groups(conn, filters)
        for items in groups.values():
            # เติมผู้ช่วยก่อน annotate เสมอ — annotate คิด can_run จาก helper_ids
            act.annotate(act.attach_helpers(conn, items), user)

        later = act.annotate(act.attach_helpers(conn, act.upcoming(conn, days, filters)), user)
        ahead: list[dict] = []
        for item in later:
            if not ahead or ahead[-1]["date"] != item["planned_date"]:
                ahead.append({"date": item["planned_date"], "items": []})
            ahead[-1]["items"].append(item)

        done_today = fetchall(conn, """
            SELECT COUNT(*) AS n FROM activities
             WHERE NOT is_deleted AND status = 'done'
               AND finished_at::date = CURRENT_DATE
        """)[0]["n"]

        staff = fetchall(conn, "SELECT id, name FROM staff WHERE active ORDER BY sort_order, name")
        categories = fetchall(conn, "SELECT id, name, color FROM activity_categories "
                                    "WHERE active ORDER BY sort_order, name")

        return page(request, user, "next.html", conn=conn,
                    groups=groups, ahead=ahead, later_n=len(later),
                    done_today=done_today, days=days, ranges=RANGES,
                    mine=mine, has_staff=user["staff_id"] is not None,
                    today_date=thaidate.today(),
                    f=filters, staff=staff, categories=categories)
