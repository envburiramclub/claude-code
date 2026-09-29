"""เทสต์ไลบรารีภายนอกที่เก็บไว้ใน repo (โฟลเดอร์ vendor/ ของแต่ละระบบ)

ไฟล์ใน vendor/ ถูกเผยแพร่และรันในเบราว์เซอร์ของผู้ใช้โดยตรง เทสต์นี้ตรวจว่าทุกไฟล์ตรงกับค่า SHA-256
ที่บันทึกไว้ใน SHA256SUMS (กันไฟล์ถูกแก้ไขหรือสลับโดยไม่ตั้งใจ) และไฟล์โค้ด/ข้อมูลใหม่ต้องมีค่า SHA-256 ด้วย

    python3 -m unittest discover -s tests -v
"""

import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ไฟล์ที่เบราว์เซอร์โหลดไปใช้งาน ต้องมีค่า SHA-256 ใน SHA256SUMS เสมอ (ไฟล์สัญญาอนุญาต/เอกสารไม่ต้อง)
CHECKED_EXTENSIONS = (".js", ".mjs", ".wasm", ".ttf", ".otf", ".woff", ".woff2", ".pfb", ".gz", ".json", ".css", ".onnx")
SUM_LINE = re.compile(r"([0-9a-f]{64}) [ *](\S[^\r\n]*)\Z")


def vendor_dirs():
    found = []
    for folder, dirs, _files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")))
        if os.path.basename(folder) == "vendor":
            found.append(folder)
            dirs[:] = []
    return found


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class VendorIntegrityTest(unittest.TestCase):
    def test_vendor_folders_exist(self):
        self.assertIn(os.path.join(ROOT, "doc2pdf", "vendor"), vendor_dirs())

    def test_files_match_recorded_checksums(self):
        for vendor in vendor_dirs():
            for folder, dirs, files in os.walk(vendor):
                dirs.sort()
                if "SHA256SUMS" not in files:
                    continue
                with open(os.path.join(folder, "SHA256SUMS"), encoding="ascii") as fh:
                    lines = [line.rstrip("\n") for line in fh if line.strip()]
                self.assertTrue(lines, folder)
                for line in lines:
                    with self.subTest(sums=os.path.relpath(folder, ROOT), line=line[66:]):
                        match = SUM_LINE.match(line)
                        self.assertIsNotNone(match, "รูปแบบบรรทัดไม่ถูกต้อง")
                        expected, name = match.groups()
                        path = os.path.normpath(os.path.join(folder, name))
                        # ชื่อไฟล์ใน SHA256SUMS ต้องอยู่ในโฟลเดอร์เดียวกัน (ไม่ใช้ .. หรือ path เต็ม)
                        self.assertTrue(path.startswith(folder + os.sep), name)
                        self.assertTrue(os.path.isfile(path), "ไม่มีไฟล์ " + name)
                        self.assertEqual(sha256(path), expected, "ไฟล์ %s ไม่ตรงกับค่า SHA-256 ที่บันทึกไว้" % name)

    def test_every_loaded_file_has_a_checksum(self):
        for vendor in vendor_dirs():
            covered = set()
            for folder, _dirs, files in os.walk(vendor):
                if "SHA256SUMS" in files:
                    with open(os.path.join(folder, "SHA256SUMS"), encoding="ascii") as fh:
                        for line in fh:
                            match = SUM_LINE.match(line.rstrip("\n"))
                            if match:
                                covered.add(os.path.normpath(os.path.join(folder, match.group(2))))
            for folder, _dirs, files in os.walk(vendor):
                for name in files:
                    path = os.path.join(folder, name)
                    if name.lower().endswith(CHECKED_EXTENSIONS):
                        with self.subTest(file=os.path.relpath(path, ROOT)):
                            self.assertIn(path, covered, "เพิ่มค่า SHA-256 ของไฟล์นี้ใน SHA256SUMS")


if __name__ == "__main__":
    unittest.main()
