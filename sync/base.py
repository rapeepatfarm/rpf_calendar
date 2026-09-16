"""sync/base.py — สัญญาที่ทุกแหล่งข้อมูลต้องทำตาม

ยังไม่มีแหล่งจริงต่ออยู่ (ตามที่ตกลงไว้ในเฟส 5 คือทำโครงรองรับก่อน)
ไฟล์นี้คือจุดที่กำหนดว่า adapter ใหม่ต้องคืนอะไรบ้าง

ทิศทางคือ **ปฏิทินดึงจากต้นทาง** ไม่ใช่ต้นทาง push เข้ามา
เพราะการเพิ่มแหล่งใหม่จะได้ไม่ต้องไปแก้โปรแกรมพี่น้อง
"""
from dataclasses import dataclass, field
from datetime import date, time
from typing import Protocol


@dataclass
class ExternalActivity:
    """กิจกรรม 1 รายการที่ดึงมาจากโปรแกรมอื่น

    external_id ต้องเป็นกุญแจที่ **ไม่เปลี่ยนตามชื่อ** — ใช้ id ตัวเลขของแถวต้นทาง
    ห้ามใช้ชื่อวัคซีนหรือชื่อฝูงเป็นกุญแจเด็ดขาด เพราะพอต้นทางเปลี่ยนชื่อ
    ความเชื่อมโยงจะขาดเงียบๆ แล้วรอบถัดไปจะสร้างกิจกรรมซ้ำขึ้นมาใหม่
    """
    external_id: str
    title: str
    planned_date: date

    # งานที่กินเวลาหลายวัน ให้ระบุวันสิ้นสุด — ไม่ระบุถือว่าจบในวันเดียว
    end_date: date | None = None

    is_all_day: bool = True
    start_time: time | None = None
    duration_min: int | None = None
    priority: int = 3
    description: str = ""

    # ชื่อผู้รับผิดชอบฝั่งต้นทาง — runner จะพยายามจับคู่กับทะเบียน staff
    # ถ้าจับคู่ไม่ได้จะปล่อยว่างไว้ให้หัวหน้ามอบหมายเอง ไม่เดาสุ่ม
    assignee_hint: str = ""

    # สถานะฝั่งต้นทาง: pending | done | cancelled
    # ถ้า done แล้ว runner จะปิดกิจกรรมในปฏิทินตาม (เฉพาะที่ยังไม่มีใครกดเอง)
    source_status: str = "pending"
    done_on: date | None = None

    payload: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        """ลายนิ้วมือของข้อมูลฝั่งแผน — ใช้เทียบว่าต้นทางเปลี่ยนหรือยัง

        ไม่รวมข้อมูลการทำงานจริง เพราะฝั่งปฏิทินเป็นเจ้าของส่วนนั้น
        """
        parts = (self.title, str(self.planned_date), str(self.final_date),
                 str(self.start_time), str(self.duration_min),
                 str(self.priority), self.description)
        return "|".join(parts)

    @property
    def final_date(self) -> date:
        return self.end_date or self.planned_date


class SyncSource(Protocol):
    """หน้าตาของ adapter — ดู sources/_example.py เป็นแม่แบบ"""

    code: str      # รหัสสั้นๆ ไม่ซ้ำใคร เช่น "farm_activities"
    name: str      # ชื่อที่คนอ่านรู้เรื่อง เช่น "แผนวัคซีนจาก RPF Farm"
    system: str    # ชื่อโปรแกรมต้นทาง เช่น "rpf_farm"

    def fetch(self, config: dict, since: date) -> list[ExternalActivity]:
        """ดึงกิจกรรมตั้งแต่วันที่ since เป็นต้นไป

        ต้องคืน **ทุกรายการที่ยังมีอยู่จริง** ในช่วงนั้น ไม่ใช่เฉพาะที่เพิ่งเปลี่ยน
        เพราะ runner ใช้รายการนี้ตัดสินว่าอะไรถูกลบจากต้นทางไปแล้วบ้าง
        (ดูกติกาข้อ 2 ใน runner.py) ถ้าคืนมาไม่ครบ กิจกรรมที่ยังอยู่จะถูกปิดผิด
        """
        ...
