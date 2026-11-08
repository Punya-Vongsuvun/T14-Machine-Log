# T14 Machine Log

โปรแกรมบันทึกปัญหา / การปรับปรุงเครื่องจักรของ **Production Line T14**
ใช้บน Windows เครื่องเดียว ผ่าน Browser (`http://localhost:8014`) — **Offline** ข้อมูลเก็บในโฟลเดอร์โปรแกรม ไม่ส่งออกภายนอก

**เวอร์ชันปัจจุบัน: v1.10.3**

## ฟังก์ชันหลัก
- **บันทึกงาน** — ยอดผลิตรายวัน (เป้าหมาย / ผลิตได้ / ผลต่าง / วันหยุด) + 2 กรอบ: ปัญหาเครื่องจักร (เวลา, คิดจากยอดผลิต, Stop Line, Monday Cleaning) และการปรับปรุง, ไฟล์แนบ, แก้วันที่ / ย้ายวัน
- **รายงาน** — A4 แนวนอน พิมพ์ / PDF / Excel, ตัวกรอง ประเภท / เครื่องจักร / Size / กะ / สถานะ (พิมพ์เฉพาะประเภทที่เลือก)
- **Dashboard** — กล่องตัวเลข 10 กล่อง + กราฟแท่ง 4 กราฟ, เปรียบเทียบช่วงเวลา, พิมพ์ A4 1 หน้า
- **ตั้งค่า** — Master (เครื่องจักร / Size / ผู้รับผิดชอบ), Backup / Restore อัตโนมัติ

## ติดตั้งใช้งาน (Windows)
1. ดาวน์โหลด `T14-Machine-Log-v1.10.3-win64.zip` จาก **[Releases](../../releases/latest)** (มี Python รวมมาในตัว ไม่ต้องติดตั้งอะไรเพิ่ม)
2. คลิกขวา → **Extract All…** (ห้ามเปิดจากใน zip) แนะนำวางที่ไดรฟ์ในเครื่อง เช่น `D:\T14-Machine-Log` — **ไม่แนะนำโฟลเดอร์เครือข่าย** (ฐานข้อมูล SQLite)
3. ดับเบิลคลิก **`Start.bat`** → Browser เปิดหน้าโปรแกรมให้เอง

คู่มือใช้งานเต็ม / การอัปเดตเวอร์ชัน / การสำรองข้อมูล: **[README_TH.md](README_TH.md)**

## สำหรับผู้พัฒนา
- Python 3.13 + FastAPI + SQLite, HTML/CSS/JavaScript (ไม่มี Framework), Chart.js — ไม่ใช้ CDN
- รันทดสอบ: `pip install -r requirements.txt pytest httpx` แล้ว `python -m pytest`
- รันโปรแกรม: `python run.py`
- สร้างชุด Windows: `python tools/build_windows.py` → `dist/T14-Machine-Log-v<เวอร์ชัน>-win64.zip`
- กติกาโครงการ / ขอบเขตที่อนุมัติ: [PROJECT_RULES.md](PROJECT_RULES.md) · สถานะ: [progress.md](progress.md) · ประวัติ: [progress-history.md](progress-history.md)
- **`data/` และ `backups/` ไม่ขึ้น Git** (ข้อมูลจริงของโรงงาน)
