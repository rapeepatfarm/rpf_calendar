"""scripts/show_urls.py — บอกว่าเครื่องอื่นต้องเปิด URL ไหน (ทั้ง LAN และนอกบริษัท)

รัน: python scripts\\show_urls.py

ใช้ตอนย้ายเครื่อง เน็ตเปลี่ยน หรือเปิด tunnel ใหม่แล้วไม่รู้ว่าได้ URL อะไร
(ไอพี LAN จาก DHCP เปลี่ยนได้เมื่อเราเตอร์รีสตาร์ท · URL ของ quick tunnel
เปลี่ยนทุกครั้งที่เปิดใหม่ — ดู docs/access.md เรื่องการทำให้ทั้งสองอย่างคงที่)
"""
import re
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (APP_PORT, BASE_DIR, ONLINE,  # noqa: E402
                    SESSION_HTTPS_ONLY, check_session_secret)

TUNNEL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def local_ips() -> list[str]:
    """ไอพีของทุกการ์ดเน็ตที่ใช้งานได้จริง

    เรียงให้ 192.168.x ขึ้นก่อน เพราะเป็นวงที่เครื่องอื่นในบริษัทอยู่
    ส่วน 172.x มักเป็นการ์ดเสมือนของ Hyper-V/WSL ที่เครื่องอื่นเข้าไม่ถึง
    """
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except socket.gaierror:
        pass

    # เผื่อ getaddrinfo ไม่ครบ (พบบ่อยบน Windows ที่มีการ์ดเสมือน)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        found.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass

    usable = [ip for ip in found
              if not ip.startswith("127.") and not ip.startswith("169.254.")]
    return sorted(usable, key=lambda ip: (not ip.startswith("192.168."), ip))


def tunnel_url() -> str | None:
    """อ่าน URL ของ quick tunnel จาก log ที่ cloudflared เขียนไว้

    ต้องอ่านจาก log เพราะ URL เปลี่ยนทุกครั้งที่เปิดใหม่ จดไว้ในเอกสารไม่ได้
    """
    log = BASE_DIR / "cloudflared.log"
    if not log.exists():
        return None
    found = TUNNEL_PATTERN.findall(log.read_text(encoding="utf-8", errors="ignore"))
    return found[-1] if found else None


def tunnel_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
                             capture_output=True, text=True, timeout=5).stdout
        return "cloudflared.exe" in out
    except (OSError, subprocess.SubprocessError):
        return False


def port_is_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", APP_PORT), timeout=1):
            return True
    except OSError:
        return False


def main():
    print("=" * 62)
    print("  RPF Calendar — ที่อยู่สำหรับเปิดจากเครื่องอื่น")
    print("=" * 62)

    if not port_is_open():
        print(f"\n  [!] ยังไม่มีโปรแกรมรันอยู่ที่พอร์ต {APP_PORT}")
        print("      สั่ง start.bat ก่อน แล้วรันสคริปต์นี้อีกครั้ง")

    ips = local_ips()
    if not ips:
        print("\n  หาไอพีของเครื่องไม่ได้ — ลองสั่ง ipconfig ดูเอง")
    else:
        print("\n  ในวง LAN บริษัท เปิดจากมือถือหรือคอมเครื่องอื่นได้ที่:\n")
        for ip in ips:
            note = ""
            if ip.startswith("172.") or ip.startswith("10."):
                note = "   <- อาจเป็นการ์ดเสมือน เครื่องอื่นเข้าไม่ถึง"
            print(f"      http://{ip}:{APP_PORT}{note}")
        print("\n  (เครื่องที่จะเข้าต้องอยู่ในวง Wi-Fi/สายเดียวกัน)")

    url, running = tunnel_url(), tunnel_running()
    if running and url:
        print("\n  จากนอกบริษัท — Cloudflare quick tunnel (กำลังทำงาน):\n")
        print(f"      {url}")
        print("\n  [!] URL นี้เปลี่ยนใหม่ทุกครั้งที่เปิด tunnel ใหม่")
        print("      และใครที่รู้ URL ก็เปิดหน้าล็อกอินได้ — อย่าโพสต์ที่สาธารณะ")
    elif url:
        print("\n  จากนอกบริษัท: tunnel หยุดทำงานแล้ว — URL เดิมใช้ไม่ได้")
        print(f"      ({url})")
        print("      สั่ง start_tunnel.bat เพื่อเปิดใหม่ · จะได้ URL ใหม่")
    else:
        print("\n  จากนอกบริษัท: ยังไม่ได้เปิด tunnel — สั่ง start_tunnel.bat")
        print("      หรือดูวิธีตั้งแบบถาวร (URL ไม่เปลี่ยน) ใน docs\\access.md")

    print("\n  " + "-" * 58)
    print("  สถานะการตั้งค่าความปลอดภัย")
    problem = check_session_secret()
    print(f"    SESSION_SECRET : "
          f"{'[!] ' + problem.split('—')[0].strip() if problem else 'แข็งแรงดี'}")
    print(f"    ONLINE         : "
          f"{'เปิด (อายุล็อกอิน 12 ชม.)' if ONLINE else 'ปิด (ใช้ในวง LAN)'}")
    print(f"    HTTPS only     : "
          f"{'เปิด' if SESSION_HTTPS_ONLY else 'ปิด (ต้องปิด เพราะยังใช้ LAN แบบ http ด้วย)'}")
    if not ONLINE:
        print("\n    หมายเหตุ: ก่อนเปิดให้เข้าจากนอกบริษัท ตั้ง ONLINE=1 ใน .env")
    print()


if __name__ == "__main__":
    main()
