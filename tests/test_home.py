"""เทสต์หน้าหลักของ repo (index.html ที่โฟลเดอร์บนสุด) ซึ่งรวมลิงก์ไปทุกระบบ

repo นี้เก็บหนึ่งระบบต่อหนึ่งโฟลเดอร์ ทุกโฟลเดอร์ต้องมี index.html และมีการ์ดลิงก์จากหน้าหลัก
ถ้าสร้างระบบใหม่แล้วลืมเพิ่มลิงก์ เทสต์นี้จะเตือน

    python3 -m unittest discover -s tests -v
"""

import os
import re
import unicodedata
import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# โฟลเดอร์บนสุดที่ไม่ใช่ระบบ (โฟลเดอร์ที่ขึ้นต้นด้วย . หรือ _ เช่น .github, __pycache__ ก็ไม่นับ)
NOT_APPS = {"tests"}
# ชื่อโฟลเดอร์ของระบบ: ภาษาอังกฤษตัวพิมพ์เล็ก ตัวเลข และ - ใช้เป็น URL ได้โดยไม่ต้อง escape
FOLDER_NAME = re.compile(r"[a-z0-9]{1,40}(?:-[a-z0-9]{1,40}){0,5}\Z")
# ระบบที่ใช้หน้า index.html ร่วมกับแพลตฟอร์มอื่น (เวอร์ชัน Google Apps Script และแอป Android)
# ใส่ลิงก์ ../index.html ไม่ได้เพราะที่นั่นไม่มีหน้าหลักนี้
NO_HOME_LINK = {"doc2pdf"}
# ไฟล์ซอร์สที่ตรวจอักขระล่องหน
SOURCE_EXTENSIONS = (".html", ".css", ".js", ".mjs", ".py", ".md", ".svg", ".json", ".yml", ".yaml", ".csv", ".txt")


def app_folders():
    return sorted(
        name for name in os.listdir(ROOT)
        if os.path.isdir(os.path.join(ROOT, name)) and not name.startswith((".", "_")) and name not in NOT_APPS
    )


class _TagCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def parse_tags(path):
    """คืนรายการ (ชื่อแท็ก, attribute) ทุกแท็กในไฟล์ HTML"""
    collector = _TagCollector()
    with open(path, encoding="utf-8") as fh:
        collector.feed(fh.read())
    collector.close()
    return collector.tags


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


class HomePageTest(unittest.TestCase):
    def setUp(self):
        self.tags = parse_tags(os.path.join(ROOT, "index.html"))
        self.cards = [
            attrs.get("href") for tag, attrs in self.tags
            if tag == "a" and "app" in (attrs.get("class") or "").split()
        ]

    def test_every_folder_is_linked_from_home_page(self):
        folders = app_folders()
        self.assertIn("csv2vcf", folders)
        for name in folders:
            with self.subTest(folder=name):
                self.assertRegex(name, FOLDER_NAME, "ชื่อโฟลเดอร์ต้องเป็นตัวพิมพ์เล็ก ตัวเลข และ - เท่านั้น")
                self.assertTrue(os.path.isfile(os.path.join(ROOT, name, "index.html")), "ทุกระบบต้องมี index.html")
                self.assertIn(name + "/index.html", self.cards, "ให้เพิ่มการ์ดของ %s/ ใน index.html" % name)

    def test_every_card_points_to_a_folder(self):
        # ไม่มีการ์ดซ้ำ และไม่มีการ์ดที่ชี้ไปโฟลเดอร์ที่ถูกลบหรือเปลี่ยนชื่อไปแล้ว
        self.assertEqual(sorted(self.cards), [name + "/index.html" for name in app_folders()])

    def test_links_are_relative_and_exist(self):
        for tag, attrs in self.tags:
            for key in ("href", "src"):
                url = attrs.get(key)
                if url is None:
                    continue
                with self.subTest(url=url):
                    parts = urlsplit(url)
                    if parts.scheme or url.startswith("//"):
                        # ลิงก์ภายนอกมีได้เฉพาะลิงก์ https ธรรมดา ที่ไม่ให้หน้าปลายทางควบคุมหน้านี้
                        self.assertEqual(parts.scheme, "https")
                        self.assertEqual(tag, "a")
                        self.assertIn("noopener", (attrs.get("rel") or "").split())
                        continue
                    # GitHub Pages ของ repo อยู่ใต้ /claude-code/ ลิงก์ภายในต้องเป็นแบบ relative
                    self.assertFalse(url.startswith(("/", "\\")), url)
                    self.assertNotIn("..", url)
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, parts.path)), url)

    def test_content_security_policy(self):
        policies = [
            attrs.get("content") or "" for tag, attrs in self.tags
            if tag == "meta" and (attrs.get("http-equiv") or "").lower() == "content-security-policy"
        ]
        self.assertEqual(len(policies), 1, "ต้องมี CSP ใน <meta> (GitHub Pages ตั้ง header เองไม่ได้)")
        policy = policies[0]
        self.assertIn("default-src 'none'", policy)
        self.assertNotIn("script-src", policy)  # หน้าหลักไม่มีสคริปต์เลย
        self.assertNotIn("unsafe", policy)
        self.assertIn("base-uri 'none'", policy)
        self.assertIn(("meta", {"name": "referrer", "content": "no-referrer"}), self.tags)

    def test_no_scripts_or_inline_code(self):
        for tag, attrs in self.tags:
            with self.subTest(tag=tag):
                self.assertNotIn(tag, ("script", "style", "iframe", "frame", "object", "embed", "form", "base"))
                self.assertNotIn("style", attrs)
                self.assertEqual([name for name in attrs if name.startswith("on")], [], "ห้ามมี event handler inline")

    def test_apps_link_back_to_home_page(self):
        folders = app_folders()
        self.assertLessEqual(NO_HOME_LINK, set(folders), "ลบชื่อโฟลเดอร์ที่ไม่มีแล้วออกจาก NO_HOME_LINK")
        for name in folders:
            page = os.path.join(ROOT, name, "index.html")
            if name in NO_HOME_LINK or not os.path.isfile(page):  # ไม่มี index.html: เทสต์ด้านบนแจ้งแล้ว
                continue
            with self.subTest(folder=name):
                hrefs = [attrs.get("href") for tag, attrs in parse_tags(page) if tag == "a"]
                self.assertIn("../index.html", hrefs, "หน้าแรกของ %s/ ต้องมีลิงก์กลับหน้าหลัก" % name)

    def test_readme_lists_every_folder(self):
        readme = read("README.md")
        for name in app_folders():
            self.assertIn("[`%s/`](%s/)" % (name, name), readme, "ให้เพิ่ม %s/ ในตารางของ README.md" % name)

    def test_no_hidden_characters(self):
        # อักขระล่องหน อักขระกลับทิศข้อความ หรืออักขระที่ไม่ใช่ตัวอักษร ทำให้โค้ดที่เห็นไม่ตรงกับที่ทำงานจริง
        # (Trojan Source) ทุกไฟล์ซอร์สใน repo ต้องเขียนอักขระพวกนี้เป็น \uXXXX แทน (ยกเว้นไลบรารีใน vendor/)
        checked = 0
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")) and d != "vendor")
            for name in files:
                if not name.endswith(SOURCE_EXTENSIONS) and name not in (".gitignore",):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                checked += 1
                hidden = sorted({
                    "U+%04X" % ord(ch) for ch in text
                    if unicodedata.category(ch) in ("Cf", "Zl", "Zp", "Co", "Cs")
                    or (unicodedata.category(ch) == "Cc" and ch not in "\n\t\r")
                    or 0xFDD0 <= ord(ch) <= 0xFDEF or (ord(ch) & 0xFFFE) == 0xFFFE  # noncharacter
                })
                with self.subTest(file=os.path.relpath(path, ROOT)):
                    self.assertEqual(hidden, [])
        self.assertGreater(checked, 30)

if __name__ == "__main__":
    unittest.main()
