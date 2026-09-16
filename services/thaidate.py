"""services/thaidate.py — จัดรูปวันที่/เวลาเป็นภาษาไทย

รวมไว้ที่เดียวเพื่อให้ทุกหน้าจอเขียนวันที่แบบเดียวกัน
ปีที่แสดงเป็น พ.ศ. ตามที่ใช้กันในฟาร์ม แต่ในฐานข้อมูลเก็บเป็น ค.ศ. เสมอ
"""
from datetime import date, datetime, time, timedelta

from config import THAI_TZ

MONTHS_FULL = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")
MONTHS_SHORT = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")
# เรียงตาม weekday() ของ Python คือ 0 = จันทร์
WEEKDAYS_FULL = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")
WEEKDAYS_SHORT = ("จ", "อ", "พ", "พฤ", "ศ", "ส", "อา")


def today() -> date:
    """วันนี้ตามเวลาไทย — ห้ามใช้ date.today() ตรงๆ ที่อื่น

    ถ้าเซิร์ฟเวอร์ตั้ง timezone เป็น UTC วันจะเปลี่ยนตอน 7 โมงเช้าบ้านเรา
    แล้ว "งานของวันนี้" จะสลับวันกลางวันแสกๆ
    """
    return datetime.now(THAI_TZ).date()


def now() -> datetime:
    return datetime.now(THAI_TZ)


def local_date(dt: datetime | None) -> date | None:
    """วันตามเวลาไทยของ timestamptz — ห้ามใช้ `dt.date()` ตรงๆ

    ค่าใน DB เก็บเป็น timestamptz ถ้าเรียก .date() โดยไม่แปลงเขตเวลาก่อน
    งานที่กดตอนหัวค่ำจะกลายเป็นวันถัดไปทันทีเมื่อเซิร์ฟเวอร์เป็น UTC
    """
    return None if dt is None else dt.astimezone(THAI_TZ).date()


def parse_iso(value: str | None) -> date | None:
    """อ่านวันที่รูปแบบ YYYY-MM-DD จาก URL — คืน None ถ้าอ่านไม่ได้

    คืน None แทนการโยน error เพราะค่านี้มาจาก URL ที่ผู้ใช้พิมพ์เองได้
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def span(start: date, end: date) -> str:
    """ข้อความช่วงวัน — งานวันเดียวแสดงวันเดียว"""
    if start == end:
        return long(start)
    return f"{short(start)} – {short(end)} ({(end - start).days + 1} วัน)"


def short(d: date | None) -> str:
    """8 ส.ค. 68"""
    if d is None:
        return "-"
    return f"{d.day} {MONTHS_SHORT[d.month - 1]} {(d.year + 543) % 100:02d}"


def long(d: date | None) -> str:
    """ศุกร์ที่ 8 สิงหาคม 2568"""
    if d is None:
        return "-"
    return (f"{WEEKDAYS_FULL[d.weekday()]}ที่ {d.day} "
            f"{MONTHS_FULL[d.month - 1]} {d.year + 543}")


def month_year(d: date) -> str:
    """สิงหาคม 2568"""
    return f"{MONTHS_FULL[d.month - 1]} {d.year + 543}"


def relative_day(d: date) -> str:
    """วันนี้ / พรุ่งนี้ / เมื่อวาน / ชื่อวัน — ใช้เป็นหัวข้อกลุ่มในรายการงาน"""
    delta = (d - today()).days
    if delta == 0:
        return "วันนี้"
    if delta == 1:
        return "พรุ่งนี้"
    if delta == -1:
        return "เมื่อวาน"
    if 2 <= delta <= 6:
        return f"วัน{WEEKDAYS_FULL[d.weekday()]}"
    return short(d)


def hhmm(t: time | None) -> str:
    if t is None:
        return ""
    return f"{t.hour:02d}:{t.minute:02d}"


def stamp(dt: datetime | None) -> str:
    """8 ส.ค. 68 14:30 — สำหรับ timeline ประวัติ"""
    if dt is None:
        return "-"
    local = dt.astimezone(THAI_TZ)
    return f"{short(local.date())} {local.hour:02d}:{local.minute:02d}"


def duration(minutes: int | None) -> str:
    """90 → 1 ชม. 30 น."""
    if minutes is None:
        return ""
    if minutes < 60:
        return f"{minutes} นาที"
    hours, mins = divmod(minutes, 60)
    return f"{hours} ชม." + (f" {mins} น." if mins else "")


def time_range(start: time | None, end: time | None, minutes: int | None) -> str:
    """สร้างข้อความช่วงเวลาที่อ่านง่ายจากข้อมูลเท่าที่มี"""
    if start and end:
        return f"{hhmm(start)} – {hhmm(end)}"
    if start and minutes:
        return f"{hhmm(start)} ({duration(minutes)})"
    if start:
        return hhmm(start)
    if minutes:
        return f"ใช้เวลา {duration(minutes)}"
    return "ทั้งวัน"


def add_months(d: date, months: int) -> date:
    """เลื่อนเดือนโดยหนีบวันที่ให้อยู่ในเดือนปลายทาง (31 ม.ค. + 1 เดือน = 28/29 ก.พ.)"""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))
