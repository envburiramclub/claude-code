# ฝากไฟล์ (file-share/)

เปิดใช้งาน: <https://envburiramclub.github.io/claude-code/file-share/>

อัปโหลดไฟล์ละไม่เกิน 100 MB แล้วรับลิงก์ไปแชร์ เลือกที่ฝากได้ 3 แบบ:

| ที่ฝาก | เข้าสู่ระบบ | ข้อจำกัดสำคัญ |
| --- | --- | --- |
| Google Drive | Gmail ของผู้ใช้เอง | ใช้พื้นที่ Drive ของผู้ใช้ (ฟรี 15 GB) ไฟล์อยู่ในโฟลเดอร์ "ระบบฝากไฟล์" และระบบเห็นเฉพาะไฟล์ที่อัปโหลดผ่านระบบนี้ |
| Microsoft OneDrive | Outlook/Hotmail ของผู้ใช้เอง | ใช้พื้นที่ OneDrive ของผู้ใช้ (ฟรี 5 GB) ไฟล์อยู่ในโฟลเดอร์ Apps ของแอป บัญชีองค์กรอาจปิดลิงก์แชร์ |
| tmpfiles.org | ไม่ต้อง | สาธารณะ ไม่เกิน 100 MB (ฐานสิบ) ลบอัตโนมัติหลัง 60 นาที |
| Gofile.io | ไม่ต้อง | สาธารณะ ไฟล์ที่ไม่มีคนดาวน์โหลดนาน ๆ อาจถูกลบ ลบเองไม่ได้ |

- **ลิงก์แชร์:** ไฟล์ใน Drive/OneDrive เป็นส่วนตัว จนกว่าจะติ๊ก "ให้ทุกคนที่มีลิงก์ดาวน์โหลดได้"
- **ดูและลบไฟล์:** ดูรายการไฟล์ที่ฝากไว้และลบได้ (ไฟล์ไปอยู่ในถังขยะ กู้คืนได้)
- **ไม่มีเซิร์ฟเวอร์ของตัวเอง:** ไฟล์ส่งตรงจากเบราว์เซอร์ไปยังผู้ให้บริการด้วย REST API
- **ไม่มีไลบรารีภายนอก:** ไม่ใช้ CDN เลย เข้าสู่ระบบด้วย OAuth 2.0 ที่เขียนเอง
- **ไม่เก็บโทเคน:** โทเคนการเข้าสู่ระบบอยู่ในหน่วยความจำเท่านั้น (หมดอายุใน 1 ชั่วโมง ปิดหน้าแล้วต้องเข้าสู่ระบบใหม่)
- **เว็บฝากไฟล์ฟรีเป็นบริการภายนอก:** อาจปิด เปลี่ยน API หรือไม่รับไฟล์จากเว็บอื่นได้ทุกเมื่อ หน้าเว็บจะแจ้งให้ลองอีกบริการ

## ตั้งค่า Google Drive และ OneDrive (ผู้ดูแลระบบทำครั้งเดียว)

ต้องลงทะเบียนแอปกับ Google และ Microsoft แล้วใส่ Client ID ใน `js/config.js`
Client ID ไม่ใช่ความลับ ใส่ใน repo ได้ **ไม่ต้องสร้างและห้ามใส่ Client Secret**

redirect URI ที่ใช้ทั้งสองแห่ง (ต้องตรงทุกตัวอักษร):

```
https://envburiramclub.github.io/claude-code/file-share/index.html
```

### Google Drive

1. เข้า <https://console.cloud.google.com/> แล้วสร้างโปรเจกต์ใหม่
2. เปิด Google Drive API: APIs & Services → Library → "Google Drive API" → Enable
3. ตั้งค่า Google Auth Platform (หน้ายินยอม OAuth):
   - **Branding:** ชื่อแอป เช่น "ระบบฝากไฟล์" และอีเมลติดต่อ
   - **Audience:** External แล้วกด **Publish app** (สถานะ In production)
     ถ้ายังเป็น Testing จะใช้ได้เฉพาะอีเมลที่เพิ่มเป็น Test users
   - **Data Access:** เพิ่ม scope `https://www.googleapis.com/auth/drive.file`
     (สิทธิ์เฉพาะไฟล์ที่แอปสร้าง ไม่ใช่สิทธิ์อ่อนไหว จึงไม่ต้องขอตรวจสอบแอป)
4. สร้าง Client ID: **Clients** → Create client → Web application
   - Authorized JavaScript origins: `https://envburiramclub.github.io`
   - Authorized redirect URIs: URL ด้านบน
5. คัดลอก Client ID (ลงท้าย `.apps.googleusercontent.com`) ใส่ใน `googleClientId` ของ `js/config.js`

### Microsoft OneDrive

1. เข้า <https://entra.microsoft.com/> → App registrations → New registration
   - Name: เช่น "ระบบฝากไฟล์" (OneDrive สร้างโฟลเดอร์ Apps/ชื่อนี้)
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
     ถ้าเลือก "Personal Microsoft accounts only" ให้ตั้ง `microsoftAuthority: 'consumers'`
   - Redirect URI: แพลตฟอร์ม **Single-page application (SPA)** และ URL ด้านบน (ต้องเป็น SPA ไม่งั้นแลกรหัสเข้าสู่ระบบไม่ได้)
2. API permissions: Microsoft Graph → Delegated → `Files.ReadWrite` และ `User.Read`
3. คัดลอก Application (client) ID ใส่ใน `microsoftClientId` ของ `js/config.js`

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `index.html`, `css/app.css`, `favicon.svg` | หน้าเว็บ (CSP อนุญาตสคริปต์จากเว็บนี้เท่านั้น และส่งข้อมูลได้เฉพาะ API ของที่ฝากไฟล์) |
| `js/config.js` | Client ID ของ Google/Microsoft (ผู้ดูแลระบบใส่) |
| `js/core.js` | ฟังก์ชันล้วน: ขีดจำกัดไฟล์, ชื่อไฟล์, URL เข้าสู่ระบบ, PKCE, ตรวจลิงก์จาก API |
| `js/providers.js` | อัปโหลด/รายการ/ลบไฟล์ของ Google Drive, OneDrive, tmpfiles.org, Gofile ผ่าน REST API |
| `js/app.js` | ควบคุมหน้าเว็บ เข้าสู่ระบบแบบ redirect คิวอัปโหลด |
| `tests/test_fileshare.py`, `tests/harness.js` | เทสต์ฟังก์ชันใน `js/core.js` (Node.js) และตรวจความปลอดภัยของหน้าเว็บ |

## ความปลอดภัย

- **เข้าสู่ระบบ:** แบบ redirect ตามมาตรฐาน OAuth 2.0 และตรวจค่า `state` ทุกครั้ง
  - Google: implicit grant ได้โทเคนใน `#fragment`
  - Microsoft: authorization code + PKCE ไม่ใช้ Client Secret
  - โทเคนและรหัสถูกลบออกจาก URL ทันที
- **สิ่งที่เก็บในเครื่อง:**
  - `sessionStorage` เก็บเฉพาะ `state`/PKCE verifier ระหว่างไปหน้าเข้าสู่ระบบ (key `file-share:auth` ลบทันทีที่กลับมา อายุไม่เกิน 10 นาที)
  - `localStorage` เก็บแค่ที่ฝากที่เลือกล่าสุด (key `file-share:provider`)
- **ลิงก์และชื่อไฟล์:**
  - ลิงก์ที่ได้จาก API ต้องเป็น https และอยู่ในโดเมนของผู้ให้บริการเท่านั้น
  - ชื่อไฟล์ตัดอักขระล่องหน/กลับทิศข้อความก่อนแสดงและอัปโหลด

## เทสต์

```bash
python3 -m unittest discover -s tests -v
```

บางเทสต์ต้องมี Node.js ถ้าไม่มีจะข้าม
