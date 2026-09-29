# claude-code — รวมเครื่องมือ

หน้าหลัก <https://envburiramclub.github.io/claude-code/> รวมลิงก์ไปทุกระบบใน repo นี้
ใช้งานผ่านเบราว์เซอร์ได้ทันทีทั้งบนคอมพิวเตอร์และมือถือ ไม่ต้องติดตั้งโปรแกรม

| โฟลเดอร์ | ระบบ | เปิดใช้งาน |
| --- | --- | --- |
| [`bg-remove/`](bg-remove/) | ลบพื้นหลังรูปภาพด้วย AI ในเบราว์เซอร์ รองรับ JPG PNG BMP WebP HEIC SVG ICO GIF TIFF | <https://envburiramclub.github.io/claude-code/bg-remove/> |
| [`csv2vcf/`](csv2vcf/) | แปลงรายชื่อ CSV เป็นไฟล์ vCard (.vcf) มีทั้งหน้าเว็บ คำสั่งในเทอร์มินัล และเว็บที่รันเอง | <https://envburiramclub.github.io/claude-code/csv2vcf/> |
| [`doc2pdf/`](doc2pdf/) | สแกนเอกสารเป็น PDF ครอปอัตโนมัติ OCR และแปลง PDF เป็นรูปหรือ Word | <https://envburiramclub.github.io/claude-code/doc2pdf/> |
| [`pdfedit/`](pdfedit/) | แก้ไข PDF: เพิ่มข้อความไทย ลายเซ็น รูป จัดการหน้า ตั้งรหัสผ่าน แปลงเป็นรูป และสรุป/ถามตอบด้วย AI | <https://envburiramclub.github.io/claude-code/pdfedit/> |
| [`qrcode-generator/`](qrcode-generator/) | สร้าง QR Code จากลิงก์ ข้อความ WiFi เบอร์โทร อีเมล และพร้อมเพย์ ใส่โลโก้ ดาวน์โหลด PNG/SVG | <https://envburiramclub.github.io/claude-code/qrcode-generator/> |

รายละเอียดของแต่ละระบบอยู่ใน `README.md` ในโฟลเดอร์ของระบบนั้น

## โครงสร้าง repo

หนึ่งระบบต่อหนึ่งโฟลเดอร์ ทุกระบบมี `index.html` เป็นหน้าแรก และมีการ์ดลิงก์จากหน้าหลัก

| ไฟล์ | หน้าที่ |
| --- | --- |
| `index.html`, `home.css`, `favicon.svg` | หน้าหลักที่รวมลิงก์ทุกระบบ (ไม่มีสคริปต์) |
| `tests/test_home.py` | ตรวจว่าหน้าหลักลิงก์ครบทุกโฟลเดอร์ ลิงก์ไม่เสีย ตั้งค่าความปลอดภัยครบ และซอร์สไม่มีอักขระล่องหน |
| `tests/test_redos.py`, `tests/redos_fuzz.js` | วัดเวลา regex ทุกตัวใน repo กับข้อความที่จงใจสร้าง (กัน ReDoS) |
| `tests/test_vendor.py` | ตรวจว่าไลบรารีใน `vendor/` ตรงกับค่า SHA-256 ใน `SHA256SUMS` |
| `.github/workflows/static.yml` | เผยแพร่ทั้ง repo ขึ้น GitHub Pages ทุกครั้งที่ push ขึ้น `main` |

**ทุกไฟล์ใน repo เป็นสาธารณะ:** workflow เผยแพร่ทั้ง repo ขึ้นเว็บ ห้าม commit ความลับหรือข้อมูลส่วนบุคคลจริง

## เพิ่มระบบใหม่

1. สร้างโฟลเดอร์ใหม่ที่โฟลเดอร์บนสุด ชื่อเป็นภาษาอังกฤษตัวพิมพ์เล็ก ตัวเลข และ `-` เช่น `qr-code`
2. ใส่ทุกไฟล์ของระบบในโฟลเดอร์นั้น มี `index.html` เป็นหน้าแรก ใช้ path แบบ relative
   และมีลิงก์กลับหน้าหลัก `../index.html`
3. เพิ่มการ์ดใน `index.html` และแถวในตารางด้านบน
4. รันเทสต์ `python3 -m unittest discover -s tests -v` (บางเทสต์ต้องมี Node.js ถ้าไม่มีจะข้าม)

## ทดสอบในเครื่อง

```bash
python3 -m http.server 8000
```

แล้วเปิด <http://127.0.0.1:8000/> (แบบเดียวกับบน GitHub Pages)
