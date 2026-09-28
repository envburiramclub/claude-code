// ตัวกลางให้ tests/test_doc2pdf.py เรียกโค้ด JavaScript ของ doc2pdf ใน Node
// โมดูลใน js/ เป็น IIFE ที่ผูกกับ window จึงโหลดใน vm ที่มี window จำลอง (ไม่มี DOM)
// อ่านรายการคำขอ JSON { fn, args } จาก stdin (ข้อมูลไบนารีเป็น { "__bytes__": base64 })
// แล้วเขียนผลลัพธ์ { ok, value, ms } ออก stdout ตามลำดับเดียวกัน
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const JS = path.join(__dirname, "..", "js");
const MODULES = ["thai-text.js", "zip.js", "docx.js", "pdf-export.js", "ocr.js", "pdf-actualtext.js", "pdf-tools.js"];

const ctx = {
  console, setTimeout, clearTimeout, Promise, TextEncoder, TextDecoder, URL, Blob, Response,
  CompressionStream, DecompressionStream,
  document: { baseURI: "https://example.test/doc2pdf/" },
  location: { protocol: "https:", href: "https://example.test/doc2pdf/" },
  navigator: {},
};
ctx.window = ctx;
ctx.self = ctx;
ctx.globalThis = ctx;
vm.createContext(ctx);
for (const name of MODULES) vm.runInContext(fs.readFileSync(path.join(JS, name), "utf8"), ctx, { filename: name });

const IDENTITY = [1, 0, 0, 1, 0, 0];
const UTIL = {
  transform: (a, b) => [
    a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5],
  ],
};

function bytesArg(value) {
  if (value && typeof value === "object" && typeof value.__bytes__ === "string") {
    return new Uint8Array(Buffer.from(value.__bytes__, "base64"));
  }
  return value;
}

async function blobToBase64(blob) {
  return { __bytes__: Buffer.from(await blob.arrayBuffer()).toString("base64") };
}

const API = {
  sanitizeFilename: (name) => ctx.PdfExport.sanitizeFilename(name),
  cleanText: (text) => ctx.Ocr.cleanText(text),
  // items: [{ str, x, y, width, hasEOL }] → ข้อความของแต่ละบรรทัด
  buildLines: (items) => ctx.PdfTools._buildLines(
    items.map((it) => ({ str: it.str, transform: [10, 0, 0, 10, it.x, it.y], width: it.width, height: 10, hasEOL: !!it.hasEOL })),
    IDENTITY, UTIL,
  ).map((line) => line.text),
  actualText: (pdf, pageNum) => ctx.PdfActualText.create(async () => pdf).forPage({ num: pageNum, gen: 0 }),
  xml: (text) => ctx.Docx.xml(text),
  zip: async (entries) => blobToBase64(await ctx.Zip.create(entries)),
  docx: async (opts) => blobToBase64(await ctx.Docx.create(opts)),
};

async function run(request) {
  const start = process.hrtime.bigint();
  try {
    const fn = API[request.fn];
    if (typeof fn !== "function") throw new Error("ไม่มีฟังก์ชัน " + request.fn);
    const value = await fn(...request.args.map(bytesArg));
    return { ok: true, value: value === undefined ? null : value, ms: Number(process.hrtime.bigint() - start) / 1e6 };
  } catch (error) {
    return { ok: false, error: String((error && error.message) || error), ms: Number(process.hrtime.bigint() - start) / 1e6 };
  }
}

const chunks = [];
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", async () => {
  const results = [];
  for (const request of JSON.parse(Buffer.concat(chunks).toString("utf8"))) results.push(await run(request));
  process.stdout.write(JSON.stringify(results));
});
