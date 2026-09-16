"""main.py — RPF Calendar · ปฏิทินวางแผนงานฟาร์ม"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from config import (BASE_DIR, ONLINE, SESSION_HTTPS_ONLY, SESSION_MAX_AGE,
                    SESSION_SECRET, check_session_secret)
from database import close_pool, init_pool
from routers import sync_admin
from routers import (activities, calendar, history, leaves, master, next_work, plans,
                     users)
from routers import auth as auth_router
from services.scheduler import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    problem = check_session_secret()
    if problem and ONLINE:
        # เปิดออกอินเทอร์เน็ตด้วยกุญแจที่เดาได้ = ใครก็เข้ามาเป็นผู้ดูแลระบบได้
        # ยอมให้โปรแกรมไม่ขึ้นดีกว่าปล่อยให้เปิดทิ้งไว้ทั้งที่ไม่ปลอดภัย
        raise RuntimeError(problem)
    if problem:
        logging.getLogger("security").warning("%s", problem)

    init_pool()
    # ตัวสร้างกิจกรรมของแผนงานประจำ — รันครั้งแรกตอนนี้ แล้วซ้ำทุกวันตอนตี 0:05
    await scheduler.start()
    yield
    await scheduler.stop()
    close_pool()


app = FastAPI(title="RPF Calendar", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    # ดู SESSION_HTTPS_ONLY ใน config.py — Tailscale ธรรมดาใช้ http จึงต้องปิดไว้
    https_only=SESSION_HTTPS_ONLY,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_router.router)
app.include_router(next_work.router)
app.include_router(calendar.router)
app.include_router(plans.router)          # prefix /plans
app.include_router(history.router)        # prefix /history
app.include_router(activities.router)   # prefix /activities มาในไฟล์เองแล้ว
app.include_router(master.router)       # prefix /master
app.include_router(leaves.router)       # prefix /leaves (v2 เฟส B)
app.include_router(users.router)        # prefix /settings/users
app.include_router(sync_admin.router)   # prefix /settings/sync


@app.exception_handler(StarletteHTTPException)
async def friendly_errors(request: Request, exc: StarletteHTTPException):
    """แสดงหน้าอธิบายแทน JSON ดิบ เมื่อผู้ใช้เปิดหน้าที่ไม่มีสิทธิ์

    require_login ใช้ HTTPException 303 พร้อม Location เพื่อพาไปหน้าล็อกอิน
    จึงต้องปล่อยผ่านไม่แตะ
    """
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)

    from auth import get_current_user
    from view import page

    user = get_current_user(request)
    if user is None or exc.status_code not in (403, 404):
        return await http_exception_handler(request, exc)

    known = {
        403: ("ไม่มีสิทธิ์ทำรายการนี้", "🔒", exc.detail),
        404: ("ไม่พบหน้านี้", "🧭", "ลิงก์อาจพิมพ์ผิด หรือรายการนี้ถูกลบไปแล้ว"),
    }
    title, icon, message = known[exc.status_code]
    response = page(request, user, "error.html", title=title, icon=icon, message=message)
    response.status_code = exc.status_code
    return response


@app.get("/settings")
def settings_hub(request: Request):
    """หน้ารวมทางเข้าการตั้งค่า — ปุ่ม "ตั้งค่า" บนแถบล่างของมือถือมาที่นี่

    บนจอใหญ่เข้าถึงแต่ละหน้าจาก sidebar ได้ตรงๆ อยู่แล้ว หน้านี้จึงมีไว้
    เพื่อให้มือถือมีทางเข้าเดียวที่รวมทุกอย่างไว้ ไม่ต้องเปิดเมนูข้าง
    """
    from auth import require_login
    from view import page

    user = require_login(request)
    return page(request, user, "settings.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """เสิร์ฟ service worker จากรากของเว็บ ไม่ใช่จาก /static/

    ขอบเขตที่ service worker คุมได้ = โฟลเดอร์ที่มันถูกเสิร์ฟออกมา ถ้าปล่อยให้
    โหลดจาก /static/sw.js มันจะคุมได้แค่ /static/** ซึ่งไม่ครอบ start_url
    ของ manifest (/calendar) แล้ว Chrome บน Android จะไม่ถือว่าติดตั้งได้
    ปุ่ม "ติดตั้งแอป" จึงไม่ขึ้น

    ตัวไฟล์ยังเก็บไว้ที่ static/sw.js ตามปกติ ที่นี่แค่เปลี่ยน URL ที่เสิร์ฟออกไป

    no-cache เพื่อให้เบราว์เซอร์เห็นตัวใหม่ทันทีที่แก้ — ไฟล์นี้ต่อ ?v= ไม่ได้
    เพราะ URL ของมันคือตัวระบุตัวตนที่เบราว์เซอร์ใช้จำว่าลงทะเบียนอะไรไว้
    ถ้า URL เปลี่ยน จะกลายเป็น service worker คนละตัวและตัวเก่าไม่มีวันถูกถอน

    ไม่ต้องล็อกอิน — เบราว์เซอร์ดึงไฟล์นี้เองก่อนที่ผู้ใช้จะล็อกอิน
    ไม่มีข้อมูลอะไรอยู่ในไฟล์ (ดูเนื้อในได้ที่ static/sw.js)
    """
    from fastapi.responses import FileResponse

    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/")
def root(request: Request):
    from auth import get_current_user

    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/calendar", status_code=303)


# หน้า "งานวันนี้" / "งานที่จะถึง" ถูกยุบเป็น "งานต่อไป" แล้วภายหลังก็ถอดเมนูออก
# เพราะกล่องข้างของปฏิทินมีทั้งงานต่อไปและงานค้างอยู่แล้ว
# เก็บ redirect ไว้เพราะผู้ใช้อาจบุ๊กมาร์กลิงก์เก่าไว้ตั้งแต่รุ่นก่อนๆ
@app.get("/today")
@app.get("/upcoming")
def moved_to_calendar(request: Request):
    return RedirectResponse("/calendar", status_code=303)
