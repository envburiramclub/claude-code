# แนวทางการทำงานในรีโปนี้

- ตอบกลับและสรุปงานเป็นภาษาไทยทุกครั้ง รวมถึงข้อความ commit
- ทุกครั้งที่เขียนหรือแก้โค้ด ต้องตรวจสอบบั๊กและช่องโหว่ด้านความปลอดภัย แล้วแก้ไขให้เรียบร้อยก่อน commit
  (เช่น injection, ReDoS, path/file overwrite, การแสดงข้อมูลที่ไม่น่าเชื่อถือบน terminal) และเพิ่มเทสต์ป้องกันบั๊กซ้ำ
- รันเทสต์ให้ผ่านก่อน commit: `python3 -m unittest discover -s tests -v`
- ใช้เฉพาะ Python standard library (Python 3.8+)
- เว็บไซต์ GitHub Pages อยู่ใน `docs/` (HTML/CSS/JavaScript ไม่มี dependency ภายนอก ใช้ path แบบ relative)
  เมื่อแก้ `csv2vcf.py` ต้องแก้ `docs/csv2vcf.js` ให้ได้ผลเหมือนกัน และรัน `python3 tools/build_js_data.py`
  ถ้าแก้ตารางข้อมูล (`tests/test_static_site.py` เทียบผลสองภาษา ต้องมี Node.js)
- commit และ push ไปที่ branch `main` เท่านั้น
- ห้าม commit ไฟล์รายชื่อจริง (`*.csv`, `*.vcf`) ยกเว้นไฟล์ตัวอย่างใน `examples/` และ `docs/example.csv`
