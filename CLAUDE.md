# แนวทางการทำงานในรีโปนี้

- ทุกครั้งที่เขียนหรือแก้โค้ด ต้องตรวจสอบบั๊กและช่องโหว่ด้านความปลอดภัย แล้วแก้ไขให้เรียบร้อยก่อน commit
  (เช่น injection, ReDoS, path/file overwrite, การแสดงข้อมูลที่ไม่น่าเชื่อถือบน terminal) และเพิ่มเทสต์ป้องกันบั๊กซ้ำ
- รันเทสต์ให้ผ่านก่อน commit: `python3 -m unittest discover -s tests -v`
- ใช้เฉพาะ Python standard library (Python 3.8+)
- commit และ push ไปที่ branch `main` เท่านั้น
- ห้าม commit ไฟล์รายชื่อจริง (`*.csv`, `*.vcf`) ยกเว้นไฟล์ตัวอย่างใน `examples/`
