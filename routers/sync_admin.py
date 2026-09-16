"""routers/sync_admin.py — หน้าจัดการแหล่งข้อมูลที่ปฏิทินไปดึงมา

ปฏิทินเป็นฝ่ายดึงเสมอ (ดูกติกาใน sync/runner.py) หน้านี้จึงเป็นที่เดียว
ที่สั่งดึงได้ ทั้งแบบกดเอง และดูผลว่ารอบล่าสุดทำอะไรไปบ้าง
"""
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from auth import require_role
from database import execute, fetchall, fetchone, get_conn
from sync import runner, sources
from view import page

router = APIRouter(prefix="/settings/sync")


@router.get("")
def sync_page(request: Request, ok: str = "", err: str = ""):
    user = require_role(request, "manager")
    with get_conn() as conn:
        rows = fetchall(conn, """
            SELECT s.*, c.name AS category_name
              FROM sync_sources s
              LEFT JOIN activity_categories c ON c.id = s.category_id
             ORDER BY s.name
        """)
        # แหล่งที่มี adapter ในโค้ดแล้วแต่ยังไม่มีแถวใน DB — ให้เห็นว่าเปิดใช้ได้
        known = {r["code"] for r in rows}
        available = [{"code": s.code, "name": s.name}
                     for s in sources.SOURCES.values() if s.code not in known]
        runs = fetchall(conn, """
            SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 20
        """)
        categories = fetchall(conn, "SELECT id, name FROM activity_categories WHERE active ORDER BY sort_order")
        return page(request, user, "settings_sync.html", conn=conn,
                    rows=rows, available=available, runs=runs, categories=categories)


@router.post("/register/{code}")
async def register(request: Request, code: str):
    """สร้างแถว sync_sources ให้ adapter ที่มีอยู่ในโค้ด แล้วเลือกหมวดกิจกรรม"""
    require_role(request, "manager")
    src = sources.get(code)
    if src is None:
        return _back(err="ไม่รู้จักแหล่งข้อมูลนี้")

    form = await request.form()
    category_id = form.get("category_id") or None
    with get_conn() as conn:
        execute(conn, """
            INSERT INTO sync_sources (code, name, enabled, category_id)
            VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (code) DO UPDATE SET category_id = EXCLUDED.category_id
        """, (src.code, src.name, int(category_id) if category_id else None))
    return _back(ok=f"เปิดใช้ {src.name} แล้ว")


@router.post("/{source_id}/toggle")
def toggle(request: Request, source_id: int):
    require_role(request, "manager")
    with get_conn() as conn:
        execute(conn, "UPDATE sync_sources SET enabled = NOT enabled WHERE id = %s", (source_id,))
    return _back(ok="เปลี่ยนสถานะแล้ว")


@router.post("/{source_id}/run")
def run_now(request: Request, source_id: int):
    """สั่งดึงทันที

    รันซ้ำกี่รอบก็ปลอดภัย — runner ผูกด้วย external_id และเทียบ external_hash
    รายการที่ไม่เปลี่ยนจะถูกนับเป็น skipped ไม่มีอะไรงอกซ้ำ
    """
    user = require_role(request, "manager")
    with get_conn() as conn:
        row = fetchone(conn, "SELECT * FROM sync_sources WHERE id = %s", (source_id,))
        if row is None:
            return _back(err="ไม่พบแหล่งข้อมูล")
        src = sources.get(row["code"])
        if src is None:
            return _back(err=f"ไม่มี adapter สำหรับ {row['code']} ในโค้ด")

        since = date.today() - timedelta(days=row["lookback_days"] or 30)
        config = dict(row["config"] or {})
        config.update({"source_id": row["id"], "category_id": row["category_id"]})

        try:
            stats = runner.run(conn, src, config, since, user)
        except Exception as exc:
            # runner บันทึกความล้มเหลวไว้บน connection แยกให้แล้ว (record_failure)
            # ที่นี่ห้ามเขียนอะไรลง conn อีก — transaction เสียแล้ว คำสั่งต่อไปจะพังซ้ำ
            # แล้วผู้ใช้จะเห็นหน้า error 500 แทนข้อความบอกสาเหตุ
            conn.rollback()
            return _back(err=f"ดึงข้อมูลไม่สำเร็จ: {exc}")

        summary = (f"เพิ่ม {stats['created']} · แก้ {stats['updated']} · "
                   f"ยกเลิก {stats['cancelled']} · เท่าเดิม {stats['skipped']}")
        execute(conn, "UPDATE sync_sources SET last_run_at = NOW(), last_status = %s WHERE id = %s",
                (summary, source_id))
    return _back(ok=f"{src.name}: {summary}")


@router.post("/run-all")
async def run_all(request: Request):
    """ดึงทุกแหล่งที่เปิดใช้อยู่ในคลิกเดียว — สำหรับปุ่มซิงค์บนแถบบนของหน้าปฏิทิน

    แยกจาก /{source_id}/run เพราะปุ่มบนแถบบนไม่ควรบังคับให้ผู้ใช้รู้ว่ามีกี่แหล่ง
    และแหล่งไหนเป็นแหล่งไหน · รันซ้ำปลอดภัยเหมือนกัน (ผูกด้วย external_id)

    `back` รับเฉพาะ path ภายในโปรแกรม กัน open redirect ไปเว็บนอก
    """
    user = require_role(request, "manager")
    # ค่ามาจาก body ของฟอร์ม ไม่ใช่ query string จึงต้องอ่านจาก request.form()
    back = (await request.form()).get("back") or "/calendar"
    target = back if back.startswith("/") and not back.startswith("//") else "/calendar"

    with get_conn() as conn:
        rows = fetchall(conn, "SELECT * FROM sync_sources WHERE enabled ORDER BY name")

    if not rows:
        return _back(err="ยังไม่ได้เปิดใช้แหล่งข้อมูลใด", url=target)

    total = {"created": 0, "updated": 0, "cancelled": 0, "skipped": 0}
    failed: list[str] = []
    for row in rows:
        src = sources.get(row["code"])
        if src is None:
            failed.append(f"{row['name']} (ไม่มี adapter)")
            continue
        since = date.today() - timedelta(days=row["lookback_days"] or 30)
        config = dict(row["config"] or {})
        config.update({"source_id": row["id"], "category_id": row["category_id"]})
        try:
            # แหล่งละ transaction — แหล่งหนึ่งพังต้องไม่ล้มของที่สำเร็จไปแล้ว
            with get_conn() as conn:
                stats = runner.run(conn, src, config, since, user)
                summary = (f"เพิ่ม {stats['created']} · แก้ {stats['updated']} · "
                           f"ยกเลิก {stats['cancelled']} · เท่าเดิม {stats['skipped']}")
                execute(conn, """UPDATE sync_sources SET last_run_at = NOW(), last_status = %s
                                  WHERE id = %s""", (summary, row["id"]))
            for k in total:
                total[k] += stats[k]
        except Exception as exc:
            # runner บันทึกสาเหตุไว้ใน sync_runs บน connection แยกให้แล้ว
            failed.append(f"{row['name']}: {str(exc)[:80]}")

    if failed:
        return _back(err="ดึงข้อมูลไม่สำเร็จบางแหล่ง — " + " · ".join(failed), url=target)
    return _back(ok=f"ซิงค์แล้ว — เพิ่ม {total['created']} · แก้ {total['updated']} · "
                    f"ยกเลิก {total['cancelled']} · เท่าเดิม {total['skipped']}", url=target)


def _back(ok: str = "", err: str = "", url: str = "/settings/sync") -> RedirectResponse:
    # url อาจมี query อยู่แล้ว (ปุ่มซิงค์บนหน้าปฏิทินส่งเดือนที่ดูอยู่กลับมา)
    # ถ้าต่อ "?" ซ้ำ เบราว์เซอร์จะอ่านพารามิเตอร์ไม่ออกทั้งชุด
    sep = "&" if "?" in url else "?"
    if ok:
        url += f"{sep}ok={quote(ok)}"
    elif err:
        url += f"{sep}err={quote(err)}"
    return RedirectResponse(url, status_code=303)
