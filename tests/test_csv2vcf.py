import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv2vcf  # noqa: E402


def convert(csv_text, delimiter=None, **options):
    warnings = []
    cards = csv2vcf.iter_vcards(
        csv_text,
        delimiter=delimiter,
        options=csv2vcf.Options(**options),
        warn=lambda line, msg: warnings.append((line, msg)),
    )
    return "".join(cards), warnings


def unfold(vcf):
    return vcf.replace("\r\n ", "")


def props(vcf):
    return [line for line in unfold(vcf).split("\r\n") if line]


KNOWN_PROPERTIES = {
    "BEGIN", "VERSION", "N", "FN", "NICKNAME", "ORG", "TITLE", "TEL", "EMAIL",
    "ADR", "URL", "BDAY", "NOTE", "END",
}


def assert_well_formed(test, vcf):
    """ทุกบรรทัดตรรกะเป็น property ที่รู้จัก, BEGIN/END จับคู่กันครบ และขึ้นบรรทัดด้วย CRLF เท่านั้น"""
    test.assertNotIn("\n", vcf.replace("\r\n", ""))
    test.assertTrue(vcf.endswith("\r\n"))
    depth = 0
    for line in props(vcf):
        name = line.split(":", 1)[0].split(";", 1)[0]
        test.assertIn(name, KNOWN_PROPERTIES, line)
        if line == "BEGIN:VCARD":
            test.assertEqual(depth, 0)
            depth = 1
        elif line == "END:VCARD":
            test.assertEqual(depth, 1)
            depth = 0
    test.assertEqual(depth, 0)
    for physical in vcf.encode("utf-8").split(b"\r\n"):
        test.assertLessEqual(len(physical), 75)
        physical.decode("utf-8")  # การ fold ไม่ตัดกลางอักขระ


class BasicConversionTest(unittest.TestCase):
    def test_thai_headers(self):
        vcf, warnings = convert(
            "ชื่อ,นามสกุล,เบอร์โทร,อีเมล\n"
            "สมชาย,ใจดี,081-234-5678,somchai@example.com\n"
        )
        self.assertEqual(warnings, [])
        self.assertEqual(
            props(vcf),
            [
                "BEGIN:VCARD",
                "VERSION:3.0",
                "N:ใจดี;สมชาย;;;",
                "FN:สมชาย ใจดี",
                "TEL:081-234-5678",
                "EMAIL;TYPE=INTERNET:somchai@example.com",
                "END:VCARD",
            ],
        )
        assert_well_formed(self, vcf)

    def test_full_name_only_fills_n(self):
        vcf, _ = convert("Name,Phone\nJohn Smith,555-1234\n")
        self.assertIn("N:;John Smith;;;", props(vcf))
        self.assertIn("FN:John Smith", props(vcf))

    def test_google_contacts_export(self):
        csv_text = (
            "Name,Given Name,Family Name,E-mail 1 - Type,E-mail 1 - Value,"
            "Phone 1 - Type,Phone 1 - Value,Phone 2 - Type,Phone 2 - Value,"
            "Address 1 - Type,Address 1 - Formatted,Address 1 - Street,Address 1 - City,"
            "Address 1 - Postal Code,Address 1 - Country,Organization 1 - Name,Organization 1 - Title\n"
            "Jane Doe,Jane,Doe,* Work,jane@work.example ::: jane@home.example,"
            "* Mobile,081-111-1111 ::: 081-222-2222,Work Fax,02-333-3333,"
            "Home,\"1 Main St\nSpringfield\",1 Main St,Springfield,12345,US,Acme,Engineer\n"
        )
        vcf, warnings = convert(csv_text)
        self.assertEqual(warnings, [])
        lines = props(vcf)
        self.assertIn("FN:Jane Doe", lines)
        self.assertIn("N:Doe;Jane;;;", lines)
        self.assertIn("EMAIL;TYPE=INTERNET,WORK,PREF:jane@work.example", lines)
        self.assertIn("EMAIL;TYPE=INTERNET,WORK,PREF:jane@home.example", lines)
        self.assertIn("TEL;TYPE=CELL,PREF:081-111-1111", lines)
        self.assertIn("TEL;TYPE=CELL,PREF:081-222-2222", lines)
        self.assertIn("TEL;TYPE=WORK,FAX:02-333-3333", lines)
        self.assertIn("ADR;TYPE=HOME:;;1 Main St;Springfield;;12345;US", lines)
        self.assertIn("ORG:Acme", lines)
        self.assertIn("TITLE:Engineer", lines)
        assert_well_formed(self, vcf)

    def test_outlook_export(self):
        csv_text = (
            "First Name,Last Name,Company,Job Title,Department,Business Phone,Home Phone,"
            "Mobile Phone,Business Fax,E-mail Address,E-mail 2 Address,Home Street,"
            "Home Street 2,Home City,Home Postal Code,Home Country/Region,Web Page\n"
            "Bob,Builder,BuildCo,Foreman,Ops,02-000-0001,02-000-0002,081-000-0003,"
            "02-000-0004,bob@build.example,bob2@build.example,5 Oak Rd,Apt 2,Leeds,LS1,UK,"
            "build.example\n"
        )
        vcf, warnings = convert(csv_text)
        self.assertEqual(warnings, [])
        lines = props(vcf)
        self.assertIn("ORG:BuildCo;Ops", lines)
        self.assertIn("TITLE:Foreman", lines)
        self.assertIn("TEL;TYPE=WORK:02-000-0001", lines)
        self.assertIn("TEL;TYPE=HOME:02-000-0002", lines)
        self.assertIn("TEL;TYPE=CELL:081-000-0003", lines)
        self.assertIn("TEL;TYPE=WORK,FAX:02-000-0004", lines)
        self.assertIn("EMAIL;TYPE=INTERNET:bob2@build.example", lines)
        self.assertIn("ADR;TYPE=HOME:;;5 Oak Rd\\, Apt 2;Leeds;;LS1;UK", lines)
        self.assertIn("URL:https://build.example", lines)

    def test_thai_address_parts(self):
        csv_text = (
            "ชื่อ,ที่อยู่,ตำบล/แขวง,อำเภอ/เขต,จังหวัด,รหัสไปรษณีย์\n"
            "สมชาย,99/1 ถนนสุขุมวิท,คลองเตย,คลองเตย,กรุงเทพมหานคร,10110\n"
        )
        vcf, _ = convert(csv_text)
        self.assertIn("ADR:;;99/1 ถนนสุขุมวิท คลองเตย;คลองเตย;กรุงเทพมหานคร;10110;", props(vcf))

    def test_google_formatted_address_is_only_a_fallback(self):
        vcf, _ = convert(
            "Name,Address 1 - Formatted,Address 1 - Street,Address 1 - City\n"
            'A,"Springfield\nUS",,Springfield\n'
            'B,"1 Main St\nSpringfield",,\n'
        )
        self.assertIn("ADR:;;;Springfield;;;", props(vcf))
        self.assertIn("ADR:;;1 Main St\\nSpringfield;;;;", props(vcf))

    def test_one_cell_address_keeps_line_breaks(self):
        vcf, _ = convert('Name,Address\nA,"1 Main St\nSpringfield"\n')
        self.assertIn("ADR:;;1 Main St\\nSpringfield;;;;", props(vcf))

    def test_org_only_contact(self):
        vcf, _ = convert("Company,Phone\nร้านกาแฟ,053-123-456\n")
        lines = props(vcf)
        self.assertIn("N:;;;;", lines)
        self.assertIn("FN:ร้านกาแฟ", lines)

    def test_duplicate_headers_are_all_used(self):
        vcf, _ = convert("Name,Phone,Phone\nA,081-111-1111,082-222-2222\n")
        self.assertIn("TEL:081-111-1111", props(vcf))
        self.assertIn("TEL:082-222-2222", props(vcf))

    def test_empty_rows_are_skipped_silently(self):
        vcf, warnings = convert("\n\nName,Phone\n\n,\nA,0811111111\n  ,  \n")
        self.assertEqual(vcf.count("BEGIN:VCARD"), 1)
        self.assertEqual(warnings, [])

    def test_row_without_identity_is_skipped_with_warning(self):
        stats = csv2vcf.Stats()
        warnings = []
        cards = list(
            csv2vcf.iter_vcards(
                "Name,Notes,Extra\nA,,\n,only a note,x\n",
                warn=lambda line, msg: warnings.append(line),
                stats=stats,
            )
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual((stats.rows, stats.written, stats.skipped), (2, 1, 1))
        self.assertEqual(warnings, [3])
        self.assertEqual(stats.ignored_columns, ["Extra"])

    def test_no_known_columns(self):
        with self.assertRaises(csv2vcf.ConversionError):
            convert("foo,bar\n1,2\n")
        with self.assertRaises(csv2vcf.ConversionError):
            convert("")

    def test_short_and_long_rows(self):
        vcf, _ = convert("Name,Phone,Email\nA\nB,0811111111,b@example.com,extra\n")
        self.assertEqual(vcf.count("BEGIN:VCARD"), 2)


class EscapingAndInjectionTest(unittest.TestCase):
    def test_text_escaping(self):
        vcf, _ = convert('Name,Notes\n"Smith, Jr; a\\b","x,y;z"\n')
        lines = props(vcf)
        self.assertIn("FN:Smith\\, Jr\\; a\\\\b", lines)
        self.assertIn("NOTE:x\\,y\\;z", lines)

    def test_newline_injection_in_single_line_field(self):
        evil = "Evil\r\nEND:VCARD\r\nBEGIN:VCARD\r\nFN:Injected\r\nTEL:1900"
        vcf, _ = convert('Name,Phone\n"%s",0811111111\n' % evil)
        self.assertEqual(props(vcf).count("BEGIN:VCARD"), 1)
        self.assertEqual(props(vcf).count("END:VCARD"), 1)
        self.assertIn("FN:Evil END:VCARD BEGIN:VCARD FN:Injected TEL:1900", props(vcf))
        assert_well_formed(self, vcf)

    def test_newline_injection_in_multiline_fields(self):
        evil = "hi\rEND:VCARD\u2028BEGIN:VCARD\x85FN:x\x0bURL:javascript:alert(1)"
        vcf, _ = convert('Name,Notes,Address\nA,"%s","%s"\n' % (evil, evil))
        self.assertEqual(props(vcf).count("BEGIN:VCARD"), 1)
        self.assertEqual(props(vcf).count("END:VCARD"), 1)
        self.assertIn(
            "NOTE:hi\\nEND:VCARD\\nBEGIN:VCARD\\nFN:x\\nURL:javascript:alert(1)", props(vcf)
        )
        assert_well_formed(self, vcf)

    def test_parameter_injection_through_type_label(self):
        vcf, _ = convert(
            'Phone 1 - Type,Phone 1 - Value,E-mail 1 - Type,E-mail 1 - Value\n'
            '"X-EVIL=1;VALUE=uri:tel","0811111111","work:evil@x.com\r\nURL:http://x","a@b.co"\n'
        )
        self.assertIn("TEL:0811111111", props(vcf))
        self.assertIn("EMAIL;TYPE=INTERNET,WORK:a@b.co", props(vcf))
        assert_well_formed(self, vcf)

    def test_control_and_bidi_characters_removed(self):
        vcf, _ = convert('Name,Phone\n"\x1b[31mRed\u202eevil\u2066\x01\x7f\x9b\ufeff",081\u200b1111111\n')
        self.assertIn("FN:[31mRedevil", props(vcf))

    def test_long_lines_are_folded_on_character_boundaries(self):
        note = "ภาษาไทยยาวมาก " * 40
        vcf, _ = convert("Name,Notes\nA,%s\n" % note)
        assert_well_formed(self, vcf)
        self.assertIn("NOTE:" + note.strip(), props(vcf))

    def test_folding_never_splits_escapes(self):
        for pad in range(0, 6):
            value = "a" * pad + ",;\\" * 60
            line = csv2vcf.fold_line("NOTE:" + csv2vcf.escape_text(value))
            for physical in line.split("\r\n"):
                stripped = physical.rstrip("\\")
                self.assertEqual((len(physical) - len(stripped)) % 2, 0, physical)
            self.assertEqual(line.replace("\r\n ", ""), "NOTE:" + csv2vcf.escape_text(value))

    def test_random_hostile_input_always_gives_well_formed_output(self):
        import csv
        import random

        pieces = list("aZ09 ,;:\\\"'<>@.+-()/|*#\t\r\n\x1b\x7f\x85\u2028\u202eกำ่๑") + [
            "BEGIN:VCARD", "END:VCARD", "javascript:", "http://", ":::", "ต่อ",
        ]
        headers = [
            "Name", "First Name", "Phone", "Mobile", "Email", "Phone 1 - Type", "Phone 1 - Value",
            "E-mail 1 - Type", "E-mail 1 - Value", "Address", "Home City", "Address 1 - Formatted",
            "Website", "Birthday", "Notes", "Company", "Department", "ชื่อ", "ตำบล",
        ]
        for seed in range(40):
            rng = random.Random(seed)
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(headers)
            for _ in range(10):
                writer.writerow(
                    ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 80))) for _ in headers]
                )
            vcf, _ = convert(out.getvalue(), country_code=rng.choice([None, "66"]))
            if vcf:
                assert_well_formed(self, vcf)

    def test_terminal_escape_sequences_in_warnings_are_neutralised(self):
        _, warnings = convert("Name,Email\nA,\x1b]0;pwned\x07bad\x1b[2J\n")
        self.assertTrue(warnings)
        for _line, message in warnings:
            self.assertNotIn("\x1b", message)
            self.assertNotIn("\x07", message)
        self.assertEqual(csv2vcf.show("\x1b[2J\u202e"), '"\\x1b[2J\\u202e"')


class FieldNormalisationTest(unittest.TestCase):
    def test_phone_normalisation(self):
        cases = {
            "๐๘๑-๒๓๔-๕๖๗๘": "081-234-5678",
            "０８１２３４５６７８": "0812345678",
            "02-123-4567 ต่อ 12": "02-123-4567,12",
            "02 123 4567 ext. 9": "02 123 4567,9",
            "+66 81+234": "+66 81234",
            "(02) 123-4567": "(02) 123-4567",
        }
        for raw, expected in cases.items():
            self.assertEqual(csv2vcf.normalize_phone(raw)[0], expected, raw)

    def test_invalid_phones(self):
        for raw in ("12", "abc", "8.12345678E+08", "1" * 41, "---"):
            phone, warning = csv2vcf.normalize_phone(raw)
            self.assertIsNone(phone, raw)
            self.assertTrue(warning, raw)
        self.assertEqual(csv2vcf.normalize_phone("  "), (None, None))

    def test_country_code(self):
        self.assertEqual(csv2vcf.normalize_phone("081-234-5678", "66")[0], "+66 81-234-5678")
        self.assertEqual(csv2vcf.normalize_phone("+1 555 0100", "66")[0], "+1 555 0100")
        self.assertEqual(csv2vcf.normalize_phone("001 555 0100", "66")[0], "001 555 0100")

    def test_multiple_phones_in_one_cell_and_dedupe(self):
        vcf, warnings = convert('Name,Phone,Mobile\nA,"081-111-1111, 0822222222 / 12",0811111111\n')
        tels = [line for line in props(vcf) if line.startswith("TEL")]
        self.assertEqual(tels, ["TEL:081-111-1111", "TEL:0822222222"])
        self.assertEqual(len(warnings), 1)  # "12" มีตัวเลขน้อยเกินไป

    def test_emails(self):
        vcf, warnings = convert(
            'Name,Email\nA,"a@example.com; mailto:b@example.co.th, not-an-email, a@EXAMPLE.com"\n'
        )
        emails = [line for line in props(vcf) if line.startswith("EMAIL")]
        self.assertEqual(
            emails,
            ["EMAIL;TYPE=INTERNET:a@example.com", "EMAIL;TYPE=INTERNET:b@example.co.th"],
        )
        self.assertEqual(len(warnings), 1)
        vcf, _ = convert('Name,Email\nA,"Somchai <s@example.com>"\n')
        self.assertIn("EMAIL;TYPE=INTERNET:s@example.com", props(vcf))
        self.assertEqual(csv2vcf.normalize_email("ผู้ใช้@ตัวอย่าง.ไทย"), "ผู้ใช้@ตัวอย่าง.ไทย")
        for bad in ("a@b", "a b@c.com", 'a"@b.com', "a@b..com", "@b.com", "a@b.com<x>"):
            self.assertIsNone(csv2vcf.normalize_email(bad), bad)

    def test_mixed_plain_and_named_emails(self):
        self.assertEqual(
            csv2vcf.split_emails('Somchai <s@example.com>, other@example.com ::: x@y.co'),
            ["s@example.com", "other@example.com", "x@y.co"],
        )

    def test_email_patterns_are_linear(self):
        # pattern "<...@...>" แบบเก่าใช้เวลาหลายนาทีกับเซลล์ขนาด 100,000 อักขระ
        import time

        start = time.perf_counter()
        csv2vcf.normalize_email("a@" + "a." * 120 + "!")
        csv2vcf.normalize_email("a" * 250 + "@" + "b" * 3)
        csv2vcf.split_emails("<" + "@" * 100000)
        csv2vcf.split_emails("<a" + "@a" * 50000)
        csv2vcf.normalize_phone(" x" * 50000)
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_urls(self):
        self.assertEqual(csv2vcf.normalize_url("example.com"), "https://example.com")
        self.assertEqual(csv2vcf.normalize_url("www.ex.com:8080/a"), "https://www.ex.com:8080/a")
        self.assertEqual(csv2vcf.normalize_url("http://ok.test/a?b=1"), "http://ok.test/a?b=1")
        for bad in (
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "data:text/html,<b>",
            "file:///etc/passwd",
            "vbscript:x",
            "http:evil",
            "https://ex.com/<script>",
            "https://ex.com/a b",
            "https:\\\\evil.com",
        ):
            self.assertIsNone(csv2vcf.normalize_url(bad), bad)

    def test_birthdays(self):
        self.assertEqual(csv2vcf.normalize_birthday("1990-05-12"), "1990-05-12")
        self.assertEqual(csv2vcf.normalize_birthday("1990-05-12 00:00:00"), "1990-05-12")
        self.assertEqual(csv2vcf.normalize_birthday("19900512"), "1990-05-12")
        self.assertEqual(csv2vcf.normalize_birthday("12/05/2533"), "1990-05-12")
        self.assertEqual(csv2vcf.normalize_birthday("๑๒/๐๕/๒๕๓๓"), "1990-05-12")
        self.assertEqual(csv2vcf.normalize_birthday("05/12/1990", "mdy"), "1990-05-12")
        for bad in ("31/02/1990", "1990-13-01", "next tuesday", "12/05/90"):
            self.assertIsNone(csv2vcf.normalize_birthday(bad), bad)
        vcf, warnings = convert("Name,Birthday\nA,31/02/1990\n")
        self.assertNotIn("BDAY", vcf)
        self.assertEqual(len(warnings), 1)


class InputHandlingTest(unittest.TestCase):
    def test_delimiter_detection(self):
        for text in ("Name;Phone\nA;0811111111\n", "Name\tPhone\nA\t0811111111\n", "sep=;\nName;Phone\nA;0811111111\n"):
            vcf, _ = convert(text)
            self.assertIn("TEL:0811111111", props(vcf), repr(text))

    def test_sep_hint(self):
        vcf, _ = convert("\ufeffsep=;\nName;Phone\nA;0811111111\n")
        self.assertIn("TEL:0811111111", props(vcf))
        with self.assertRaises(csv2vcf.ConversionError):
            convert('sep="\nName,Phone\nA,0811111111\n')  # ไม่ทำตาม hint ที่ไม่ถูกต้อง

    def test_lone_surrogates_are_dropped(self):
        vcf, _ = convert("Name,Phone\nA\ud800B,0811111111\n")
        self.assertIn("FN:AB", props(vcf))

    def test_explicit_delimiter(self):
        vcf, _ = convert("Name|Phone\nA|0811111111\n", delimiter="|")
        self.assertIn("TEL:0811111111", props(vcf))

    def test_decoding(self):
        text = "ชื่อ,เบอร์โทร\nสมชาย,0811111111\n"
        for data, expected in (
            (text.encode("utf-8"), "utf-8"),
            (b"\xef\xbb\xbf" + text.encode("utf-8"), "utf-8-sig"),
            (text.encode("utf-16"), "utf-16"),
            (text.encode("cp874"), "cp874"),
        ):
            decoded, used = csv2vcf.decode_csv_bytes(data)
            self.assertEqual(decoded, text)
            self.assertEqual(used, expected)
        with self.assertRaises(csv2vcf.ConversionError):
            csv2vcf.decode_csv_bytes(b"a", "no-such-encoding")
        with self.assertRaises(csv2vcf.ConversionError):
            csv2vcf.decode_csv_bytes(b"a", "rot13")
        with self.assertRaises(csv2vcf.ConversionError):
            csv2vcf.decode_csv_bytes(b"\xff\xfe\xfd", "utf-8")

    def test_bom_in_header_with_explicit_encoding(self):
        text, _ = csv2vcf.decode_csv_bytes(b"\xef\xbb\xbfName,Phone\nA,0811111111\n", "utf-8")
        vcf, _ = convert(text)
        self.assertIn("FN:A", props(vcf))

    def test_nul_bytes_are_rejected(self):
        with self.assertRaises(csv2vcf.ConversionError):
            convert("Name,Phone\nA,081\x00\n")

    def test_malformed_csv_is_rejected(self):
        with self.assertRaises(csv2vcf.ConversionError):
            convert('Name,Phone\n"Bob,0811111111\nAlice,0822222222\n')
        with self.assertRaises(csv2vcf.ConversionError):
            convert('Name,Notes\nA,"' + "x" * 200000 + '"\n')


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.csv_path = os.path.join(self.dir, "contacts.csv")
        with open(self.csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write("Name,Phone\r\nสมชาย,081-111-1111\r\nB,0822222222\r\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = csv2vcf.main(list(argv))
        return code, err.getvalue()

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_default_output_path(self):
        code, err = self.run_main(self.csv_path)
        self.assertEqual(code, 0, err)
        data = self.read(os.path.join(self.dir, "contacts.vcf"))
        self.assertEqual(data.count(b"BEGIN:VCARD"), 2)
        self.assertIn("FN:สมชาย".encode("utf-8"), data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(os.path.join(self.dir, "contacts.vcf")).st_mode)
            self.assertEqual(mode, 0o600)
        self.assertEqual(sorted(os.listdir(self.dir)), ["contacts.csv", "contacts.vcf"])

    def test_refuses_to_overwrite_without_force(self):
        out = os.path.join(self.dir, "out.vcf")
        with open(out, "wb") as fh:
            fh.write(b"keep me")
        code, err = self.run_main(self.csv_path, "-o", out)
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertEqual(self.read(out), b"keep me")
        code, _ = self.run_main(self.csv_path, "-o", out, "--force")
        self.assertEqual(code, 0)
        self.assertTrue(self.read(out).startswith(b"BEGIN:VCARD"))

    def test_refuses_to_overwrite_input(self):
        original = self.read(self.csv_path)
        code, _ = self.run_main(self.csv_path, "-o", self.csv_path, "--force")
        self.assertEqual(code, 1)
        self.assertEqual(self.read(self.csv_path), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks not supported")
    def test_refuses_to_overwrite_input_through_symlink(self):
        link = os.path.join(self.dir, "link.vcf")
        try:
            os.symlink(self.csv_path, link)
        except OSError:
            self.skipTest("cannot create symlink")
        original = self.read(self.csv_path)
        code, _ = self.run_main(self.csv_path, "-o", link, "--force")
        self.assertEqual(code, 1)
        self.assertEqual(self.read(self.csv_path), original)

    def test_output_is_a_directory(self):
        code, _ = self.run_main(self.csv_path, "-o", self.dir, "--force")
        self.assertEqual(code, 1)

    def test_no_contacts_leaves_no_files(self):
        with open(self.csv_path, "w", encoding="utf-8") as fh:
            fh.write("Name,Phone\n,\n")
        code, _ = self.run_main(self.csv_path)
        self.assertEqual(code, 1)
        self.assertEqual(os.listdir(self.dir), ["contacts.csv"])

    def test_size_limit(self):
        with open(self.csv_path, "w", encoding="utf-8") as fh:
            fh.write("Name,Notes\n" + ("A,x\n" * 300000))
        code, err = self.run_main(self.csv_path, "--max-size", "1")
        self.assertEqual(code, 1)
        self.assertIn("--max-size", err)

    def test_missing_output_folder(self):
        code, err = self.run_main(self.csv_path, "-o", os.path.join(self.dir, "no", "out.vcf"))
        self.assertEqual(code, 1)
        self.assertIn("out.vcf", err)

    def test_warnings_are_capped(self):
        with open(self.csv_path, "w", encoding="utf-8") as fh:
            fh.write("Name,Email\n" + "A,bad\n" * 150)
        code, err = self.run_main(self.csv_path)
        self.assertEqual(code, 0)
        self.assertEqual(err.count("bad"), csv2vcf.MAX_WARNINGS_SHOWN)
        self.assertIn("50", err)

    def test_missing_input(self):
        code, err = self.run_main(os.path.join(self.dir, "nope.csv"))
        self.assertEqual(code, 1)
        self.assertIn("nope.csv", err)

    def test_stdout_output(self):
        buffer = io.BytesIO()
        fake_stdout = io.TextIOWrapper(buffer, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(fake_stdout), contextlib.redirect_stderr(err):
            code = csv2vcf.main([self.csv_path, "-o", "-"])
        fake_stdout.flush()
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(buffer.getvalue().count(b"BEGIN:VCARD"), 2)

    def test_warnings_do_not_leak_terminal_escapes(self):
        with open(self.csv_path, "w", encoding="utf-8") as fh:
            fh.write("Name,Email,\x1b[31mCol\n\x1b]0;x\x07A,bad\x1b[2J,\n")
        code, err = self.run_main(self.csv_path)
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", err)
        self.assertNotIn("\x07", err)

    def test_bad_arguments(self):
        for argv in (
            [self.csv_path, "--country-code", "abc"],
            [self.csv_path, "--max-size", "0"],
            [self.csv_path, "--max-size", "99999999999999999999"],
            [self.csv_path, "--delimiter", '"'],
        ):
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    csv2vcf.main(argv)


if __name__ == "__main__":
    unittest.main()
