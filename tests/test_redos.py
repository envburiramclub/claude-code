"""เทสต์ ReDoS: regex ทุกตัวในโค้ดของ repo ต้องใช้เวลาแบบเส้นตรงกับข้อความที่จงใจสร้าง

ทุกระบบรับข้อมูลที่ไม่น่าเชื่อถือ (ไฟล์ CSV, ไฟล์ PDF, ข้อความจาก OCR) regex อย่าง /[ \\t]+$/ หรือ
/\\d+\\.?\\d*$/ ใช้เวลาแบบกำลังสองเมื่อเจอตัวอักษรซ้ำยาว ๆ ที่ไม่ match ทำให้หน้าเว็บหรือโปรแกรมค้างได้
เทสต์นี้ดึง regex จากซอร์สทุกไฟล์ (ยกเว้นไลบรารีใน vendor/) แล้ววัดเวลากับข้อความซ้ำ 20,000 ตัว

    python3 -m unittest discover -s tests -v
"""

import ast
import json
import os
import re
import shutil
import subprocess
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
FUZZ = os.path.join(ROOT, "tests", "redos_fuzz.js")
SKIP_DIRS = {"vendor", "node_modules"}

LENGTH = 20000
# regex แบบเส้นตรงใช้เวลาไม่ถึง 1 ms กับข้อความยาวเท่านี้ แบบกำลังสองใช้หลายร้อย ms ขึ้นไป
LIMIT_MS = 50
ATOMS = ["1", "a", " ", ".", "-", "_", "0", "\t", "\n", "\u0e01", "\u0e48", "\u0e33", "/", "\\", "%", "=", "(", ")",
         "<", "&", "#", ",", "@", ":", "+", "e", "E", "A", "x", "9.", "1 ", " 1", "a.", "-1", ".1", "1-",
         "\u0e01\u0e48", "\u3000", "\u00a0", "\ufffd", "\x00"]
TAILS = ["", "!", "x", "\x00", "\n", "~~", "\ud800"]


def source_files(extensions):
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")) and d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(extensions):
                yield os.path.join(folder, name)


def js_regex_literals(path):
    """ดึง regex literal จากไฟล์ JavaScript แบบคร่าว ๆ (ข้ามสตริงและคอมเมนต์)"""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    found, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            quote, i = c, i + 1
            while i < n and src[i] != quote:
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if src.startswith("//", i):
            end = src.find("\n", i)
            i = n if end < 0 else end
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c == "/":
            j = i - 1
            while j >= 0 and src[j] in " \t\n":
                j -= 1
            prev = src[j] if j >= 0 else ""
            word = re.search(r"[A-Za-z_$]{1,20}\Z", src[max(0, j - 19):j + 1])
            if prev in "(,=:!&|?;{}[+" or (word and word.group(0) in ("return", "typeof")):
                k, in_class = i + 1, False
                while k < n and src[k] != "\n":
                    if src[k] == "\\":
                        k += 2
                        continue
                    if src[k] == "[":
                        in_class = True
                    elif src[k] == "]":
                        in_class = False
                    elif src[k] == "/" and not in_class:
                        break
                    k += 1
                if k < n and src[k] == "/":
                    flags = re.match(r"[dgimsuyv]*", src[k + 1:]).group(0)
                    found.append({"file": os.path.relpath(path, ROOT), "line": src.count("\n", 0, i) + 1,
                                  "source": src[i + 1:k], "flags": flags})
                    i = k + 1 + len(flags)
                    continue
        i += 1
    return found


def python_regexes(path):
    """regex ที่เป็นสตริงคงที่ใน re.compile/re.sub/... ของไฟล์ Python"""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                and node.func.attr in ("compile", "match", "search", "fullmatch", "sub", "subn", "split", "findall", "finditer")
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            flags = 0
            for part in ast.walk(node):
                if (isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name)
                        and part.value.id == "re" and part.attr.isupper()):
                    flags |= getattr(re, part.attr)
            found.append((os.path.relpath(path, ROOT), node.lineno, node.args[0].value, flags))
    return found


class RegexTimeTest(unittest.TestCase):
    def test_extractor_finds_regexes(self):
        # ตัวดึง regex ต้องยังทำงาน ไม่เช่นนั้นเทสต์ด้านล่างจะผ่านโดยไม่ได้ตรวจอะไรเลย
        found = [r for path in source_files((".js", ".mjs")) for r in js_regex_literals(path)]
        self.assertGreater(len(found), 100)
        self.assertTrue(any(r["file"].startswith("doc2pdf") for r in found))
        self.assertGreater(len([r for path in source_files((".py",)) for r in python_regexes(path)]), 15)

    @unittest.skipUnless(NODE, "ต้องมี Node.js")
    def test_javascript_regexes_run_in_linear_time(self):
        found = [r for path in source_files((".js", ".mjs")) for r in js_regex_literals(path)]
        options = json.dumps({"ATOMS": ATOMS, "TAILS": TAILS, "LENGTH": LENGTH, "LIMIT_MS": LIMIT_MS})
        result = subprocess.run([NODE, FUZZ, options], input=json.dumps(found).encode("utf-8"),
                                capture_output=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        slow = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(slow, [], "regex เหล่านี้ใช้เวลาแบบกำลังสอง ให้เขียนใหม่ (เช่น ตัดท้ายข้อความด้วยลูปจากท้ายสตริง)")

    def test_python_regexes_run_in_linear_time(self):
        slow = []
        for path in source_files((".py",)):
            if os.sep + "tests" + os.sep in path:
                continue
            for where, line, pattern, flags in python_regexes(path):
                try:
                    compiled = re.compile(pattern, flags)
                except re.error:
                    continue
                worst = 0.0
                for atom in ATOMS:
                    for tail in TAILS:
                        if worst > LIMIT_MS:
                            break  # เจอข้อความที่ช้าแล้ว ไม่ต้องวัดต่อ
                        text = atom * (LENGTH // len(atom)) + tail
                        start = time.perf_counter()
                        compiled.search(text)
                        compiled.match("x" + text)
                        worst = max(worst, (time.perf_counter() - start) * 1000)
                if worst > LIMIT_MS:
                    slow.append("%s:%d %r (%.0f ms)" % (where, line, pattern, worst))
        self.assertEqual(slow, [])


if __name__ == "__main__":
    unittest.main()
