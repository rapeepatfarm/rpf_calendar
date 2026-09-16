"""forms.py — ตัวช่วยแปลงค่าจากฟอร์ม HTML

ฟอร์มส่งมาเป็นข้อความเสมอ ช่องที่ผู้ใช้เว้นว่างจะมาเป็น "" ไม่ใช่ None
ตัวช่วยชุดนี้แปลง "" ให้เป็น None เพื่อให้เก็บลง DB เป็น NULL ได้ถูกต้อง
"""
from datetime import date, datetime, time
from typing import Annotated

from pydantic import BeforeValidator


def _filter_int(value):
    """ค่าตัวกรองจาก query string — อะไรที่ไม่ใช่ตัวเลขให้ถือว่า "ไม่กรอง"

    ช่องเลือก "ทุกคน / ทุกประเภท" ส่งมาเป็น "" ไม่ใช่ค่าว่างจริง ถ้าไม่ดักไว้
    FastAPI จะพยายามแปลงเป็น int แล้วตอบ 422 พร้อม JSON ดิบเต็มหน้าจอ
    ผู้ใช้เห็นแค่ข้อความอังกฤษยาวๆ โดยไม่รู้ว่าเกิดอะไรขึ้น (เจอจริง 2026-08-27)

    ค่าที่เพี้ยนก็คืน None เหมือนกัน ตามหลักการเดียวกับ `thaidate.parse_iso()` —
    ค่าพวกนี้มาจาก URL ที่ผู้ใช้พิมพ์เองหรือบุ๊กมาร์กเก่าได้ การไม่กรองให้
    ดีกว่าการโยนหน้า error ใส่คนที่แค่อยากดูตาราง
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


# ใช้กับพารามิเตอร์ตัวกรองใน query string ทุกหน้า (ปฏิทิน · งานต่อไป · ประวัติ)
# ประกาศไว้ที่เดียวเพื่อไม่ให้บางหน้าดักค่าว่างแล้วบางหน้าลืมดัก
OptInt = Annotated[int | None, BeforeValidator(_filter_int)]


def as_bool(value: str | None) -> bool:
    return value in ("1", "true", "on", "yes")


def as_int(value: str | None, default: int | None = None) -> int | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def as_text(value: str | None) -> str:
    return (value or "").strip()


def as_date(value: str | None) -> date | None:
    value = as_text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def as_time(value: str | None) -> time | None:
    """<input type=time> ส่งมาเป็น HH:MM หรือ HH:MM:SS แล้วแต่เบราว์เซอร์"""
    value = as_text(value)
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def as_priority(value: str | None) -> int:
    priority = as_int(value, 3) or 3
    return min(4, max(1, priority))
