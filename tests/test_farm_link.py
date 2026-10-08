"""การผูกกิจกรรมกับฝูงไก่ใน RPF Farm (migration 016) — ส่วนที่เป็นตรรกะล้วน ไม่แตะ DB"""
from datetime import date

from services import farm_link
from sync.base import ExternalActivity
from sync.runner import category_for


def test_parse_item_accepts_both_registries():
    assert farm_link.parse_item("vaccine:13") == ("vaccine", 13)
    assert farm_link.parse_item("activity:5") == ("activity", 5)


def test_parse_item_rejects_garbage():
    # ค่าจากฟอร์มยิงตรงได้ — ต้องไม่หลุดไปเป็นชื่อตารางใน SQL
    for bad in ("", None, "vaccine:", "vaccine:abc", "users:1", "vaccine:1;drop", ":3"):
        assert farm_link.parse_item(bad) == (None, None)


def test_resolve_requires_flock_and_item_before_touching_db():
    for args in ((None, "vaccine", 1), (5, None, 1), (5, "vaccine", None), (5, "users", 1)):
        try:
            farm_link.resolve(*args)
        except ValueError:
            continue
        raise AssertionError(f"resolve{args} ควรปฏิเสธ")


def test_fill_keeps_synced_activity_untouched():
    # งานที่ซิงค์มาจากฟาร์ม ห้ามถูกตั้งให้ส่งกลับ — คงค่าเดิมไว้ ไม่เรียก DB เลย
    existing = {"source_system": "rpf_farm", **farm_link.EMPTY}
    data = {"category_id": 1, "farm_flock_id": 99}
    assert farm_link.fill(None, {}, data, existing) is None
    assert data["farm_flock_id"] is None


def _item(key):
    return ExternalActivity(external_id="1", title="x", planned_date=date(2026, 10, 1),
                            category_key=key)


def test_category_for_uses_map_then_default():
    cfg = {"category_id": 1, "category_map": {"activity": 13}}
    assert category_for(cfg, _item("activity")) == 13
    assert category_for(cfg, _item("vaccine")) == 1      # ไม่ได้ตั้ง → ประเภทตั้งต้น
    assert category_for({"category_id": 1}, _item("activity")) == 1
    assert category_for({}, _item("")) is None
