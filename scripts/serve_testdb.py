"""scripts/serve_testdb.py — เปิดสำเนาโปรแกรมชี้ DB ทดสอบ สำหรับตรวจหน้าจอระหว่างพัฒนา

รัน: python scripts\\serve_testdb.py            (พอร์ต 8201 · DB rpf_calendar_test)
     python scripts\\serve_testdb.py 8202 rpf_calendar_test2

ทำไมไม่ตั้ง env ใน launch.json แล้วเรียก uvicorn ตรงๆ: launch.json ตั้งตัวแปรแวดล้อมไม่ได้
ถ้าห่อด้วย powershell/cmd จะได้โปรเซสสองชั้น ตัวห่อถูกปิดแต่ตัว python ยังค้าง
ถือ connection ของ DB ทดสอบไว้จน DROP DATABASE ไม่ได้ (เจอจริง 2026-09-16)
สคริปต์นี้รัน uvicorn ในโปรเซสเดียวกัน ปิดแล้วจบจริง

ห้ามชี้ DB จริง — assert ไว้กันพลาด เพราะไฟล์นี้ตั้งใจให้ใช้กับข้อมูลทดสอบเท่านั้น
"""
import os
import sys
from pathlib import Path

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8201
dbname = sys.argv[2] if len(sys.argv) > 2 else "rpf_calendar_test"
assert dbname.endswith("_test") or dbname.endswith("_test2"), "ต้องเป็น DB ทดสอบเท่านั้น"
assert port != 8200, "พอร์ต 8200 เป็นของเซิร์ฟเวอร์จริง (มี tunnel ชี้อยู่)"

os.environ["PG_DBNAME"] = dbname          # ต้องมาก่อน import config
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, os.getcwd())

import uvicorn  # noqa: E402

uvicorn.run("main:app", host="127.0.0.1", port=port)
