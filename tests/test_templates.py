"""กันบั๊กชนิด "ตัวจัดการเหตุการณ์ของ Alpine ตายเงียบ"

ที่มา (2026-10-02): ปุ่มลบในกล่องข้างของปฏิทินเขียนกล่องยืนยันคร่อมหลายบรรทัด
Alpine คอมไพล์นิพจน์นั้นไม่ผ่าน ตัวจัดการจึงไม่ทำงาน แล้ว **กดลบแล้วลบทันทีโดยไม่ถาม**
ไม่มีอะไรบนหน้าจอบอกเลย รู้ได้จาก console เท่านั้น — เทสต์ชุดนี้จึงอ่านเทมเพลตตรงๆ

สองกับดักที่ดักไว้:
  1. สตริงคร่อมบรรทัดจริง — JavaScript ไม่ยอม ต้องใช้ \\n
  2. นิพจน์ที่เป็น "คำสั่ง" ซึ่ง Alpine ห่อ IIFE ให้ไม่ทัน → SyntaxError

ข้อ 2 อ่านจากตัวจริงใน static/js/vendor/alpine.min.js:

    /^[\\n\\s]*if.*\\(.*\\)/.test(e.trim()) || /^(let|const)\\s/.test(e.trim())
        ? `(async()=>{ ${e} })()` : e

แปลว่า **ห่อให้เฉพาะ** นิพจน์ที่ขึ้นต้นด้วย `let`/`const` หรือขึ้นต้นด้วย `if` ที่มีวงเล็บ
เปิด-ปิดครบในบรรทัดเดียวกัน (`.` ของ regex ไม่ข้ามบรรทัด) · นอกนั้นเอาไปวางหลัง `=` ตรงๆ
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
HANDLER = re.compile(r'(x-on:\w+(?:\.\w+)*|@\w+(?:\.\w+)*)="([^"]*)"', re.S)
# คำสั่งที่ Alpine ไม่เคยห่อให้เลย — เขียนเมื่อไรก็พัง
NEVER_WRAPPED = re.compile(r"^(for|while|switch|var|return)\b")


def handlers():
    for path in sorted(TEMPLATES.glob("*.html")):
        for match in HANDLER.finditer(path.read_text(encoding="utf-8")):
            yield path.name, match.group(1), match.group(2)


def test_no_alpine_handler_has_a_real_newline_inside_a_string():
    bad = []
    for name, attr, expr in handlers():
        # นับเครื่องหมายคำพูดก่อนถึงบรรทัดใหม่ — คี่ = ขึ้นบรรทัดกลางสตริง
        for cut in (i for i, ch in enumerate(expr) if ch == "\n"):
            if expr.count("'", 0, cut) % 2 == 1:
                bad.append(f"{name} {attr}: {expr.splitlines()[0][:60]}")
                break
    assert not bad, "สตริงใน Alpine คร่อมบรรทัดไม่ได้ ใช้ \\n แทน:\n" + "\n".join(bad)


def test_if_handlers_close_their_paren_on_the_first_line():
    """`if (` ที่วงเล็บไปปิดบรรทัดถัดไป = ตัวที่ทำให้ปุ่มลบไม่ถามยืนยัน"""
    bad = []
    for name, attr, expr in handlers():
        head = expr.strip().split("\n")[0]
        if head.startswith("if") and ")" not in head:
            bad.append(f"{name} {attr}: {head[:60]}")
    assert not bad, ("นิพจน์ที่ขึ้นต้นด้วย if ต้องปิดวงเล็บในบรรทัดแรก "
                     "ไม่งั้น Alpine ห่อ IIFE ให้ไม่ทัน:\n" + "\n".join(bad))


def test_no_handler_uses_a_statement_alpine_never_wraps():
    bad = [f"{name} {attr}: {expr.strip().splitlines()[0][:60]}"
           for name, attr, expr in handlers() if NEVER_WRAPPED.match(expr.strip())]
    assert not bad, ("Alpine ไม่ห่อ IIFE ให้คำสั่งพวกนี้ ต้องเขียนเป็นนิพจน์:\n" + "\n".join(bad))


def test_destructive_actions_in_the_calendar_panel_still_ask_first():
    """ปุ่มที่ลบ/ถอนในกล่องข้างต้องมี confirm() ติดอยู่จริง ไม่ใช่แค่เคยมี"""
    panel = (TEMPLATES / "_panel_detail.html").read_text(encoding="utf-8")
    forms = re.findall(r"<form[^>]*?/(delete|unstart)'\"[^>]*?>", panel, re.S)
    assert len(forms) == 2, f"คาดว่ามีฟอร์มลบและถอนอย่างละหนึ่ง เจอ {forms}"
    for action in ("/delete", "/unstart"):
        block = panel.split(action + "'\"")[1].split(">")[0]
        assert "confirm(" in block, f"ฟอร์ม {action} ในกล่องข้างไม่มีกล่องยืนยันแล้ว"
