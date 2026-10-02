"""routers/plans.py — แผนงานประจำ (กิจกรรมที่ทำซ้ำ)

ฟาร์มนี้ใช้รายเดือนและรายปีเป็นหลัก ตัวเลือกในฟอร์มจึงเรียงสองแบบนั้นขึ้นก่อน
"""
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from auth import can_manage, require_role
from database import execute, fetchall, fetchone, get_conn
from forms import as_bool, as_date, as_int, as_priority, as_text, as_time
from services import recurrence, scheduler, thaidate
from view import page

router = APIRouter(prefix="/plans")


def _back(ok: str = "", err: str = "") -> RedirectResponse:
    url = "/plans"
    if ok:
        url += f"?ok={quote(ok)}"
    elif err:
        url += f"?err={quote(err)}"
    return RedirectResponse(url, status_code=303)


def _master(conn) -> dict:
    staff = fetchall(conn, """
        SELECT s.id, s.name, p.name AS position, COALESCE(p.can_assign, TRUE) AS can_assign
          FROM staff s LEFT JOIN positions p ON p.id = s.position_id
         WHERE s.active ORDER BY s.sort_order, s.name
    """)
    return {
        "staff": staff,
        # เกณฑ์เดียวกับฟอร์มกิจกรรม: ตัดตำแหน่งที่ตั้งว่าไม่รับผิดชอบงานออก
        "leads": [x for x in staff if x["can_assign"]] or staff,
        "categories": fetchall(conn, "SELECT id, name, color FROM activity_categories "
                                     "WHERE active ORDER BY sort_order, name"),
    }


def _load(conn, series_id: int) -> dict:
    row = fetchone(conn, "SELECT * FROM activity_series WHERE id = %s", (series_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบแผนงานนี้")
    return row


def _add_next_rounds(row: dict) -> None:
    """เติม "รอบถัดไป" ให้หน้ารายการแผนงาน — สองรอบข้างหน้า ไม่ใช่รอบเดียว

    ผู้ใช้ขอ (2026-10-02) ให้เห็นรอบถัดไปด้วย "ถึงแม้จะเป็นแค่แผน" · เหตุที่ขอเพราะ
    โหมด `after_done` วางล่วงหน้าได้ครั้งละรอบเดียว (วันของรอบถัดไปขึ้นกับว่ารอบนี้เสร็จเมื่อไร)
    เปิดหน้านี้มาจึงเห็นแค่รอบเดียวแล้วไม่รู้ว่าถัดไปประมาณไหน

      · โหมด fixed      → รอบถัดจากนั้นมีอยู่จริงในตารางแล้ว เอามาแสดงตรงๆ
      · โหมด after_done → ยังไม่มีของจริง จึง **ประมาณการ** จากวันจบของรอบที่ค้างอยู่
                          + คาบของแผน แล้วติดธง `after_next_guess` ให้หน้าจอบอกว่าเป็นค่าประมาณ
                          (ถ้าโชว์เฉยๆ โดยไม่บอก จะกลายเป็นสัญญาว่าจะเกิดวันนั้นแน่ๆ ซึ่งไม่จริง)
    """
    row["next_on"] = row.get("next_on") or row.get("open_on")   # รอบค้างก็ถือเป็นรอบถัดไป
    row["next_late"] = bool(row.get("open_on") and row["open_on"] < thaidate.today())
    row["after_next_guess"] = False

    if row.get("after_next_on") or not row["active"]:
        return
    if row.get("anchor_mode") != recurrence.ANCHOR_AFTER_DONE:
        return
    anchor = row.get("open_end") or row.get("open_on")
    if not anchor:
        return
    row["after_next_on"] = recurrence.next_after(row, anchor, row.get("made_n") or 0)
    row["after_next_guess"] = True


@router.get("")
def plans_page(request: Request, ok: str = "", err: str = ""):
    user = require_role(request, "manager")
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT s.*, c.name AS category_name, c.color AS category_color,
                   st.name AS assignee_name,
                   (SELECT COUNT(*) FROM activities a
                     WHERE a.series_id = s.id AND NOT a.is_deleted) AS made_n,
                   (SELECT MIN(a.planned_date) FROM activities a
                     WHERE a.series_id = s.id AND NOT a.is_deleted
                       AND a.status = 'planned' AND a.planned_date >= CURRENT_DATE) AS next_on,
                   -- รอบที่ยังไม่ปิดที่เร็วที่สุด "รวมของที่เลยกำหนดมาแล้ว" — คอลัมน์ข้างบน
                   -- ตัดของค้างทิ้ง ทำให้แผนที่มีรอบค้างอยู่ขึ้นว่าไม่มีครั้งถัดไป ทั้งที่มี
                   (SELECT MIN(a.planned_date) FROM activities a
                     WHERE a.series_id = s.id AND NOT a.is_deleted
                       AND a.status IN ('planned', 'in_progress')) AS open_on,
                   (SELECT MIN(a.planned_end_date) FROM activities a
                     WHERE a.series_id = s.id AND NOT a.is_deleted
                       AND a.status IN ('planned', 'in_progress')) AS open_end,
                   -- รอบถัดจากรอบที่ใกล้ที่สุด (โหมด fixed วางล่วงหน้าไว้แล้วจึงมีของจริง)
                   (SELECT MIN(a.planned_date) FROM activities a
                     WHERE a.series_id = s.id AND NOT a.is_deleted AND a.status = 'planned'
                       AND a.planned_date > (
                            SELECT MIN(b.planned_date) FROM activities b
                             WHERE b.series_id = s.id AND NOT b.is_deleted
                               AND b.status IN ('planned', 'in_progress'))) AS after_next_on
              FROM activity_series s
              LEFT JOIN activity_categories c ON c.id = s.category_id
              LEFT JOIN staff st ON st.id = s.assignee_id
             ORDER BY s.active DESC, s.title
        """)
        for row in rows:
            row["rule_text"] = recurrence.describe(row)
            _add_next_rounds(row)
        return page(request, user, "plans.html", conn=conn, rows=rows, **_master(conn))


@router.get("/new")
def new_form(request: Request):
    user = require_role(request, "manager")
    with get_conn() as conn:
        return page(request, user, "plan_form.html", conn=conn,
                    series=None, default_date=thaidate.today(),
                    freq_order=recurrence.FREQ_ORDER,
                    freq_labels=recurrence.FREQ_LABELS, **_master(conn))


@router.get("/{series_id}/edit")
def edit_form(request: Request, series_id: int):
    user = require_role(request, "manager")
    with get_conn() as conn:
        series = _load(conn, series_id)
        series["helper_ids"] = [r["staff_id"] for r in fetchall(
            conn, "SELECT staff_id FROM series_helpers WHERE series_id = %s", (series_id,))]
        return page(request, user, "plan_form.html", conn=conn,
                    series=series, default_date=series["starts_on"],
                    freq_order=recurrence.FREQ_ORDER,
                    freq_labels=recurrence.FREQ_LABELS, **_master(conn))


def _form_data(form) -> dict:
    all_day = as_bool(form.get("is_all_day"))
    weekdays = [as_int(v) for v in form.getlist("byweekday")]
    return {
        "title": as_text(form.get("title")),
        "category_id": as_int(form.get("category_id")),
        "description": as_text(form.get("description")),
        "assignee_id": as_int(form.get("assignee_id")),
        "priority": as_priority(form.get("priority")),
        "is_all_day": all_day,
        "start_time": None if all_day else as_time(form.get("start_time")),
        "duration_min": None if all_day else as_int(form.get("duration_min")),
        "duration_days": max(1, min(366, as_int(form.get("duration_days"), 1) or 1)),

        "anchor_mode": (recurrence.ANCHOR_AFTER_DONE
                        if as_bool(form.get("anchor_after_done"))
                        else recurrence.ANCHOR_FIXED),
        "freq": form.get("freq") or "monthly_day",
        "interval": max(1, as_int(form.get("interval"), 1) or 1),
        "byweekday": [d for d in weekdays if d is not None] or None,
        "bymonthday": as_int(form.get("bymonthday")),
        "nth_week": as_int(form.get("nth_week")),
        "nth_weekday": as_int(form.get("nth_weekday")),
        "bymonth": as_int(form.get("bymonth")),
        "byday": as_int(form.get("byday")),
        "starts_on": as_date(form.get("starts_on")),
        "ends_on": as_date(form.get("ends_on")),
        "max_count": as_int(form.get("max_count")),

        "carry_over": as_bool(form.get("carry_over")),
        "auto_skip_after_days": as_int(form.get("auto_skip_after_days")),
        "active": as_bool(form.get("active")),
    }


def _helper_ids(form) -> list[int]:
    return [i for i in (as_int(v) for v in form.getlist("helper_ids")) if i]


def _set_series_helpers(conn, series_id: int, staff_ids: list[int]):
    execute(conn, "DELETE FROM series_helpers WHERE series_id = %s", (series_id,))
    for staff_id in dict.fromkeys(staff_ids):
        execute(conn, "INSERT INTO series_helpers (series_id, staff_id) VALUES (%s, %s) "
                      "ON CONFLICT DO NOTHING", (series_id, staff_id))


def _problem(data: dict) -> str | None:
    if not data["title"]:
        return "ต้องกรอกชื่องาน"
    if not data["starts_on"]:
        return "ต้องกรอกวันเริ่มแผน"
    if data["freq"] not in recurrence.FREQ_LABELS:
        return "รูปแบบการทำซ้ำไม่ถูกต้อง"
    if data["ends_on"] and data["ends_on"] < data["starts_on"]:
        return "วันสิ้นสุดแผนต้องไม่มาก่อนวันเริ่ม"
    if data["freq"] == "weekly" and not data["byweekday"]:
        return "แผนรายสัปดาห์ต้องเลือกวันในสัปดาห์อย่างน้อย 1 วัน"
    return None


_FIELDS = ("title", "category_id", "description", "assignee_id", "priority",
           "is_all_day", "start_time", "duration_min", "duration_days",
           "anchor_mode", "freq", "interval", "byweekday", "bymonthday", "nth_week", "nth_weekday",
           "bymonth", "byday", "starts_on", "ends_on", "max_count",
           "carry_over", "auto_skip_after_days", "active")


@router.post("/new")
async def create(request: Request):
    user = require_role(request, "manager")
    form = await request.form()
    data = _form_data(form)
    problem = _problem(data)
    if problem:
        return _back(err=problem)

    columns = ", ".join(_FIELDS)
    placeholders = ", ".join(f"%({name})s" for name in _FIELDS)
    with get_conn() as conn:
        row = fetchone(conn, f"""
            INSERT INTO activity_series ({columns}, created_by, updated_by)
            VALUES ({placeholders}, %(user_id)s, %(user_id)s) RETURNING id
        """, {**data, "user_id": user["id"]})
        _set_series_helpers(conn, row["id"], _helper_ids(form))
        series = _load(conn, row["id"])
        made = scheduler.generate_series(conn, series, scheduler.horizon(conn))
        first = fetchone(conn, """
            SELECT MIN(planned_date) AS d FROM activities
             WHERE series_id = %s AND NOT is_deleted AND status = 'planned'
        """, (row["id"],))
    when = f" · ครั้งแรก {thaidate.short(first['d'])}" if first and first["d"] else ""
    return _back(ok=f"สร้างแผนงาน \"{data['title']}\" แล้ว — "
                    f"วางกิจกรรมล่วงหน้าไว้ {made} ครั้ง{when}")


@router.post("/{series_id}/edit")
async def edit(request: Request, series_id: int):
    """แก้แผนงาน แล้วสร้างกิจกรรมในอนาคตใหม่ตามกติกาใหม่

    ลบเฉพาะกิจกรรมอนาคตที่ **ยังไม่มีใครแตะ** เท่านั้น
    งานที่กดเริ่ม/จบ/ยกเลิกไปแล้วห้ามยุ่ง เพราะเป็นประวัติการทำงานจริง
    """
    user = require_role(request, "manager")
    form = await request.form()
    data = _form_data(form)
    problem = _problem(data)
    if problem:
        return _back(err=problem)

    assignments = ", ".join(f"{name} = %({name})s" for name in _FIELDS)
    with get_conn() as conn:
        _load(conn, series_id)
        execute(conn, f"""
            UPDATE activity_series SET {assignments},
                   generated_until = NULL, updated_at = NOW(), updated_by = %(user_id)s
             WHERE id = %(id)s
        """, {**data, "id": series_id, "user_id": user["id"]})

        _set_series_helpers(conn, series_id, _helper_ids(form))
        # ลบ "ตั้งแต่วันนี้เป็นต้นไป" ไม่ใช่ "หลังวันนี้"
        #
        # ของเดิมใช้ > CURRENT_DATE รอบที่ตกวันนี้จึงรอด แล้วเกิดอาการที่ผู้ใช้เจอ
        # (2026-10-02): แก้แผนเปลี่ยนวันเริ่มกับชื่อ แต่ปฏิทินยังโชว์วันเก่าชื่อเก่า
        # เพราะโหมด after_done เห็นว่ามีรอบที่ยังไม่ปิดค้างอยู่แล้วเลยไม่สร้างรอบใหม่
        # ส่วนโหมด fixed ก็ได้รอบเก่าค้างปนกับรอบใหม่
        #
        # รอบของ "วันนี้" ที่ยังไม่มีใครแตะเลยถือเป็นแค่แผน ต้องเดินตามแผนที่เพิ่งแก้
        # แต่ **รอบที่เลยมาแล้วยังไม่ปิดห้ามแตะ** — นั่นคืองานค้างจริงที่ต้องตามเก็บ
        removed = execute(conn, """
            DELETE FROM activities
             WHERE series_id = %s AND planned_date >= CURRENT_DATE
               AND status = 'planned' AND started_at IS NULL
               AND result_note = '' AND NOT is_deleted
        """, (series_id,))
        made = scheduler.generate_series(conn, _load(conn, series_id),
                                         scheduler.horizon(conn))
    return _back(ok=f"บันทึกแผนงานแล้ว — วางกิจกรรมใหม่ {made} ครั้ง "
                    f"(แทนของเดิมที่ยังไม่ได้เริ่ม {removed} ครั้ง)")


@router.post("/{series_id}/toggle")
def toggle(request: Request, series_id: int):
    """เปิด/ปิดแผนงาน — ปิดแล้วลบกิจกรรมอนาคตที่ยังไม่ได้เริ่มออกจากปฏิทิน"""
    require_role(request, "manager")
    with get_conn() as conn:
        series = _load(conn, series_id)
        active = not series["active"]
        execute(conn, "UPDATE activity_series SET active = %s, updated_at = NOW() WHERE id = %s",
                (active, series_id))
        if active:
            made = scheduler.generate_series(conn, _load(conn, series_id),
                                             scheduler.horizon(conn))
            return _back(ok=f"เปิดแผนงานแล้ว — วางกิจกรรมล่วงหน้า {made} ครั้ง")
        removed = execute(conn, """
            DELETE FROM activities
             WHERE series_id = %s AND planned_date > CURRENT_DATE
               AND status = 'planned' AND started_at IS NULL AND result_note = ''
        """, (series_id,))
    return _back(ok=f"ปิดแผนงานแล้ว — เอากิจกรรมอนาคตออกจากปฏิทิน {removed} ครั้ง")


@router.post("/{series_id}/delete")
def delete(request: Request, series_id: int):
    """ลบแผนงาน — กิจกรรมที่เคยทำไปแล้วยังอยู่ในปฏิทินเป็นประวัติ

    FK ของ activities.series_id เป็น ON DELETE SET NULL กิจกรรมเก่าจึงไม่หายตาม
    """
    user = require_role(request, "manager")
    if not can_manage(user):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ลบแผนงาน")
    with get_conn() as conn:
        series = _load(conn, series_id)
        removed = execute(conn, """
            DELETE FROM activities
             WHERE series_id = %s AND planned_date > CURRENT_DATE
               AND status = 'planned' AND started_at IS NULL AND result_note = ''
        """, (series_id,))
        execute(conn, "DELETE FROM activity_series WHERE id = %s", (series_id,))
    return _back(ok=f"ลบแผนงาน \"{series['title']}\" แล้ว — "
                    f"เอากิจกรรมอนาคตออก {removed} ครั้ง ส่วนงานที่ทำไปแล้วยังอยู่")


@router.post("/run")
def run_generator(request: Request):
    """สั่งสร้างกิจกรรมล่วงหน้าเดี๋ยวนี้ — **ไม่มีปุ่มบนหน้าจอแล้ว**

    เอาปุ่มออกเพราะซ้ำซ้อน: scheduler สร้างให้เองทั้งตอนเปิดโปรแกรมและทุกวันตอนตี 0:05
    และผู้ใช้สับสนกับปุ่ม "เพิ่มแผนงาน" · เก็บ endpoint ไว้เป็นทางกู้กรณี
    scheduler ไม่ทำงาน — เรียกด้วย POST /plans/run จากเครื่องที่ล็อกอินเป็นหัวหน้างาน
    """
    require_role(request, "manager")
    result = scheduler.run_once()
    return _back(ok=f"สร้างกิจกรรมใหม่ {result['created']} รายการ · "
                    f"ปิดงานค้างเกินกำหนด {result['closed']} รายการ")
