"""services/calgrid.py — จัดวางแถบกิจกรรมลงตารางปฏิทินรายเดือน

ปัญหาที่ต้องแก้: กิจกรรมหนึ่งกินหลายวันและอาจคาบข้ามสัปดาห์
ต้องตัดเป็นแถบย่อยรายสัปดาห์ แล้ววางซ้อนกันเป็นชั้น (lane) ไม่ให้ทับกัน
เหมือนตารางจองห้องประชุม

แยกออกมาเป็นไฟล์ต่างหากเพราะเป็นตรรกะล้วนๆ ทดสอบได้โดยไม่ต้องมี DB หรือ HTTP
"""
from calendar import monthrange
from datetime import date, timedelta

# เกินกว่านี้ในสัปดาห์เดียว ช่องปฏิทินจะสูงจนใช้งานไม่ได้ ที่เหลือขึ้นเป็น "+N"
MAX_LANES = 4

# แถบการลา (lane_rank 0, v2) ได้ชั้นเพิ่มต่างหากไม่กินโควตาของกิจกรรม — แต่ก็มีเพดาน
# ไม่งั้นสัปดาห์สงกรานต์ที่ลากัน 10 คนจะสูงเป็นเมตร · ที่เกินไป "+N" และดูได้ในแถบพนักงาน
MAX_LEAVE_LANES = 3


def month_bounds(year: int, month: int) -> tuple[date, date, date, date]:
    """คืน (วันแรกของเดือน, วันสุดท้ายของเดือน, วันแรกของตาราง, วันสุดท้ายของตาราง)

    ตารางเริ่มวันจันทร์และเติมวันของเดือนข้างเคียงให้ครบสัปดาห์
    """
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=6 - last.weekday())
    return first, last, grid_start, grid_end


def _sort_key(item: dict):
    """ลำดับการวางแถบ — ยาวก่อนสั้น เพื่อให้แถบยาวได้ชั้นบนและอ่านง่าย

    ถ้าเรียงตามความสำคัญอย่างเดียว แถบยาวจะถูกดันลงล่างแล้วสายตาไล่ตามยาก

    `lane_rank` มาก่อนทุกอย่าง — แถบการลา (v2) ตั้งเป็น 0 จึงได้จองชั้นก่อนกิจกรรมเสมอ
    ไม่งั้นวันที่มีวัคซีน 4 รายการจะกินครบ MAX_LANES แล้วแถบลาหลุดไปอยู่ใน "+N"
    ทั้งที่ผู้ใช้อยากเห็นทันทีว่าใครลา (§29.4) · กิจกรรมที่หลุดยังอยู่ในลิสต์ของกล่องข้าง
    แต่การลาไม่มีที่อื่นให้เห็นนอกจากแถบกับแถบพนักงาน
    """
    return (item.get("lane_rank", 1), item["planned_date"], -item["span_days"],
            item["priority"], item["id"])


def build_weeks(year: int, month: int, items: list[dict], today: date) -> list[dict]:
    """สร้างโครงตารางเดือนพร้อมแถบที่จัดชั้นแล้ว

    คืนรายการสัปดาห์ แต่ละสัปดาห์มี
      days  — 7 ช่อง (วันที่, อยู่ในเดือนนี้ไหม, วันนี้ไหม)
      bars  — แถบที่ตัดตามสัปดาห์แล้ว พร้อมคอลัมน์เริ่ม/ความกว้าง/ชั้น
      lanes — จำนวนชั้นที่ใช้จริง (เอาไว้คุมความสูงของแถว)
      more  — จำนวนกิจกรรมที่ล้นเกิน MAX_LANES แยกตามวัน
    """
    first, last, grid_start, grid_end = month_bounds(year, month)
    ordered = sorted(items, key=_sort_key)

    weeks = []
    week_start = grid_start
    while week_start <= grid_end:
        week_end = week_start + timedelta(days=6)

        # lanes[i] = คอลัมน์สุดท้ายที่ชั้น i ถูกจองไว้ถึง (0 = ว่าง)
        lane_ends: list[int] = []
        bars, overflow = [], {}
        # ชั้นที่แถบการลาเปิดไว้ในสัปดาห์นี้ — กิจกรรมได้โควตา MAX_LANES ต่างหากจากตรงนี้
        # (การลามาก่อนเสมอตาม _sort_key จึงรู้ค่านี้ครบก่อนถึงกิจกรรมตัวแรก)
        leave_lanes = 0

        for item in ordered:
            start = max(item["planned_date"], week_start)
            end = min(item["planned_end_date"], week_end)
            if start > end:
                continue

            col_start = (start - week_start).days + 1        # 1..7
            col_end = (end - week_start).days + 1

            lane = next((i for i, taken in enumerate(lane_ends) if taken < col_start),
                        len(lane_ends))
            is_leave = item.get("lane_rank", 1) == 0
            cap = MAX_LEAVE_LANES if is_leave else MAX_LANES + leave_lanes
            if lane >= cap:
                # ไม่มีที่แล้ว — นับเป็น "+N" ของทุกวันที่แถบนี้พาดผ่าน
                for offset in range(col_start, col_end + 1):
                    day = week_start + timedelta(days=offset - 1)
                    overflow[day] = overflow.get(day, 0) + 1
                continue

            if lane == len(lane_ends):
                lane_ends.append(col_end)
            else:
                lane_ends[lane] = col_end
            if is_leave:
                leave_lanes = max(leave_lanes, lane + 1)

            bars.append({
                "item": item,
                "col_start": col_start,
                "span": col_end - col_start + 1,
                "lane": lane,
                # แถบที่ถูกตัดกลางคัน ตัดมุมข้างนั้นออกเพื่อบอกว่ายังไม่จบ
                "clipped_left": item["planned_date"] < week_start,
                "clipped_right": item["planned_end_date"] > week_end,
            })

        weeks.append({
            "days": [{
                "date": week_start + timedelta(days=i),
                "in_month": (week_start + timedelta(days=i)).month == month,
                "is_today": (week_start + timedelta(days=i)) == today,
                "more": overflow.get(week_start + timedelta(days=i), 0),
            } for i in range(7)],
            "bars": bars,
            "lanes": len(lane_ends),
        })
        week_start += timedelta(days=7)

    return weeks


def day_index(items: list[dict]) -> dict[str, list[int]]:
    """แผนที่ วันที่ (ISO) -> รายการ id ของกิจกรรมที่คาบวันนั้น

    ฝั่งเบราว์เซอร์ใช้ตัวนี้เลือกว่าจะแสดงอะไรในแผงรายละเอียดเมื่อผู้ใช้กดวัน
    """
    index: dict[str, list[int]] = {}
    for item in sorted(items, key=_sort_key):
        day = item["planned_date"]
        while day <= item["planned_end_date"]:
            index.setdefault(day.isoformat(), []).append(item["id"])
            day += timedelta(days=1)
    return index


def build_week(monday: date, items: list[dict], today: date) -> dict:
    """โครงมุมมองรายสัปดาห์ — แถบคร่อมวันอยู่บน งานที่ระบุเวลาแยกเป็นคอลัมน์รายวันอยู่ล่าง

    ไม่ทำเป็นตารางเวลาแบบชั่วโมงต่อชั่วโมง เพราะงานฟาร์มเป็นก้อนใหญ่ๆ ไม่กี่งานต่อวัน
    ตารางชั่วโมงจะเหลือที่ว่างเปล่าเกือบทั้งจอ · ใช้เป็นรายการเรียงตามเวลาแทน
    """
    sunday = monday + timedelta(days=6)
    ordered = sorted(items, key=_sort_key)

    # แถบด้านบน = งานทั้งวัน หรือ งานที่กินมากกว่า 1 วัน
    spanning = [i for i in ordered
                if i["planned_end_date"] > i["planned_date"] or i["is_all_day"]]
    bars, lane_ends = [], []
    for item in spanning:
        start = max(item["planned_date"], monday)
        end = min(item["planned_end_date"], sunday)
        if start > end:
            continue
        col_start = (start - monday).days + 1
        col_end = (end - monday).days + 1
        lane = next((i for i, taken in enumerate(lane_ends) if taken < col_start),
                    len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(col_end)
        else:
            lane_ends[lane] = col_end
        bars.append({
            "item": item, "col_start": col_start, "span": col_end - col_start + 1,
            "lane": lane,
            "clipped_left": item["planned_date"] < monday,
            "clipped_right": item["planned_end_date"] > sunday,
        })

    spanning_ids = {i["id"] for i in spanning}
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        days.append({
            "date": day,
            "is_today": day == today,
            "items": [i for i in ordered
                      if i["id"] not in spanning_ids
                      and i["planned_date"] <= day <= i["planned_end_date"]],
        })

    return {"monday": monday, "sunday": sunday, "days": days,
            "bars": bars, "lanes": len(lane_ends)}


def week_of(day: date) -> date:
    """วันจันทร์ของสัปดาห์ที่วันนี้อยู่"""
    return day - timedelta(days=day.weekday())
