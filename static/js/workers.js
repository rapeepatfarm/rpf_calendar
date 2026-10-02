/* workers.js — ตัวเลือกผู้ปฏิบัติงานในฟอร์มกิจกรรม (v2 เฟส D)

   ป้ายความว่างต่อคนคิดจากวันที่กรอกในฟอร์ม (เปลี่ยนวันแล้วคิดใหม่ทันที ไม่ยิงเซิร์ฟเวอร์)
   ข้อมูลดิบมาจาก staffing.availability_data(): ช่วง ISO ของ ลา / ประจำจุด / งานอื่น ต่อคน

   สองระดับตาม §29.5:
     away  = ลา "ทุกวัน" ของช่วงงาน  → ติ๊กไม่ได้ (เซิร์ฟเวอร์ปฏิเสธซ้ำใน _workers_problem)
     warn  = ลาบางวัน / ประจำจุดงาน / มีงานอื่นคาบช่วงนี้ → แค่บอก ยังเลือกได้

   เทียบวันเป็นข้อความ ISO (YYYY-MM-DD เรียงตามตัวอักษรตรงกับลำดับวัน) ไม่แตะเรื่องวันไทย */

function workerPicker(data) {
  const overlaps = (r, start, end) => r.from <= end && r.to >= start;

  /** ลาครบทุกวันของช่วงไหม — นับวันที่ถูกคาบด้วยรายการลาใดๆ */
  function coversAll(leaves, start, end) {
    const s = new Date(start + 'T00:00:00'), e = new Date(end + 'T00:00:00');
    for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
      const iso = d.toISOString().slice(0, 10);
      if (!leaves.some(l => l.from <= iso && iso <= l.to)) return false;
    }
    return true;
  }

  return {
    picked: (data.chosen || []).map(String),
    dept: '',                       // ฝ่ายที่กางรายชื่ออยู่ — ว่าง = ยังไม่กางใคร
    avail: data.avail || {},
    start: data.start || '',
    end: data.end || data.start || '',

    setRange(start, end) {
      this.start = start || this.start;
      this.end = (end && end >= this.start) ? end : this.start;
      // คนที่เพิ่งกลายเป็น "ลาตลอดช่วง" ต้องหลุดออกจากที่ติ๊กไว้ ไม่งั้นส่งไปแล้วเซิร์ฟเวอร์ตีกลับ
      this.picked = this.picked.filter(id => !this.state(Number(id)).away);
    },

    state(id) {
      const start = this.start, end = this.end || start;
      if (!start) return { away: false, warn: false, label: '', title: '' };
      const leaves = (this.avail.leaves || {})[id] || [];
      const duty = (this.avail.duty || {})[id] || [];
      const busy = (this.avail.busy || {})[id] || [];

      const leaveHit = leaves.filter(l => overlaps(l, start, end));
      if (leaveHit.length && coversAll(leaveHit, start, end)) {
        return { away: true, warn: false, label: ' · ลา', title: 'ลาตลอดช่วงงานนี้ เลือกไม่ได้' };
      }
      const notes = [];
      if (leaveHit.length) notes.push('ลาบางวัน');
      const post = duty.find(a => overlaps(a, start, end));
      if (post) notes.push('ประจำ ' + post.post);
      const other = busy.find(b => overlaps(b, start, end) && String(b.id) !== String(data.activityId || ''));
      if (other) notes.push('มีงานอื่น');
      return {
        away: false, warn: notes.length > 0,
        label: notes.length ? ' · ' + notes.join(' · ') : '',
        title: other ? ('มีงานอื่นช่วงนี้: ' + other.title) : (notes.join(' · ')),
      };
    },

    /** มีใครในกลุ่มนี้ถูกติ๊กไว้ไหม — ใช้ให้กลุ่มนั้นยังกางอยู่แม้จะเปลี่ยนฝ่ายไปแล้ว
     *  ไม่งั้นคนที่ติ๊กไว้จะหายจากสายตา แล้วผู้ใช้เผลอกดบันทึกทั้งที่ยังอยู่ในฟอร์ม */
    hasPicked(ids) {
      return ids.some(id => this.picked.includes(String(id)));
    },

    allPicked(ids) {
      const open = ids.filter(id => !this.state(id).away).map(String);
      return open.length > 0 && open.every(id => this.picked.includes(id));
    },

    /** เลือกทั้งฝ่าย = ติ๊กทุกคนในฝ่ายที่เลือกได้ · กดซ้ำเมื่อครบแล้ว = เอาออกทั้งฝ่าย
     *  บันทึกเป็นรายคน (ไม่ใช่ "ฝ่าย X") เพราะสมาชิกฝ่ายเปลี่ยนได้ กิจกรรมต้องจำว่าตอนนั้นใครถูกเลือก */
    toggleDept(ids) {
      const open = ids.filter(id => !this.state(id).away).map(String);
      if (this.allPicked(ids)) {
        this.picked = this.picked.filter(id => !open.includes(id));
      } else {
        this.picked = [...new Set([...this.picked, ...open])];
      }
    },
  };
}
