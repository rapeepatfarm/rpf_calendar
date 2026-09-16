"""scripts/tunnel.py — เปิด/ปิด/ดูสถานะ Cloudflare quick tunnel

    python scripts\\tunnel.py           ดูสถานะ · ถ้ายังไม่เปิดจะเปิดให้
    python scripts\\tunnel.py restart   ปิดตัวเดิมแล้วเปิดใหม่ (ได้ URL ใหม่)
    python scripts\\tunnel.py stop      ปิด tunnel

ทำไมต้องเป็น Python ไม่ใช่ .bat ล้วน — cmd.exe อ่านภาษาไทยในไฟล์ .bat เพี้ยน
เพราะใช้ codepage ของระบบ (874) ไม่ใช่ UTF-8 · เขียนเป็น Python แล้วบังคับ
stdout เป็น UTF-8 ได้ ข้อความภาษาไทยจึงอ่านออกทุกเครื่อง
"""
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# บังคับ UTF-8 ก่อนพิมพ์อะไร ไม่งั้นภาษาไทยจะพังบน cmd.exe ที่ตั้ง codepage 874
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import APP_PORT, BASE_DIR  # noqa: E402

CLOUDFLARED = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
LOG = BASE_DIR / "cloudflared.log"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
WAIT_SECONDS = 60


def running_pids() -> list[int]:
    """PID ของ cloudflared ที่รันอยู่ · ใช้ tasklist เพราะไม่ต้องพึ่งไลบรารีเสริม"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(m) for m in re.findall(r'"cloudflared\.exe","(\d+)"', out)]


def url_from_log() -> str | None:
    if not LOG.exists():
        return None
    found = URL_PATTERN.findall(LOG.read_text(encoding="utf-8", errors="ignore"))
    return found[-1] if found else None


def app_is_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", APP_PORT), timeout=2):
            return True
    except OSError:
        return False


def stop() -> int:
    pids = running_pids()
    if not pids:
        print("  ไม่มี tunnel รันอยู่")
        return 0
    subprocess.run(["taskkill", "/IM", "cloudflared.exe", "/F"],
                   capture_output=True, text=True, timeout=15)
    # รอให้ Windows ปล่อยไฟล์ log จริงๆ ก่อน ไม่งั้นลบไม่ได้ในขั้นถัดไป
    for _ in range(10):
        if not running_pids():
            break
        time.sleep(0.5)
    print(f"  ปิด tunnel แล้ว ({len(pids)} process)")
    return len(pids)


def start() -> str | None:
    if not CLOUDFLARED.exists():
        print(f"  [!] ไม่พบ cloudflared ที่ {CLOUDFLARED}")
        return None

    if not app_is_up():
        print(f"  [!] ยังไม่มีโปรแกรมรันอยู่ที่พอร์ต {APP_PORT}")
        print("      สั่ง start.bat ก่อน แล้วค่อยเปิด tunnel")
        return None

    # ล้าง log เก่าเพื่อไม่ให้อ่าน URL เดิมมาแสดงผิด — ต้องปิด process ก่อนถึงลบได้
    try:
        LOG.unlink(missing_ok=True)
    except OSError:
        print("  [!] ลบไฟล์ log เก่าไม่ได้ (อาจมี tunnel อื่นค้างอยู่)")
        print("      สั่ง: python scripts\\tunnel.py restart")
        return None

    print("  กำลังเปิด tunnel ...")
    with open(LOG, "wb") as log_file:
        subprocess.Popen(
            [str(CLOUDFLARED), "tunnel", "--no-autoupdate",
             "--url", f"http://localhost:{APP_PORT}"],
            stdout=subprocess.DEVNULL, stderr=log_file,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)

    for _ in range(WAIT_SECONDS):
        time.sleep(1)
        url = url_from_log()
        if url:
            return url
        if not running_pids():
            print("  [!] cloudflared ปิดตัวเองไปแล้ว — ดูรายละเอียดใน cloudflared.log")
            return None
    print("  [!] รอเกิน 1 นาทีแล้วยังไม่ได้ URL — ดู cloudflared.log")
    return None


def show(url: str, fresh: bool):
    print()
    print("  " + "=" * 56)
    print("  URL สำหรับเข้าจากนอกบริษัท:")
    print()
    print(f"      {url}")
    print()
    if not fresh:
        print("  (tunnel เดิมยังทำงานอยู่ — ยังใช้ URL นี้ได้ ไม่ต้องเปิดใหม่)")
        print("  ถ้าต้องการ URL ใหม่ สั่ง: python scripts\\tunnel.py restart")
    else:
        print("  ส่ง URL นี้ให้เฉพาะคนที่ต้องใช้")
        print("  ใครที่รู้ URL ก็เปิดหน้าล็อกอินได้ — อย่าโพสต์ที่สาธารณะ")
    print("  " + "=" * 56)


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else "start").lower()
    print("=" * 60)
    print("  RPF Calendar — Cloudflare quick tunnel")
    print("=" * 60)

    if action == "stop":
        stop()
        return

    if action == "restart":
        stop()
        url = start()
        if url:
            show(url, fresh=True)
        return

    # ค่าเริ่มต้น: ถ้ามีตัวเดิมรันอยู่แล้วก็ใช้ต่อ ไม่เปิดซ้อน
    # (เปิดซ้อนจะแย่งไฟล์ log กันแล้วได้ URL ที่อ่านมาผิด)
    if running_pids():
        url = url_from_log()
        if url:
            show(url, fresh=False)
        else:
            print("  มี tunnel รันอยู่แต่หา URL ใน log ไม่เจอ")
            print("  สั่ง: python scripts\\tunnel.py restart")
        return

    url = start()
    if url:
        show(url, fresh=True)


if __name__ == "__main__":
    main()
