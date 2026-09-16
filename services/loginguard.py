"""services/loginguard.py — จำกัดจำนวนครั้งที่เดารหัสผ่านผิด

จำเป็นตอนเปิดให้เข้าจากนอกฟาร์ม เพราะหน้าล็อกอินจะถูกยิงลองรหัสผ่านจากอินเทอร์เน็ต
ได้เรื่อยๆ · bcrypt ช้าพอที่จะกันการเดาแบบหมื่นครั้งต่อวินาที แต่ไม่กันการเดา
ทีละครั้งอย่างอดทน (รหัสผ่านสั้นๆ ที่คนตั้งเองมักหลุดแบบนั้น)

เก็บในหน่วยความจำของโปรเซส ไม่ลง DB เพราะ
  • ต้องเร็วมากและถูกเรียกทุกครั้งที่มีคนล็อกอิน
  • ข้อมูลนี้ไม่มีค่าเมื่อรีสตาร์ท — เริ่มนับใหม่ได้ ไม่เสียหาย
  • การเขียน DB ทุกครั้งที่มีคนยิงผิด คือช่องให้ถมดิสก์เสียเอง

ข้อจำกัด: นับแยกต่อโปรเซส ถ้าวันหนึ่งรัน uvicorn หลาย worker
ตัวนับจะแยกกันตาม worker ทำให้เพดานจริงคูณจำนวน worker
โปรแกรมนี้รัน worker เดียวจึงยังตรง — ถ้าเพิ่ม worker ต้องย้ายไปเก็บที่ส่วนกลาง
"""
import time
from threading import Lock

# ผิดได้กี่ครั้งก่อนถูกล็อก และล็อกนานเท่าไร
MAX_FAILS = 8
WINDOW_SEC = 15 * 60        # นับย้อนหลัง 15 นาที
LOCK_SEC = 15 * 60          # ล็อกไว้ 15 นาที

# กันหน่วยความจำโตไม่รู้จบเมื่อถูกยิงด้วยชื่อผู้ใช้สุ่มเป็นแสนชื่อ
MAX_TRACKED = 5000

_fails: dict[tuple[str, str], list[float]] = {}
_lock = Lock()


def _key(username: str, ip: str) -> tuple[str, str]:
    return (username.strip().lower(), ip or "?")


def _prune(now: float):
    """ทิ้งรายการที่หมดอายุ · เรียกใต้ _lock เท่านั้น"""
    for key in [k for k, times in _fails.items()
                if not times or now - times[-1] > max(WINDOW_SEC, LOCK_SEC)]:
        del _fails[key]


def locked_for(username: str, ip: str) -> int:
    """เหลือเวลาถูกล็อกอีกกี่วินาที (0 = ล็อกอินได้)"""
    now = time.time()
    with _lock:
        times = [t for t in _fails.get(_key(username, ip), []) if now - t <= WINDOW_SEC]
        if len(times) < MAX_FAILS:
            return 0
        return max(0, int(LOCK_SEC - (now - times[-1])))


def record_failure(username: str, ip: str):
    now = time.time()
    with _lock:
        if len(_fails) >= MAX_TRACKED:
            _prune(now)
            if len(_fails) >= MAX_TRACKED:
                return          # ยอมหยุดนับดีกว่ากินหน่วยความจำไม่จำกัด
        key = _key(username, ip)
        times = [t for t in _fails.get(key, []) if now - t <= WINDOW_SEC]
        times.append(now)
        _fails[key] = times


def clear(username: str, ip: str):
    """ล็อกอินสำเร็จแล้วล้างประวัติ — คนที่พิมพ์ผิดสองสามครั้งไม่ควรถูกจำ"""
    with _lock:
        _fails.pop(_key(username, ip), None)


def wait_message(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return (f"ลองรหัสผ่านผิดหลายครั้งเกินไป — รอประมาณ {minutes} นาทีแล้วลองอีกครั้ง "
            f"หรือติดต่อผู้ดูแลระบบ")
