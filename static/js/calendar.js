/* calendar.js — สถานะของหน้าปฏิทิน

   แผงข้างมีสี่สภาพ:
     tab = 'next'    ลิสต์งานต่อไป (กำลังทำ + วันนี้ + วันถัดๆ ไป เรียงลงมาเป็นชุดเดียว)
     tab = 'overdue' ลิสต์งานค้าง
     tab = 'staff'   ใครลา / ใครมาทำงาน ในวันที่เลือก (v2) — แถบเดียวที่ผูกกับวันในปฏิทิน
     picked          รายละเอียดของกิจกรรมที่กดเลือก (จากแถบในปฏิทินหรือจากลิสต์)

   ข้อมูลทั้งหมดถูกส่งมาพร้อมหน้าตั้งแต่แรก การกดจึงตอบสนองทันทีโดยไม่ต้องยิงกลับ
   ไปที่เซิร์ฟเวอร์ — สำคัญมากบนมือถือที่เน็ตฟาร์มช้า

   ข้อความวันที่ไทยทั้งหมดจัดรูปมาจากฝั่งเซิร์ฟเวอร์แล้ว (ดู view.panel_data)
   ไฟล์นี้จึงไม่ต้องรู้เรื่องปี พ.ศ. หรือชื่อเดือนไทยเลย */

function calendarPage(data) {
  return {
    items: data.items || [],            // กิจกรรมของเดือนที่กำลังดู — ใช้หาตัวที่กดบนปฏิทิน
    nextItems: data.next || [],
    overdueItems: data.overdue || [],

    // แถบพนักงาน — ทะเบียนคนกับรายการลาที่คาบเดือนนี้ ส่งมาทีเดียว
    // แยก "ลา / มาทำงาน" ตามวันที่กดที่นี่ (เทียบ ISO เป็นข้อความได้ตรงๆ)
    staff: data.staff || [],
    leaves: data.leaves || [],
    dayLabels: data.dayLabels || {},    // ชื่อวันไทยจากเซิร์ฟเวอร์ — ห้ามจัดรูปวันไทยใน JS
    canManage: !!data.canManage,

    tab: 'next',
    pickedId: data.picked || null,      // กางรายละเอียดค้างไว้ตั้งแต่โหลดหน้า (ดู pick())
    selDate: data.selected || null,     // วันที่ไฮไลต์ไว้ในตาราง
    todayIso: data.today || '',         // ใช้เป็นเพดานของช่อง "แก้วันเริ่มงาน"

    init() {
      // กลับมาจากหน้าวันลา (ปุ่มลัดในแถบพนักงาน) ให้เปิดแถบพนักงานต่อ
      if (data.tab === 'staff') {
        this.tab = 'staff';
        return;
      }
      // เปิดแถบให้ตรงกับที่ผู้ใช้กดมา หลังโหลดหน้าใหม่เพราะเลื่อนเดือน
      // ไม่ต้องส่งชื่อแถบมาทาง URL — ดูจากว่ากิจกรรมนั้นอยู่ลิสต์ไหนก็รู้แล้ว
      const inOverdue = id => this.overdueItems.some(a => a.id === id);
      if ((this.pickedId && inOverdue(this.pickedId))
          || (this.overdueItems.length && !this.nextItems.length)) {
        this.tab = 'overdue';
      }
    },

    /** วันที่แถบพนักงานกำลังแสดง — ไม่ได้เลือกวัน = วันนี้ */
    get staffDay() {
      return this.selDate || this.todayIso;
    },

    get dayLeaves() {
      const d = this.staffDay;
      return this.leaves.filter(l => l.from <= d && d <= l.to);
    },

    /** คนที่มาทำงาน = ทุกคนในทะเบียน − คนที่ลาวันนั้น (รวมลาครึ่งวัน)
     *  เฟส C จะแยกต่อว่าประจำจุดงานไหน หรือว่างจริง */
    get dayPresent() {
      const away = new Set(this.dayLeaves.map(l => l.staff_id));
      return this.staff.filter(s => !away.has(s.id));
    },

    /** จัดกลุ่มคนที่มาทำงานตามฝ่าย — ทะเบียนส่งมาเรียงตามฝ่ายอยู่แล้ว จึงแค่หั่นตามชื่อ */
    get presentGroups() {
      const groups = [];
      for (const s of this.dayPresent) {
        const name = s.department || 'ยังไม่ระบุฝ่าย';
        const last = groups[groups.length - 1];
        if (last && last.name === name) {
          last.staff.push(s);
        } else {
          groups.push({ name, staff: [s] });
        }
      }
      return groups;
    },

    /** กดแถบ "ลา …" บนปฏิทิน — เปิดแถบพนักงานของวันนั้น */
    pickStaffDay(iso) {
      this.selDate = iso;
      this.pickedId = null;
      this.tab = 'staff';
      this.syncUrl();
      this.$nextTick(() => {
        const panel = document.querySelector('.cal-panel');
        if (panel && window.innerWidth < 900) {
          panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    },

    get listItems() {
      return this.tab === 'overdue' ? this.overdueItems : this.nextItems;
    },

    /** กิจกรรมที่กำลังกางรายละเอียดอยู่
     *
     *  หาจากทั้งสามชุด เพราะตัวที่กดจากปฏิทินอาจไม่ได้อยู่ในลิสต์ใดเลย
     *  (เช่นงานที่ปิดไปแล้ว หรืองานที่อยู่ไกลเกินช่วงที่แผงมองไปข้างหน้า)
     */
    get picked() {
      if (this.pickedId === null) return null;
      return this.find(this.pickedId);
    },

    find(id) {
      return this.items.find(a => a.id === id)
          || this.nextItems.find(a => a.id === id)
          || this.overdueItems.find(a => a.id === id)
          || null;
    },

    /** URL ที่จะกลับมาหลังกดเริ่ม/สิ้นสุด — คงเดือนและตัวที่เลือกไว้เหมือนเดิม */
    get backUrl() {
      const url = new URL(window.location.href);
      if (this.selDate) url.searchParams.set('d', this.selDate);
      return url.pathname + url.search;
    },

    showTab(name) {
      this.tab = name;
      this.clearPick();
    },

    /** ลิงก์ปุ่ม "+ บันทึกการลา" — กลับมาที่เดือนนี้ วันนี้ และแถบพนักงานหลังบันทึก */
    get leaveAddUrl() {
      const back = new URL(window.location.href);
      if (this.selDate) back.searchParams.set('d', this.selDate);
      back.searchParams.set('tab', 'staff');
      back.searchParams.delete('a');
      return '/leaves?add=1&date=' + this.staffDay
           + '&next=' + encodeURIComponent(back.pathname + back.search);
    },

    /** กดกิจกรรมจากลิสต์
     *
     *  ถ้ากิจกรรมนั้นไม่ได้อยู่ในตารางที่เห็นอยู่ (ลิสต์มองไปข้างหน้า 30 วัน
     *  จึงมีของเดือนถัดไปปนอยู่) ให้เลื่อนปฏิทินตามไปด้วย ไม่งั้นผู้ใช้จะเห็น
     *  รายละเอียดของงานที่หาไม่เจอบนตารางตรงหน้า
     *
     *  เช็กจาก items ซึ่งเป็นของที่วาดอยู่บนตารางจริงๆ ไม่ใช่เทียบเลขเดือน —
     *  ตารางเดือนมีวันของเดือนข้างเคียงติดมาด้วยเสมอ ถ้าเทียบเลขเดือนจะเด้ง
     *  ทั้งที่งานนั้นมองเห็นอยู่แล้ว
     */
    pick(id) {
      const item = this.find(id);
      if (item && item.date && !this.items.some(a => a.id === id)) {
        this.goToMonth(item.date, id);
        return;
      }
      this.pickedId = id;
      // เลื่อนแผงขึ้นให้เห็นหัวข้อ สำคัญบนมือถือที่แผงอยู่ใต้ปฏิทิน
      this.$nextTick(() => {
        const panel = document.querySelector('.cal-panel');
        if (panel && window.innerWidth < 900) {
          panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    },

    /** โหลดหน้าใหม่ไปที่เดือนของ iso แล้วกางรายละเอียดของ id ต่อ
     *
     *  ต่อพารามิเตอร์ลงบน URL ปัจจุบัน ตัวกรองที่ผู้ใช้ตั้งไว้จึงติดไปด้วย
     */
    goToMonth(iso, id) {
      const [y, m] = iso.split('-');
      const url = new URL(window.location.href);
      url.searchParams.set('y', String(Number(y)));
      url.searchParams.set('m', String(Number(m)));
      url.searchParams.set('d', iso);
      url.searchParams.set('a', String(id));
      window.location.assign(url.pathname + url.search);
    },

    clearPick() {
      this.pickedId = null;
      this.syncUrl();
    },

    /** กดแถบกิจกรรมบนปฏิทิน — กางรายละเอียดของงานนั้นในแผงข้าง */
    pickActivity(id, startIso) {
      if (this.pickedId === id) {       // กดซ้ำตัวเดิม = ปิด กลับไปดูลิสต์
        this.clearPick();
        return;
      }
      this.selDate = startIso;
      this.pick(id);
      this.syncUrl();
    },

    /** กดช่องวัน — ไฮไลต์ไว้เฉยๆ ใช้เป็นวันตั้งต้นตอนกดเพิ่มงาน
     *  ในแถบพนักงาน กดซ้ำไม่ยกเลิกการเลือก ไม่งั้นแถบจะเด้งกลับไปแสดงวันนี้เฉยๆ */
    pickDay(iso) {
      this.selDate = (this.selDate === iso && this.tab !== 'staff') ? null : iso;
      this.pickedId = null;
      this.syncUrl();
    },

    /** เขียนวันที่เลือกลง URL เพื่อให้กดรีเฟรชหรือแชร์ลิงก์แล้วยังอยู่ที่เดิม */
    syncUrl() {
      const url = new URL(window.location.href);
      if (this.selDate) {
        url.searchParams.set('d', this.selDate);
      } else {
        url.searchParams.delete('d');
      }
      // a มีไว้ใช้ครั้งเดียวตอนโหลดหน้า ถ้าค้างไว้ กดรีเฟรชแล้วรายละเอียด
      // จะเด้งกลับมาเองทั้งที่ผู้ใช้ปิดไปแล้ว
      if (this.pickedId) {
        url.searchParams.set('a', String(this.pickedId));
      } else {
        url.searchParams.delete('a');
      }
      // จำเฉพาะแถบพนักงาน — สองแถบแรกเดาจากข้อมูลได้เอง (ดู init)
      if (this.tab === 'staff') {
        url.searchParams.set('tab', 'staff');
      } else {
        url.searchParams.delete('tab');
      }
      history.replaceState(null, '', url.pathname + url.search);
    },
  };
}
