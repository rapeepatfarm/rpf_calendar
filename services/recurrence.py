"""services/recurrence.py — แปลงกติกาการทำซ้ำเป็นรายการวัน + คำบรรยายภาษาไทย

ฟาร์มนี้ใช้ **รายเดือนและรายปีเป็นหลัก** ส่วนรายวัน/รายสัปดาห์ตั้งใจไม่ค่อยใช้
เพราะจะทำให้กิจกรรมล้นปฏิทิน · โค้ดจึงให้ความสำคัญกับความถูกต้องของสองแบบแรกก่อน
โดยเฉพาะกรณีขอบเรื่องวันสิ้นเดือนที่พลาดง่ายและไม่มีอะไรเตือน

เขียนเองไม่พึ่ง dateutil เพราะกติกาที่ต้องการมีแค่ 5 แบบ และสองแบบสำคัญที่สุด
(วันที่ 31 ของเดือน / 29 ก.พ. รายปี) ต้อง "หนีบเข้าวันสุดท้ายของเดือน"
ซึ่ง rrule มาตรฐานจะ **ข้ามเดือนนั้นทิ้ง** แทน — ผิดจากที่ฟาร์มต้องการ
"""
from calendar import monthrange
from datetime import date, timedelta

from services.thaidate import MONTHS_FULL, WEEKDAYS_FULL, add_months, short

FREQ_LABELS = {
    "monthly_day": "รายเดือน (ตามวันที่)",
    "monthly_nth": "รายเดือน (ตามสัปดาห์)",
    "yearly": "รายปี",
    "weekly": "รายสัปดาห์",
    "daily": "รายวัน",
}
# เรียงตามที่ฟาร์มใช้จริง — รายเดือน/รายปีขึ้นก่อนในเมนู
FREQ_ORDER = ("monthly_day", "monthly_nth", "yearly", "weekly", "daily")

NTH_LABELS = {1: "แรก", 2: "ที่ 2", 3: "ที่ 3", 4: "ที่ 4", -1: "สุดท้าย"}

# วิธีนับว่ารอบถัดไปตกวันไหน
ANCHOR_FIXED = "fixed"            # ยึดวันตายตัวตามปฏิทิน
ANCHOR_AFTER_DONE = "after_done"  # นับจากวันที่ทำเสร็จจริง + ระยะเวลา
ANCHOR_LABELS = {
    ANCHOR_FIXED: "ยึดวันตามปฏิทิน",
    ANCHOR_AFTER_DONE: "นับจากวันที่ทำเสร็จจริง",
}

# กันไม่ให้กติกาที่ตั้งผิด (เช่น interval 0) วนไม่รู้จบจนโปรแกรมค้าง
MAX_OCCURRENCES = 2000


def last_day(year: int, month: int) -> int:
    return monthrange(year, month)[1]


def clamp_day(year: int, month: int, day: int) -> date:
    """วันที่ N ของเดือน โดยหนีบเข้าวันสุดท้ายถ้าเดือนนั้นสั้นกว่า

    31 ในเดือนกุมภาพันธ์ = 28 หรือ 29 · ไม่ใช่ข้ามเดือนนั้นไป
    ฟาร์มสั่งงาน "ทุกสิ้นเดือน" ด้วยการตั้งวันที่ 31 จึงต้องมีทุกเดือนจริงๆ
    """
    return date(year, month, min(day, last_day(year, month)))


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """เช่น จันทร์ที่ 2 ของเดือน (weekday=0, nth=2) · nth=-1 คือตัวสุดท้าย"""
    if nth == -1:
        last = date(year, month, last_day(year, month))
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (nth - 1) * 7
    if day > last_day(year, month):
        # เช่น "ศุกร์ที่ 5" ในเดือนที่มีศุกร์แค่ 4 ครั้ง — เดือนนั้นไม่มีรอบ
        return None
    return date(year, month, day)


def _month_steps(start: date, interval: int, until: date):
    """ไล่เดือนทีละ interval ตั้งแต่เดือนของ start จนถึงเดือนของ until"""
    year, month = start.year, start.month
    while date(year, month, 1) <= until:
        yield year, month
        month += interval
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1


def occurrences(series: dict, until: date, since: date | None = None) -> list[date]:
    """คืนรายการวันที่ต้องสร้างกิจกรรม ตั้งแต่ starts_on ถึง until

    since ใช้ตอนสร้างเพิ่ม — ข้ามรอบที่สร้างไปแล้วเพื่อไม่ต้องคำนวณซ้ำทั้งชุด
    (ตัวสร้างพึ่ง unique constraint กันของซ้ำอยู่แล้ว since เป็นแค่การประหยัดแรง)
    """
    freq = series["freq"]
    interval = max(1, series.get("interval") or 1)
    start = series["starts_on"]
    hard_end = series.get("ends_on")
    if hard_end and hard_end < until:
        until = hard_end
    if until < start:
        return []

    dates: list[date] = []

    if freq == "daily":
        cursor = start
        while cursor <= until and len(dates) < MAX_OCCURRENCES:
            dates.append(cursor)
            cursor += timedelta(days=interval)

    elif freq == "weekly":
        # ไม่ระบุวันในสัปดาห์ = ใช้วันเดียวกับวันเริ่ม
        weekdays = sorted(series.get("byweekday") or [start.weekday()])
        # ตรึงจุดอ้างอิงไว้ที่วันจันทร์ของสัปดาห์แรก เพื่อให้ "ทุก 2 สัปดาห์"
        # นับจากสัปดาห์เดิมเสมอ ไม่เลื่อนไปตามวันที่บังเอิญตกในสัปดาห์นั้น
        week_start = start - timedelta(days=start.weekday())
        while week_start <= until and len(dates) < MAX_OCCURRENCES:
            for weekday in weekdays:
                day = week_start + timedelta(days=weekday)
                if start <= day <= until:
                    dates.append(day)
            week_start += timedelta(weeks=interval)

    elif freq == "monthly_day":
        day_of_month = series.get("bymonthday") or start.day
        for year, month in _month_steps(start, interval, until):
            day = clamp_day(year, month, day_of_month)
            if start <= day <= until:
                dates.append(day)
            if len(dates) >= MAX_OCCURRENCES:
                break

    elif freq == "monthly_nth":
        weekday = series.get("nth_weekday")
        nth = series.get("nth_week") or 1
        if weekday is None:
            weekday = start.weekday()
        for year, month in _month_steps(start, interval, until):
            day = nth_weekday(year, month, weekday, nth)
            if day and start <= day <= until:
                dates.append(day)
            if len(dates) >= MAX_OCCURRENCES:
                break

    elif freq == "yearly":
        month = series.get("bymonth") or start.month
        day_of_month = series.get("byday") or start.day
        for year in range(start.year, until.year + 1):
            # 29 ก.พ. ในปีที่ไม่ใช่อธิกสุรทิน ต้องได้ 28 ก.พ. ไม่ใช่ข้ามปีนั้นไป
            day = clamp_day(year, month, day_of_month)
            if start <= day <= until:
                dates.append(day)

    dates.sort()

    max_count = series.get("max_count")
    if max_count:
        dates = dates[:max_count]
    if since:
        dates = [d for d in dates if d >= since]
    return dates


def period_after(series: dict, anchor: date) -> date:
    """วันถัดไปนับจาก anchor ตามคาบของแผน — ใช้ในโหมด after_done

    โหมดนี้สนใจแค่ "เว้นระยะห่างเท่าไร" ไม่สนใจว่าต้องตกวันที่เท่าไรของเดือน
    เช่น ทุก 3 เดือน ทำเสร็จ 30 ต.ค. -> รอบถัดไป 30 ม.ค.
    (กติกา bymonthday / nth_weekday ถูกละไว้ในโหมดนี้โดยตั้งใจ
    เพราะถ้าดึงกลับไปหาวันตายตัว ระยะห่างที่ผู้ใช้ต้องการจะเพี้ยน)

    วันสิ้นเดือนยังถูกหนีบให้อยู่ในเดือนปลายทางเหมือนเดิม
    (31 ม.ค. + 1 เดือน = 28/29 ก.พ.) เพราะ add_months จัดการให้แล้ว
    """
    freq = series["freq"]
    interval = max(1, series.get("interval") or 1)

    if freq == "daily":
        return anchor + timedelta(days=interval)
    if freq == "weekly":
        return anchor + timedelta(weeks=interval)
    if freq == "yearly":
        return add_months(anchor, 12 * interval)
    # monthly_day และ monthly_nth ใช้คาบเป็นเดือนเหมือนกันในโหมดนี้
    return add_months(anchor, interval)


def next_after(series: dict, anchor: date, made_count: int = 0) -> date | None:
    """รอบถัดไปในโหมด after_done · คืน None เมื่อแผนจบแล้ว

    made_count คือจำนวนรอบที่สร้างไปแล้ว ใช้เทียบกับ max_count
    """
    max_count = series.get("max_count")
    if max_count and made_count >= max_count:
        return None

    nxt = period_after(series, anchor)
    ends_on = series.get("ends_on")
    if ends_on and nxt > ends_on:
        return None
    return nxt


def describe(series: dict) -> str:
    """คำบรรยายกติกาเป็นภาษาไทยสำหรับแสดงในหน้ารายการแผนงาน

    ผู้ใช้ต้องอ่านออกว่าแผนนี้จะเกิดเมื่อไรโดยไม่ต้องเปิดฟอร์มเข้าไปดู
    """
    freq = series["freq"]
    interval = max(1, series.get("interval") or 1)

    if freq == "daily":
        text = "ทุกวัน" if interval == 1 else f"ทุก {interval} วัน"

    elif freq == "weekly":
        days = series.get("byweekday") or [series["starts_on"].weekday()]
        names = " · ".join(f"วัน{WEEKDAYS_FULL[d]}" for d in sorted(days))
        text = names if interval == 1 else f"ทุก {interval} สัปดาห์ ({names})"

    elif freq == "monthly_day":
        day = series.get("bymonthday") or series["starts_on"].day
        when = "วันสุดท้ายของเดือน" if day >= 29 else f"วันที่ {day} ของเดือน"
        if day >= 29:
            when = f"วันที่ {day} ของเดือน (เดือนที่สั้นกว่าใช้วันสุดท้าย)"
        text = when if interval == 1 else f"ทุก {interval} เดือน — {when}"

    elif freq == "monthly_nth":
        weekday = series.get("nth_weekday")
        weekday = series["starts_on"].weekday() if weekday is None else weekday
        nth = NTH_LABELS.get(series.get("nth_week") or 1, "แรก")
        # ป้ายที่มีตัวเลข ("ที่ 2") ต้องเว้นวรรคก่อน "ของเดือน" ไม่งั้นเลขติดกับคำ
        # ส่วนป้ายที่เป็นคำล้วน ("แรก" / "สุดท้าย") เขียนติดกันตามปกติของภาษาไทย
        joiner = " " if any(c.isdigit() for c in nth) else ""
        when = f"วัน{WEEKDAYS_FULL[weekday]}{nth}{joiner}ของเดือน"
        text = when if interval == 1 else f"ทุก {interval} เดือน — {when}"

    elif freq == "yearly":
        month = series.get("bymonth") or series["starts_on"].month
        day = series.get("byday") or series["starts_on"].day
        text = f"ทุกปี วันที่ {day} {MONTHS_FULL[month - 1]}"

    else:
        text = freq

    if series.get("anchor_mode") == ANCHOR_AFTER_DONE:
        # ในโหมดนี้ "ทุกวันที่ 15" ไม่เป็นจริงอีกต่อไป จึงต้องเขียนใหม่ทั้งประโยค
        # ไม่ใช่ต่อท้าย ไม่งั้นผู้ใช้จะเข้าใจผิดว่ายังยึดวันที่ 15 อยู่
        interval = max(1, series.get("interval") or 1)
        unit = {"daily": "วัน", "weekly": "สัปดาห์", "yearly": "ปี"}.get(freq, "เดือน")
        if freq == "yearly":
            interval = interval
        text = f"ทุก {interval} {unit} นับจากวันที่ทำเสร็จจริง"

    if series.get("duration_days", 1) > 1:
        text += f" · ครั้งละ {series['duration_days']} วัน"
    if series.get("ends_on"):
        text += f" · ถึง {short(series['ends_on'])}"
    elif series.get("max_count"):
        text += f" · {series['max_count']} ครั้ง"
    return text
