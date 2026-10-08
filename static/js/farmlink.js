/* farmlink.js — เลือกฝูงไก่ + วัคซีน/กิจกรรมจาก RPF Farm ในฟอร์มกิจกรรม
 *
 * ส่วนนี้โผล่เมื่อประเภทที่เลือกติ๊ก "ส่งไป RPF Farm" (ส่งรายการ id มาจาก router)
 * ไม่ได้ผูกกับชื่อประเภท — เปลี่ยนชื่อ "วัคซีนไก่รุ่น" แล้วปุ่มต้องไม่หาย
 *
 * ตัวเลือกโหลดเมื่อกดปุ่ม "ดึงฝูงไก่ปัจจุบัน" (ผู้ใช้สั่ง) · ก่อนโหลด ช่องเลือกมีแค่ค่าเดิม
 * ของงานที่กำลังแก้ จะได้ไม่หายไปตอนบันทึก
 *
 * ใช้ :selected บน <option> แทนการใส่ค่าให้ <select> — ตัวเลือกมาจาก x-for
 * ถ้าใส่ค่าก่อน <option> เกิด ช่องจะค้างที่ตัวแรก (กับดัก §12m3 ใน CLAUDE.md)
 * เซิร์ฟเวอร์ตรวจซ้ำทุกอย่างใน routers/activities._farm_problem()
 */
function farmLink(cfg) {
  const saved = {
    flock: cfg.flockId ? { id: cfg.flockId, flock_code: cfg.flockCode, houses: '', age_days: null } : null,
    kind: cfg.kind, itemId: cfg.itemId, itemName: cfg.itemName,
  };
  return {
    cats: cfg.cats || [],
    category: cfg.category || '',
    flockId: cfg.flockId ? String(cfg.flockId) : '',
    item: cfg.kind && cfg.itemId ? cfg.kind + ':' + cfg.itemId : '',
    loaded: false,
    loading: false,
    error: '',
    flocks: saved.flock ? [saved.flock] : [],
    vaccines: saved.kind === 'vaccine' ? [{ id: saved.itemId, name: saved.itemName }] : [],
    types: saved.kind === 'activity' ? [{ id: saved.itemId, name: saved.itemName }] : [],

    get show() { return this.cats.includes(String(this.category)); },

    async load() {
      this.loading = true;
      this.error = '';
      try {
        const res = await fetch('/activities/farm-options', { headers: { Accept: 'application/json' } });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        this.flocks = data.flocks;
        this.vaccines = data.vaccines;
        this.types = data.activity_types;
        // ค่าเดิมของงานที่กำลังแก้อาจไม่อยู่ในรายการแล้ว (ฝูงปลดแล้ว / ปิดใช้วัคซีน)
        // เติมกลับเข้าไปให้เห็น ไม่งั้นกดบันทึกแล้วการผูกเดิมหายเงียบๆ
        if (saved.flock && !this.flocks.some(f => f.id === saved.flock.id)) {
          this.flocks.unshift({ ...saved.flock, flock_code: saved.flock.flock_code + ' (ไม่อยู่ในฝูงปัจจุบัน)' });
        }
        const keep = (list, kind) => {
          if (saved.kind === kind && !list.some(x => x.id === saved.itemId)) {
            list.unshift({ id: saved.itemId, name: saved.itemName + ' (ปิดใช้แล้ว)' });
          }
        };
        keep(this.vaccines, 'vaccine');
        keep(this.types, 'activity');
        this.loaded = true;
      } catch (e) {
        this.error = 'ดึงข้อมูลจาก RPF Farm ไม่ได้: ' + e.message;
      } finally {
        this.loading = false;
      }
    },

    flockLabel(f) {
      let s = f.flock_code;
      if (f.houses) s += ' · ' + f.houses;
      if (f.age_days !== null && f.age_days !== undefined) {
        s += ' · อายุ ' + Math.floor(f.age_days / 7) + ' สัปดาห์ ' + (f.age_days % 7) + ' วัน';
      }
      return s;
    },

    /* ชื่องานว่างอยู่ → เติมให้จากสิ่งที่เลือก · มีชื่ออยู่แล้วไม่ทับ */
    suggestTitle() {
      const title = document.getElementById('title');
      if (!title || title.value.trim() || !this.flockId || !this.item) return;
      const f = this.flocks.find(x => String(x.id) === this.flockId);
      const [kind, id] = this.item.split(':');
      const list = kind === 'vaccine' ? this.vaccines : this.types;
      const it = list.find(x => String(x.id) === id);
      if (!f || !it) return;
      const code = f.flock_code.replace(' (ไม่อยู่ในฝูงปัจจุบัน)', '');
      title.value = (kind === 'vaccine' ? 'ทำวัคซีน ' : '') + it.name + ' — ' + code;
    },
  };
}
