# -*- coding: utf-8 -*-
"""สร้างไอคอนของ PWA — สั่งใหม่ได้ทุกเมื่อถ้าเปลี่ยนสีหรือรูปแบบ

    python scripts\\make_icons.py

ทำไมต้องมีสคริปต์ ไม่วาดทิ้งไว้เฉย ๆ
    ไอคอนมีหลายขนาดหลายแบบและต้องเหมือนกันทุกใบ ถ้าวาดมือแล้ววันหนึ่ง
    เปลี่ยนสีแบรนด์ จะต้องไล่แก้ทีละไฟล์แล้วลืมบางใบแน่นอน

ไอคอนที่ออกมา
    icon-192.png            ขนาดมาตรฐานที่ Android ใช้บนหน้าจอโฮม
    icon-512.png            ใช้ทำหน้า splash ตอนเปิดแอป
    icon-maskable-512.png   Android รุ่นใหม่ครอบรูปทรงของตัวเอง (วงกลม/สี่เหลี่ยมมน)
                            ทับไอคอนเรา ตัวนี้จึงเผื่อขอบไว้ 20% รอบด้าน
                            ไม่งั้นขอบภาพจะโดนตัดทิ้ง
    apple-touch-icon.png    iOS ไม่อ่าน manifest ต้องมีแท็กและไฟล์แยก
                            ห้ามโปร่งใสและห้ามมนมุมมาเอง เพราะ iOS มนให้อยู่แล้ว
                            ถ้ามนมาก่อนจะได้มุมดำ
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"

BLUE = (47, 125, 225)        # #2f7de1 — สีเดียวกับ theme_color ใน manifest
BLUE_DARK = (28, 95, 176)
WHITE = (255, 255, 255)

SS = 4                       # วาดใหญ่ 4 เท่าแล้วย่อ = ขอบเรียบโดยไม่ต้องพึ่ง antialias ของ draw


def draw_icon(size, pad_ratio=0.0, rounded=True):
    """วาดไอคอนปฏิทิน · pad_ratio = เว้นขอบกี่ส่วนของด้าน (ใช้กับ maskable)"""
    S = size * SS
    img = Image.new("RGB", (S, S), BLUE)
    d = ImageDraw.Draw(img)

    if rounded:
        # พื้นหลังมนมุม — วาดบนภาพทึบ ไม่ใช้ alpha เพราะ apple-touch-icon ห้ามโปร่งใส
        bg = Image.new("RGB", (S, S), WHITE)
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
        img = Image.composite(Image.new("RGB", (S, S), BLUE), bg, m)
        d = ImageDraw.Draw(img)

    # กรอบที่ยอมให้วาดรูปได้ · maskable ต้องหดเข้ามาให้พ้นเขตที่ระบบครอบทิ้ง
    inset = S * pad_ratio
    x0, y0, x1, y1 = inset, inset, S - inset, S - inset
    w, h = x1 - x0, y1 - y0

    def px(fx, fy):
        return x0 + w * fx, y0 + h * fy

    # ตัวปฏิทิน
    card = [*px(0.20, 0.26), *px(0.80, 0.80)]
    d.rounded_rectangle(card, radius=int(w * 0.07), fill=WHITE)

    # แถบหัวปฏิทิน
    band = [*px(0.20, 0.26), *px(0.80, 0.42)]
    d.rounded_rectangle(band, radius=int(w * 0.07), fill=BLUE_DARK)
    d.rectangle([*px(0.20, 0.36), *px(0.80, 0.42)], fill=BLUE_DARK)

    # ห่วงสองอันโผล่พ้นแถบหัว
    for fx in (0.36, 0.64):
        d.rounded_rectangle([*px(fx - 0.035, 0.17), *px(fx + 0.035, 0.33)],
                            radius=int(w * 0.035), fill=WHITE)

    # ช่องวันที่ 4 x 2
    for row, fy in enumerate((0.52, 0.66)):
        for col, fx in enumerate((0.29, 0.435, 0.58, 0.725)):
            if row == 1 and col == 3:
                continue          # เว้นช่องท้ายให้ดูเป็นเดือนจริง ไม่ใช่ตาราง
            fill = BLUE if (row, col) != (0, 1) else BLUE_DARK
            d.rounded_rectangle([*px(fx, fy), *px(fx + 0.075, fy + 0.085)],
                                radius=int(w * 0.012), fill=fill)

    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    made = [
        ("icon-192.png", draw_icon(192)),
        ("icon-512.png", draw_icon(512)),
        # 20% รอบด้าน = เนื้อหาอยู่ในวงปลอดภัยที่ Android รับประกันว่าไม่ตัด
        ("icon-maskable-512.png", draw_icon(512, pad_ratio=0.20)),
        # iOS มนมุมให้เอง ถ้าเรามนมาก่อนจะเห็นมุมดำโผล่
        ("apple-touch-icon.png", draw_icon(180, rounded=False)),
    ]
    for name, img in made:
        p = OUT / name
        img.save(p, "PNG", optimize=True)
        print(f"  {name:24} {img.size[0]}x{img.size[1]}  {p.stat().st_size:,} bytes")
    print(f"\nเขียนลง {OUT}")


if __name__ == "__main__":
    sys.exit(main())
