/* service worker ของ RPF Calendar
 *
 * เสิร์ฟจาก /sw.js (ดู route ใน main.py) ไม่ใช่ /static/sw.js
 *   ขอบเขตของ service worker เท่ากับโฟลเดอร์ที่มันถูกเสิร์ฟออกมา ถ้าวางไว้ใต้
 *   /static/ มันจะคุมได้แค่ /static/** ซึ่งไม่ครอบ start_url ของ manifest (/calendar)
 *   แล้ว Chrome บน Android จะไม่ขึ้นปุ่ม "ติดตั้งแอป" ให้
 *
 * ── ตั้งใจให้ทำน้อยที่สุด ────────────────────────────────────────
 * แคชเฉพาะไฟล์ใน /static/ (css, js, ไอคอน) เท่านั้น
 * HTML ทุกหน้าและทุก POST ปล่อยผ่านไปหาเซิร์ฟเวอร์ตรง ๆ ไม่แตะเลย
 *
 * เพราะข้อมูลในโปรแกรมนี้เปลี่ยนตลอดเวลาและมีการล็อกอิน ถ้าแคชหน้า HTML ไว้
 * จะเกิดสองอาการที่แย่กว่าไม่มี service worker เลย
 *   1. เห็นตารางงานของเมื่อวาน แล้วนึกว่าไม่มีใครแก้อะไร
 *   2. คนถัดไปที่มาใช้เครื่องเดียวกันเห็นหน้าที่คนก่อนหน้าเปิดค้างไว้
 *
 * ใช้ cache-first กับ /static/ ได้อย่างปลอดภัย เพราะ view.asset() ต่อ ?v=<mtime>
 * ท้าย URL ทุกไฟล์ (กติกาข้อ 12f ใน CLAUDE.md) แก้ไฟล์เมื่อไร URL เปลี่ยนทันที
 * ของเก่าจึงไม่มีวันถูกหยิบมาใช้
 *
 * ── ถ้าจะเลิกใช้ ────────────────────────────────────────────────
 * แทนที่ทั้งไฟล์นี้ด้วย
 *     self.addEventListener('install', () => self.skipWaiting());
 *     self.addEventListener('activate', async () => {
 *       for (const k of await caches.keys()) await caches.delete(k);
 *       await self.registration.unregister();
 *     });
 * แล้วลบสคริปต์ register ใน base.html ออก · เบราว์เซอร์ทุกเครื่องจะถอนตัวเอง
 * ตอนเข้าเว็บครั้งถัดไป (ห้ามลบไฟล์เฉย ๆ ตัวที่ติดตั้งไปแล้วจะอยู่ต่อไปเรื่อย ๆ)
 */

const CACHE = 'rpf-cal-static-v1';

self.addEventListener('install', () => {
  // ไม่ pre-cache อะไรเลย เก็บเฉพาะไฟล์ที่ถูกขอจริงระหว่างใช้งาน
  // รายการไฟล์ที่เขียนตายตัวไว้จะล้าสมัยเงียบ ๆ ทุกครั้งที่มีคนเพิ่มไฟล์ static
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith('/static/')) return;   // HTML และ API ไม่แตะ

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    if (hit) return hit;

    const res = await fetch(req);
    if (res.ok && res.type === 'basic') {
      // เก็บของใหม่แล้วทิ้งเวอร์ชันเก่าของไฟล์เดียวกัน (path เดียวกัน คนละ ?v=)
      // ไม่งั้นทุกครั้งที่แก้ css จะเหลือขยะสะสมไปเรื่อย ๆ ไม่มีใครลบ
      cache.put(req, res.clone());
      for (const k of await cache.keys()) {
        const ku = new URL(k.url);
        if (ku.pathname === url.pathname && ku.search !== url.search) {
          await cache.delete(k);
        }
      }
    }
    return res;
  })());
});
