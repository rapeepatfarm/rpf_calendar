"""view.py — Jinja2 กลางของทั้งโปรแกรม

รวมไว้ที่เดียวเพราะทุกหน้าต้องใช้ตัวช่วยจัดรูปวันที่ไทยและป้ายสถานะชุดเดียวกัน
ถ้าปล่อยให้แต่ละ router สร้าง Jinja2Templates เอง จะลืมลงทะเบียนตัวช่วยบางตัว
แล้วหน้านั้นจะพังตอน render เท่านั้น ไม่มีอะไรเตือนตอนเขียนโค้ด
"""
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import BASE_DIR
from database import fetchone, get_conn
from auth import ROLE_LABELS
from services import activities as act
from services import staffing, thaidate
from sync.sources import SYSTEM_LABELS

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def asset(path: str) -> str:
    """ต่อเลขเวอร์ชันท้าย URL ของไฟล์ static ตามเวลาที่ไฟล์ถูกแก้ล่าสุด

    ถ้าไม่ทำ เบราว์เซอร์จะใช้ CSS/JS ที่แคชไว้ต่อไปแม้เราจะแก้ไฟล์แล้ว
    ผลคือหน้าจอเพี้ยนแบบหาสาเหตุยากมาก — HTML เป็นของใหม่ (ไม่ถูกแคช)
    แต่ CSS/JS เป็นของเก่า ปุ่มจึงขึ้นแบบไม่มีสไตล์และตัวจัดการคลิกไม่ตรงกัน
    เคยเกิดจริงตอนเปลี่ยนแผงข้างของหน้าปฏิทิน (2026-08-27)

    อ่าน mtime สดทุกครั้ง ไม่แคชไว้ในตัวแปร เพราะระหว่างแก้งานเรารีสตาร์ต
    เฉพาะตัวเซิร์ฟเวอร์บ้าง ไม่ได้รีสตาร์ตทุกครั้งที่แก้ไฟล์ static
    ต้นทุนคือ stat() ครั้งเดียวต่อไฟล์ต่อการโหลดหน้า ซึ่งไม่มีนัยสำคัญ
    """
    file = BASE_DIR / "static" / path.lstrip("/")
    try:
        return f"/static/{path.lstrip('/')}?v={int(file.stat().st_mtime)}"
    except OSError:
        return f"/static/{path.lstrip('/')}"

templates.env.globals.update(
    d_short=thaidate.short,
    d_long=thaidate.long,
    d_span=thaidate.span,
    d_relative=thaidate.relative_day,
    d_month=thaidate.month_year,
    t_hhmm=thaidate.hhmm,
    t_range=thaidate.time_range,
    ts=thaidate.stamp,
    d_local=thaidate.local_date,
    dur=thaidate.duration,
    today=thaidate.today,
    STATUS_LABELS=act.STATUS_LABELS,
    PRIORITY_LABELS=act.PRIORITY_LABELS,
    ACTION_LABELS=act.ACTION_LABELS,
    WEEKDAYS_SHORT=thaidate.WEEKDAYS_SHORT,
    ROLE_LABELS=ROLE_LABELS,
    asset=asset,
    SOURCE_LABELS=SYSTEM_LABELS,
)


def panel_data(rows: list[dict]) -> list[dict]:
    """แปลงกิจกรรมเป็นข้อมูลพร้อมแสดงสำหรับแผงรายละเอียดฝั่งเบราว์เซอร์

    จัดรูปข้อความทั้งหมด (วันที่ไทย เวลา ป้ายสถานะ) ที่ฝั่งเซิร์ฟเวอร์
    เพื่อไม่ให้ต้องเขียนตรรกะจัดรูปวันที่ไทยซ้ำอีกชุดใน JavaScript
    ซึ่งจะเพี้ยนจากฝั่งเซิร์ฟเวอร์เมื่อไรก็ได้โดยไม่มีใครรู้
    """
    return [{
        "id": r["id"],
        "title": r["title"],
        "status": r["status"],
        "status_label": act.STATUS_LABELS[r["status"]],
        "priority": r["priority"],
        "priority_label": act.PRIORITY_LABELS[r["priority"]],
        "urgent": r["priority"] <= 2,
        "category": r["category_name"] or "",
        "color": r["category_color"] or "#8592a6",
        "assignee": r["assignee_name"] or "",
        "helpers": ", ".join(r.get("helper_names") or []),
        # วัน ISO ดิบ — ใช้คำนวณว่าต้องเลื่อนปฏิทินไปเดือนไหนตอนกดจากลิสต์
        # (ข้อความไทยใน "when" เอาไปคำนวณต่อไม่ได้ และห้ามแปลงกลับใน JS)
        "date": r["planned_date"].isoformat(),
        "when": thaidate.span(r["planned_date"], r["planned_end_date"]),
        "time": ("ทั้งวัน" if r["is_all_day"] else
                 thaidate.time_range(r["planned_start_time"], r["planned_end_time"],
                                     r["duration_min"])),
        "started": thaidate.stamp(r.get("started_at")),
        "started_on": (thaidate.local_date(r["started_at"]).isoformat()
                       if r.get("started_at") else ""),
        "needs_start": r.get("needs_start", True),
        "days_late": r["days_late"],
        "span": r.get("span_days") or 1,
        "note": r["result_note"],
        "description": r["description"],
        "closed": r["status"] in act.CLOSED_STATUSES,
        "can_run": r.get("can_run", False),
        "start_state": r.get("start_state", ""),
        "start_days": r.get("start_days", 0),
    } for r in rows]


def overdue_count(conn) -> int:
    """จำนวนงานค้าง — ขึ้นเป็นตัวเลขแดงข้างเมนู 'วันนี้' ทุกหน้า

    นี่คือเหตุผลที่ต้องมี index บางส่วนบน (status='planned') ใน migration
    เพราะ query นี้วิ่งทุกครั้งที่เปิดหน้าใดก็ตาม
    """
    row = fetchone(conn, """
        SELECT COUNT(*) AS n FROM activities
         WHERE NOT is_deleted AND status = 'planned'
           AND carry_over AND planned_date < CURRENT_DATE
    """)
    return row["n"]


# หน้าหลักที่ปุ่ม "ย้อนกลับ" ในหน้ารายละเอียดกิจกรรมจะพากลับไป
# เก็บเป็น path ตรงตัว (ไม่ใช่ startswith) เพื่อไม่ให้หน้าลูกอย่าง /plans/3/edit
# ถูกจำเป็นหน้าหลักไปด้วย — กดย้อนกลับแล้วต้องไม่เด้งเข้าฟอร์มแก้ไข
MAIN_PAGES = {
    "/next": "งานต่อไป",
    "/calendar": "ปฏิทิน",
    "/history": "ประวัติและสรุป",
    "/plans": "แผนงานประจำ",
}


def page(request: Request, user: dict, name: str, conn=None, **ctx) -> HTMLResponse:
    """render หน้าพร้อมข้อมูลที่ทุกหน้าต้องมี

    ส่ง conn ที่เปิดอยู่แล้วเข้ามาได้เพื่อไม่ต้องยืม connection จาก pool ซ้ำ
    """
    base = {"request": request, "user": user}

    # จำหน้าหลักล่าสุดไว้ใน session เพื่อให้หน้ารายละเอียดกิจกรรมมีปุ่มย้อนกลับ
    # ที่พากลับไป "ที่เดิม" ได้จริง — เก็บ query string ไปด้วย ปฏิทินจะได้กลับไป
    # เดือนและตัวกรองเดิม ไม่ใช่เด้งไปเดือนปัจจุบัน
    #
    # ใช้ session ไม่ใช่ header Referer เพราะหลังกดเริ่ม/จบงาน หน้าจะ redirect
    # กลับมาที่รายละเอียดอีกรอบ Referer จะกลายเป็นหน้ารายละเอียดเอง
    # แล้วปุ่มย้อนกลับจะวนอยู่กับที่
    here = request.url.path
    if here in MAIN_PAGES:
        q = request.url.query
        request.session["back_url"] = here + (f"?{q}" if q else "")
        request.session["back_label"] = MAIN_PAGES[here]
    base["back_url"] = request.session.get("back_url", "/calendar")
    base["back_label"] = request.session.get("back_label", MAIN_PAGES["/calendar"])
    if conn is not None:
        base["overdue_n"] = overdue_count(conn)
        base["duty_short_n"] = _duty_short_count(conn, user)
    else:
        with get_conn() as c:
            base["overdue_n"] = overdue_count(c)
            base["duty_short_n"] = _duty_short_count(c, user)
    return templates.TemplateResponse(name, {**base, **ctx})


def _duty_short_count(conn, user: dict) -> int:
    """ป้ายเลข "จุดที่จะขาดคน" ข้างเมนูหน้าที่ประจำ — เฉพาะคนที่เห็นเมนูนั้น (manager ขึ้นไป)

    ตารางเล็ก (จุดงานไม่กี่จุด × 30 วัน) จึงคำนวณสดทุกหน้าได้เหมือนป้ายงานค้าง
    """
    if user.get("role") not in ("admin", "manager"):
        return 0
    return staffing.shortfall_post_count(conn)
