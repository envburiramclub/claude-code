// ตัวกลางให้ tests/test_redos.py วัดเวลา regex ของ JavaScript กับข้อความที่จงใจสร้าง
// อ่านรายการ { file, line, source, flags } จาก stdin แล้วเขียนรายการ regex ที่ช้าออก stdout (JSON)
"use strict";
const { ATOMS, TAILS, LENGTH, LIMIT_MS } = JSON.parse(process.argv[2]);

const chunks = [];
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", () => {
  const slow = [];
  for (const r of JSON.parse(Buffer.concat(chunks).toString("utf8"))) {
    let re;
    try {
      // ไม่ใช้ g/y: ให้ทุกครั้งเริ่มค้นจากต้นข้อความ
      re = new RegExp(r.source, r.flags.replace(/[gy]/g, ""));
    } catch (error) {
      continue; // ไม่ใช่ regex จริง (ตัวแยกแบบคร่าว ๆ อาจจับผิด)
    }
    let worst = 0;
    let input = "";
    // หยุดทันทีที่เจอข้อความที่ช้า (regex ที่ช้าแบบกำลังสองใช้หลายวินาทีต่อข้อความ)
    for (const atom of ATOMS) {
      if (worst > LIMIT_MS) break;
      for (const tail of TAILS) {
        if (worst > LIMIT_MS) break;
        const text = atom.repeat(Math.ceil(LENGTH / atom.length)) + tail;
        const start = process.hrtime.bigint();
        re.test(text);
        re.test("x" + text);
        const ms = Number(process.hrtime.bigint() - start) / 1e6;
        if (ms > worst) {
          worst = ms;
          input = JSON.stringify(atom) + " x " + LENGTH + " + " + JSON.stringify(tail);
        }
      }
    }
    if (worst > LIMIT_MS) slow.push({ where: r.file + ":" + r.line, regex: "/" + r.source + "/" + r.flags, ms: Math.round(worst), input });
  }
  process.stdout.write(JSON.stringify(slow));
});
