#!/usr/bin/env python3
"""csv2vcf - แปลงไฟล์รายชื่อผู้ติดต่อ .csv เป็นไฟล์ vCard (.vcf)

Converts a contacts CSV (Google Contacts export, Outlook export, or a
hand-made sheet with English or Thai column names) into a vCard 3.0 file
that Android, iOS, Google Contacts and Outlook can import.

Only the Python standard library is used.

    python3 csv2vcf.py contacts.csv                      # -> contacts.vcf
    python3 csv2vcf.py contacts.csv -o out.vcf --country-code 66
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import csv
import datetime
import io
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

__version__ = "1.0.0"

DEFAULT_MAX_MB = 50
MAX_MAX_MB = 4096
MAX_WARNINGS_SHOWN = 100
PATH_SHOW_LIMIT = 1000  # file paths in messages are shown (sanitised) in full
FOLD_LIMIT = 75  # octets per physical line, excluding CRLF (RFC 2425 5.8.1)

WarnFn = Callable[[int, str], None]


class ConversionError(Exception):
    """A problem that stops the conversion (bad input, unwritable output...)."""


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

_NEWLINE_RE = re.compile("\r\n|[\r\n\x0b\x0c\x85\u2028\u2029]")
# C0/C1 control characters (except tab/newline, handled separately), lone
# surrogates (not encodable as UTF-8), the BOM, and bidi embedding/override/isolate controls. The latter can make a name
# display differently from what it really contains ("Trojan Source" spoofing).
_STRIP_RE = re.compile("[\x00-\x08\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufeff\u202a-\u202e\u2066-\u2069]")


def clean_text(value: str, multiline: bool = False) -> str:
    """Normalise a CSV cell: NFC, no control characters, tidy whitespace.

    Line breaks survive only when *multiline* is true; otherwise every run of
    whitespace (including line breaks) collapses to a single space.
    """
    value = unicodedata.normalize("NFC", value)
    value = _STRIP_RE.sub("", _NEWLINE_RE.sub("\n", value))
    if multiline:
        return "\n".join(" ".join(line.split()) for line in value.split("\n")).strip("\n")
    return " ".join(value.split())


def escape_text(value: str) -> str:
    """Escape a TEXT value (RFC 2426 section 4, RFC 6350 section 3.4)."""
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return _NEWLINE_RE.sub(lambda _m: "\\n", value)


_FOLD_TOKEN_RE = re.compile(r"\\.|.", re.DOTALL)


def fold_line(line: str, limit: int = FOLD_LIMIT) -> str:
    """Fold a content line so that no physical line exceeds *limit* octets.

    Breaks only between whole characters and never inside a backslash escape,
    so multi-byte UTF-8 sequences (e.g. Thai) stay intact - several importers
    cannot rejoin a character that was split across lines.
    """
    if len(line.encode("utf-8")) <= limit:
        return line
    pieces: List[str] = []
    current: List[str] = []
    size = 0
    room = limit
    for token in _FOLD_TOKEN_RE.findall(line):
        n = len(token.encode("utf-8"))
        if current and size + n > room:
            pieces.append("".join(current))
            current, size = [], 0
            room = limit - 1  # continuation lines start with one space
        current.append(token)
        size += n
    pieces.append("".join(current))
    return "\r\n ".join(pieces)


def show(value: str, limit: int = 60) -> str:
    """Quote an untrusted value for a terminal message.

    Control and format characters (ANSI escape sequences, bidi overrides...)
    are shown as escapes so a crafted CSV cannot manipulate the terminal.
    """
    if len(value) > limit:
        value = value[:limit] + "..."
    out = []
    for ch in value:
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp"):
            out.append(ch.encode("unicode_escape").decode("ascii"))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _ascii_digits(value: str) -> str:
    """NFKC-normalise and turn any decimal digit (Thai ๐-๙, full-width...) into ASCII."""
    value = unicodedata.normalize("NFKC", value)
    return "".join(
        str(unicodedata.digit(ch)) if unicodedata.category(ch) == "Nd" else ch for ch in value
    )


# --------------------------------------------------------------------------
# Field normalisation
# --------------------------------------------------------------------------

_PHONE_SPLIT_RE = re.compile(r":::|[;,/|\n]")
_PHONE_EXT_RE = re.compile(r"\s*(?:ต่อ|extension|ext\.?|x)\s*(?=\d)", re.IGNORECASE)
_EXCEL_SCI_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?[eE][+-]?\d+$")
_PHONE_ALLOWED = frozenset("0123456789+-(). *#,")
_MAX_PHONE_LEN = 40


def normalize_phone(
    raw: str, country_code: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(phone, warning)``; *phone* is None when the value is unusable."""
    value = clean_text(_ascii_digits(raw))
    if not value:
        return None, None
    if _EXCEL_SCI_RE.match(value):
        return None, (
            f"เบอร์โทร {show(raw)} ถูก Excel แปลงเป็นเลขวิทยาศาสตร์ "
            "(ให้ตั้งคอลัมน์เป็น Text แล้ว export ใหม่)"
        )
    value = _PHONE_EXT_RE.sub(",", value)  # "ต่อ 12" / "ext 12" -> dial pause
    kept = [ch for ch in value if ch in _PHONE_ALLOWED]
    dropped = len(kept) != len(value)
    phone = " ".join("".join(kept).split())
    # "+" is only meaningful as the very first character.
    phone = phone[:1] + phone[1:].replace("+", "")
    phone = phone.strip(" -.,")
    digits = sum(ch.isdigit() for ch in phone)
    if digits < 3 or len(phone) > _MAX_PHONE_LEN:
        return None, f"ข้ามเบอร์โทรที่ไม่ถูกต้อง {show(raw)}"
    if country_code and phone.startswith("0") and not phone.startswith("00"):
        phone = f"+{country_code} " + phone[1:].lstrip(" -.")
    warning = f"ตัดอักขระที่ไม่ใช่เบอร์โทรออกจาก {show(raw)}" if dropped else None
    return phone, warning


_EMAIL_SPLIT_RE = re.compile(r":::|[;,]")
# Neither side may contain "@": otherwise "<@@@@..." backtracks quadratically.
_EMAIL_BRACKET_RE = re.compile(r"<([^<>\s@]+@[^<>\s@]+)>")
# Deliberately permissive (allows internationalised addresses) but excludes
# whitespace and every character that is special in vCard or HTML. Domain
# labels exclude "." so the pattern cannot backtrack catastrophically.
_EMAIL_RE = re.compile(r'^[^\s@<>()\[\]\\,;:"]+@[^\s@<>()\[\]\\,;:".]+(?:\.[^\s@<>()\[\]\\,;:".]+)+$')
_MAX_EMAIL_LEN = 254


def split_emails(raw: str) -> List[str]:
    """Split a cell holding one or more addresses ("a@x.com; Name <b@y.com>")."""
    parts: List[str] = []
    for segment in _EMAIL_SPLIT_RE.split(clean_text(raw)):
        parts.extend(_EMAIL_BRACKET_RE.findall(segment) or segment.split())
    return parts


def normalize_email(raw: str) -> Optional[str]:
    value = raw.strip()
    if value[:7].lower() == "mailto:":
        value = value[7:]
    if len(value) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(value):
        return None
    return value


_URL_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(?!\d)")
_URL_FORBIDDEN = frozenset('<>"\\`{}|^')
_MAX_URL_LEN = 2048


def normalize_url(raw: str) -> Optional[str]:
    """Return an http(s) URL, or None for anything else (javascript:, file:...)."""
    value = clean_text(raw)
    if (
        not value
        or len(value) > _MAX_URL_LEN
        or any(ch.isspace() or ch in _URL_FORBIDDEN for ch in value)
    ):
        return None
    match = _URL_SCHEME_RE.match(value)
    if match:
        if match.group(1).lower() not in ("http", "https") or "://" not in value:
            return None
        return value
    return "https://" + value.lstrip("/")


_DATE_YMD_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")
_DATE_COMPACT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATE_XY_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:\s.*)?$")


def normalize_birthday(raw: str, date_order: str = "dmy") -> Optional[str]:
    """Parse a birthday into ``YYYY-MM-DD``.

    Accepts ISO dates and DD/MM/YYYY (or MM/DD/YYYY with ``date_order="mdy"``).
    Buddhist-era years (> 2400, common in Thailand) are converted to CE.
    """
    value = clean_text(_ascii_digits(raw))
    match = _DATE_YMD_RE.match(value) or _DATE_COMPACT_RE.match(value)
    if match:
        year, month, day = (int(g) for g in match.groups())
    else:
        match = _DATE_XY_RE.match(value)
        if not match:
            return None
        first, second, year = (int(g) for g in match.groups())
        day, month = (second, first) if date_order == "mdy" else (first, second)
    if year > 2400:
        year -= 543
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Column recognition
# --------------------------------------------------------------------------


def normalize_header(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace("\ufeff", "")
    name = name.strip().strip("\"'").strip().lower()
    name = re.sub(r"[\s_]+", " ", name).rstrip(".:").strip()
    return name.replace("e-mail", "email")


@dataclass(frozen=True)
class Column:
    kind: str  # name | org | tel | email | url | adr | bday | note
    attr: str = "value"
    group: Tuple = ()
    types: Tuple[str, ...] = ()


_COLUMN_ALIASES: List[Tuple[str, str, Tuple[str, ...], Sequence[str]]] = [
    ("name", "full_name", (), [
        "name", "full name", "fullname", "display name", "formatted name", "contact name",
        "ชื่อ-นามสกุล", "ชื่อ - นามสกุล", "ชื่อ นามสกุล", "ชื่อและนามสกุล", "ชื่อเต็ม",
        "ชื่อที่แสดง", "ชื่อผู้ติดต่อ",
    ]),
    ("name", "given", (), ["first name", "firstname", "given name", "givenname", "first", "ชื่อ", "ชื่อจริง"]),
    ("name", "family", (), ["last name", "lastname", "family name", "familyname", "surname", "last", "นามสกุล"]),
    ("name", "middle", (), ["middle name", "middlename", "additional name", "middle", "ชื่อกลาง"]),
    ("name", "prefix", (), ["name prefix", "prefix", "honorific prefix", "คำนำหน้า", "คำนำหน้าชื่อ"]),
    ("name", "suffix", (), ["name suffix", "suffix", "honorific suffix"]),
    ("name", "nickname", (), ["nickname", "nick name", "ชื่อเล่น"]),
    ("org", "org", (), [
        "organization", "organisation", "organization name", "company", "company name",
        "บริษัท", "องค์กร", "หน่วยงาน", "สังกัด",
    ]),
    ("org", "title", (), ["job title", "jobtitle", "organization title", "position", "ตำแหน่ง"]),
    ("org", "dept", (), ["department", "organization department", "แผนก", "ฝ่าย"]),
    ("tel", "value", (), [
        "phone", "phone number", "phone no", "telephone", "telephone number", "tel", "tel no",
        "other phone", "เบอร์", "เบอร์โทร", "เบอร์โทรศัพท์", "โทรศัพท์", "หมายเลขโทรศัพท์",
    ]),
    ("tel", "value", ("PREF",), ["primary phone"]),
    ("tel", "value", ("CELL",), [
        "mobile", "mobile phone", "mobile number", "mobile no", "cell", "cell phone", "cellphone",
        "มือถือ", "เบอร์มือถือ", "โทรศัพท์มือถือ", "เบอร์โทรศัพท์มือถือ",
    ]),
    ("tel", "value", ("HOME",), ["เบอร์บ้าน", "โทรศัพท์บ้าน"]),
    ("tel", "value", ("WORK",), ["company main phone", "เบอร์ที่ทำงาน", "โทรศัพท์ที่ทำงาน"]),
    ("tel", "value", ("FAX",), ["fax", "fax number", "แฟกซ์", "โทรสาร"]),
    ("tel", "value", ("PAGER",), ["pager"]),
    ("tel", "value", ("CAR",), ["car phone"]),
    ("email", "value", (), ["email", "email address", "mail", "อีเมล", "อีเมล์", "อีเมลล์"]),
    ("url", "value", (), [
        "website", "web site", "web page", "webpage", "personal web page", "url", "homepage",
        "เว็บไซต์",
    ]),
    ("bday", "value", (), ["birthday", "bday", "birth date", "birthdate", "date of birth", "dob", "วันเกิด"]),
    ("note", "value", (), ["note", "notes", "comment", "comments", "หมายเหตุ", "บันทึก"]),
    ("adr", "address", (), ["address", "full address", "mailing address", "postal address", "ที่อยู่"]),
    ("adr", "address", ("HOME",), ["ที่อยู่บ้าน"]),
    ("adr", "address", ("WORK",), ["ที่อยู่ที่ทำงาน"]),
    ("adr", "street", (), ["street", "street address", "address line 1", "บ้านเลขที่", "ถนน"]),
    ("adr", "extended", (), ["extended address", "address line 2"]),
    ("adr", "subdistrict", (), ["subdistrict", "sub-district", "ตำบล", "แขวง", "ตำบล/แขวง", "แขวง/ตำบล"]),
    ("adr", "city", (), ["city", "town", "district", "อำเภอ", "เขต", "อำเภอ/เขต", "เขต/อำเภอ"]),
    ("adr", "region", (), ["state", "province", "region", "state/province", "จังหวัด"]),
    ("adr", "postal", (), ["postal code", "postcode", "post code", "zip", "zip code", "zipcode", "รหัสไปรษณีย์"]),
    ("adr", "country", (), ["country", "country/region", "country region", "ประเทศ"]),
    ("adr", "pobox", (), ["po box", "p.o. box", "pobox"]),
]

_SIMPLE_COLUMNS: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    normalize_header(alias): (kind, attr, types)
    for kind, attr, types, aliases in _COLUMN_ALIASES
    for alias in aliases
}

# "Home Phone", "Business Fax", "Other E-mail", "Home Street" (Outlook style).
_TYPE_PREFIXES: Dict[str, Tuple[str, ...]] = {
    "home": ("HOME",), "personal": ("HOME",), "business": ("WORK",), "work": ("WORK",),
    "office": ("WORK",), "other": (),
}

# Google Contacts: "Phone 1 - Type", "E-mail 2 - Value", "Address 1 - City"...
_GOOGLE_RE = re.compile(r"^(phone|email|address|website|organization) ?(\d+) ?- ?(.+)$")
_GOOGLE_KIND = {"phone": "tel", "email": "email", "address": "adr", "website": "url", "organization": "org"}
_GOOGLE_ATTRS: Dict[str, Dict[str, str]] = {
    "phone": {"value": "value", "type": "type", "label": "type"},
    "email": {"value": "value", "type": "type", "label": "type"},
    "website": {"value": "value"},
    "address": {
        "formatted": "formatted", "street": "street", "city": "city", "po box": "pobox",
        "region": "region", "postal code": "postal", "country": "country",
        "extended address": "extended", "type": "type", "label": "type",
    },
    "organization": {"name": "org", "title": "title", "department": "dept"},
}


def _strip_numbers(name: str) -> str:
    return " ".join(word for word in name.split() if not word.isdigit())


def _make_column(kind: str, attr: str, types: Tuple[str, ...], index: int) -> Column:
    if kind in ("tel", "email", "url"):
        group: Tuple = (kind, "column", index)  # every column is its own entry
    elif kind == "adr":
        group = ("adr",) + types  # "Home Street" + "Home City" form one address
    else:
        group = ()
    return Column(kind, attr, group, types)


def classify_header(header: str, index: int) -> Optional[Column]:
    """Map a CSV header to the contact field it holds, or None if unknown."""
    name = normalize_header(header)
    if not name:
        return None
    match = _GOOGLE_RE.match(name)
    if match:
        section, number, sub = match.groups()
        attr = _GOOGLE_ATTRS[section].get(sub.strip())
        if attr is None:
            return None
        kind = _GOOGLE_KIND[section]
        if kind == "org":
            return Column("org", attr)
        return Column(kind, attr, group=(kind, "google", number))
    for candidate in dict.fromkeys((name, _strip_numbers(name))):
        hit = _SIMPLE_COLUMNS.get(candidate)
        if hit:
            return _make_column(*hit, index)
        word, _, rest = candidate.partition(" ")
        hit = _SIMPLE_COLUMNS.get(rest)
        if word in _TYPE_PREFIXES and hit and hit[0] in ("tel", "email", "adr"):
            kind, attr, types = hit
            return _make_column(kind, attr, _TYPE_PREFIXES[word] + types, index)
    return None


_LABEL_TYPES: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = [
    ("CELL", ("mobile", "cell", "iphone", "มือถือ"), ("tel",)),
    ("HOME", ("home", "personal", "บ้าน", "ส่วนตัว"), ("tel", "email", "adr")),
    ("WORK", ("work", "business", "office", "งาน"), ("tel", "email", "adr")),
    ("FAX", ("fax", "แฟกซ์", "โทรสาร"), ("tel",)),
    ("PAGER", ("pager",), ("tel",)),
]


def types_from_label(label: str, kind: str) -> Tuple[str, ...]:
    """Translate a free-form label ("* Mobile", "Work Fax") into allowlisted TYPEs.

    The label itself is never copied into the output, so it cannot inject
    parameters or properties.
    """
    text = clean_text(label).lower()
    types = [t for t, words, kinds in _LABEL_TYPES if kind in kinds and any(w in text for w in words)]
    if text.startswith("*"):  # Google marks the primary value with "* "
        types.append("PREF")
    return tuple(types)


# --------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------


@dataclass
class Address:
    types: Tuple[str, ...] = ()
    pobox: str = ""
    extended: str = ""
    street: str = ""
    city: str = ""
    region: str = ""
    postal: str = ""
    country: str = ""

    def components(self) -> Tuple[str, ...]:
        return (self.pobox, self.extended, self.street, self.city, self.region, self.postal, self.country)


@dataclass
class Contact:
    full_name: str = ""
    given: str = ""
    family: str = ""
    middle: str = ""
    prefix: str = ""
    suffix: str = ""
    nickname: str = ""
    org: str = ""
    dept: str = ""
    title: str = ""
    phones: List[Tuple[str, Tuple[str, ...]]] = field(default_factory=list)
    emails: List[Tuple[str, Tuple[str, ...]]] = field(default_factory=list)
    addresses: List[Address] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    birthday: str = ""
    note: str = ""

    def display_name(self) -> str:
        structured = " ".join(
            p for p in (self.prefix, self.given, self.middle, self.family, self.suffix) if p
        )
        return (
            self.full_name
            or structured
            or self.nickname
            or self.org
            or (self.emails[0][0] if self.emails else "")
            or (self.phones[0][0] if self.phones else "")
        )


@dataclass
class Options:
    country_code: Optional[str] = None  # e.g. "66": 081... -> +66 81...
    date_order: str = "dmy"  # how to read 01/02/2000: "dmy" or "mdy"


def _dedupe(types: Iterable[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(types))


def build_contact(
    row: Sequence[str], columns: Sequence[Tuple[int, Column]], options: Options, warn: WarnFn, line: int
) -> Optional[Contact]:
    """Turn one CSV row into a Contact, or None if it holds nothing usable."""
    contact = Contact()
    groups: Dict[Tuple, Tuple[Column, Dict[str, List[str]]]] = {}

    for index, column in columns:
        raw = row[index] if index < len(row) else ""
        if not raw.strip():
            continue
        if column.kind in ("name", "org"):
            if not getattr(contact, column.attr):
                setattr(contact, column.attr, clean_text(raw))
        elif column.kind == "bday":
            if not contact.birthday:
                birthday = normalize_birthday(raw, options.date_order)
                if birthday:
                    contact.birthday = birthday
                else:
                    warn(line, f"ข้ามวันเกิดที่อ่านไม่ออก {show(raw)} (ใช้รูปแบบ YYYY-MM-DD หรือ DD/MM/YYYY)")
        elif column.kind == "note":
            text = clean_text(raw, multiline=True)
            contact.note = f"{contact.note}\n{text}" if contact.note else text
        else:
            _, fields = groups.setdefault(column.group, (column, {}))
            fields.setdefault(column.attr, []).append(raw)

    seen_phones = set()
    seen_emails = set()
    for column, fields in groups.values():
        types = list(column.types)
        for label in fields.get("type", []):
            types.extend(types_from_label(label, column.kind))
        types_t = _dedupe(types)

        if column.kind == "tel":
            for raw in fields.get("value", []):
                for part in _PHONE_SPLIT_RE.split(raw):
                    phone, problem = normalize_phone(part, options.country_code)
                    if problem:
                        warn(line, problem)
                    key = phone and re.sub(r"[^\d+,]", "", phone)
                    if phone and key not in seen_phones:
                        seen_phones.add(key)
                        contact.phones.append((phone, types_t))
        elif column.kind == "email":
            for raw in fields.get("value", []):
                for part in split_emails(raw):
                    email = normalize_email(part)
                    if email is None:
                        warn(line, f"ข้ามอีเมลที่ไม่ถูกต้อง {show(part)}")
                    elif email.lower() not in seen_emails:
                        seen_emails.add(email.lower())
                        contact.emails.append((email, types_t))
        elif column.kind == "url":
            for raw in fields.get("value", []):
                for part in raw.split(":::"):
                    if not part.strip():
                        continue
                    url = normalize_url(part)
                    if url is None:
                        warn(line, f"ข้าม URL ที่ไม่ปลอดภัยหรือไม่ถูกต้อง {show(part)} (รองรับเฉพาะ http/https)")
                    elif url not in contact.urls:
                        contact.urls.append(url)
        elif column.kind == "adr":
            address = _build_address(fields, types_t)
            if address:
                contact.addresses.append(address)

    if not contact.display_name():
        warn(line, "ข้ามแถวนี้เพราะไม่มีชื่อ องค์กร เบอร์โทร หรืออีเมล")
        return None
    return contact


def _build_address(fields: Dict[str, List[str]], types: Tuple[str, ...]) -> Optional[Address]:
    def part(name: str, multiline: bool = False) -> str:
        values = (clean_text(v, multiline) for v in fields.get(name, []))
        return ", ".join(v for v in values if v)

    # A hand-made "Address"/"ที่อยู่" column is the street part when there is no
    # street column, even next to city/province columns.
    street = part("street", multiline=True) or part("address", multiline=True)
    subdistrict = part("subdistrict")
    if subdistrict:
        street = f"{street} {subdistrict}".strip()
    address = Address(
        types=tuple(t for t in types if t in ("HOME", "WORK", "PREF")),
        pobox=part("pobox"),
        extended=part("extended"),
        street=street,
        city=part("city"),
        region=part("region"),
        postal=part("postal"),
        country=part("country"),
    )
    if not any(address.components()):
        # Google's "Address N - Formatted" repeats the structured parts, so it
        # is only used when they are all empty.
        address.street = part("formatted", multiline=True)
    return address if any(address.components()) else None


# --------------------------------------------------------------------------
# vCard output
# --------------------------------------------------------------------------


def _content_line(name: str, value: str, types: Tuple[str, ...] = ()) -> str:
    head = name + (";TYPE=" + ",".join(types) if types else "")
    return fold_line(f"{head}:{value}")


def contact_to_vcard(contact: Contact) -> str:
    """Render a Contact as a vCard 3.0 entry with CRLF line endings."""
    name_parts = (contact.family, contact.given, contact.middle, contact.prefix, contact.suffix)
    if not any(name_parts) and contact.full_name:
        # Many phones build the displayed name from N, not FN.
        name_parts = ("", contact.full_name, "", "", "")

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        _content_line("N", ";".join(escape_text(p) for p in name_parts)),
        _content_line("FN", escape_text(contact.display_name())),
    ]
    if contact.nickname:
        lines.append(_content_line("NICKNAME", escape_text(contact.nickname)))
    if contact.org or contact.dept:
        org = escape_text(contact.org) + (";" + escape_text(contact.dept) if contact.dept else "")
        lines.append(_content_line("ORG", org))
    if contact.title:
        lines.append(_content_line("TITLE", escape_text(contact.title)))
    for phone, types in contact.phones:
        # Phone values only contain characters from _PHONE_ALLOWED.
        lines.append(_content_line("TEL", phone, types))
    for email, types in contact.emails:
        lines.append(_content_line("EMAIL", escape_text(email), _dedupe(("INTERNET",) + types)))
    for address in contact.addresses:
        value = ";".join(escape_text(p) for p in address.components())
        lines.append(_content_line("ADR", value, address.types))
    for url in contact.urls:
        # URL is a URI value (not TEXT); normalize_url rejects whitespace.
        lines.append(_content_line("URL", url))
    if contact.birthday:
        lines.append(_content_line("BDAY", contact.birthday))
    if contact.note:
        lines.append(_content_line("NOTE", escape_text(contact.note)))
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


# --------------------------------------------------------------------------
# CSV input
# --------------------------------------------------------------------------


def decode_csv_bytes(data: bytes, encoding: str = "auto") -> Tuple[str, str]:
    """Decode raw CSV bytes; returns ``(text, encoding_used)``.

    ``auto`` honours a UTF-8/UTF-16 BOM, then tries UTF-8, then Windows Thai
    (cp874), which is what Excel on Thai Windows writes by default.
    """
    try:
        if encoding != "auto":
            return data.decode(encoding), encoding
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig"), "utf-8-sig"
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16"), "utf-16"
        try:
            return data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            return data.decode("cp874"), "cp874"
    except LookupError as exc:
        raise ConversionError(f"ไม่รู้จัก encoding {show(encoding)}") from exc
    except UnicodeDecodeError as exc:
        raise ConversionError(
            f"ถอดรหัสไฟล์ด้วย {exc.encoding} ไม่ได้ (ตำแหน่งไบต์ {exc.start}) "
            "ลองระบุ --encoding เช่น utf-8, cp874, tis-620, utf-16"
        ) from exc


_DELIMITERS = (",", ";", "\t", "|")
_SEP_HINT_RE = re.compile(r"^sep=(.)\r?\n")


def detect_delimiter(text: str) -> str:
    """Pick the delimiter that appears most often in the header line (default ",")."""
    header = text.split("\n", 1)[0]
    counts = {d: header.count(d) for d in _DELIMITERS}
    best = max(counts, key=lambda d: counts[d])  # ties resolve to ","
    return best if counts[best] else ","


@dataclass
class Stats:
    rows: int = 0
    written: int = 0
    skipped: int = 0
    ignored_columns: List[str] = field(default_factory=list)


def iter_vcards(
    text: str,
    delimiter: Optional[str] = None,
    options: Optional[Options] = None,
    warn: Optional[WarnFn] = None,
    stats: Optional[Stats] = None,
) -> Iterator[str]:
    """Yield one vCard string per usable row of the CSV *text*."""
    options = options or Options()
    warn = warn or (lambda _line, _msg: None)
    stats = stats if stats is not None else Stats()

    if "\x00" in text:
        raise ConversionError(
            "ไฟล์มีอักขระ NUL อาจเป็นไฟล์ UTF-16 ที่ไม่มี BOM ลองระบุ --encoding utf-16-le"
        )
    if text.startswith("\ufeff"):
        text = text[1:]
    hint = _SEP_HINT_RE.match(text)  # Excel's "sep=;" first line
    if hint and hint.group(1) in _DELIMITERS:
        text = text[hint.end():]
        delimiter = delimiter or hint.group(1)
    delimiter = delimiter or detect_delimiter(text)

    # strict: an unclosed quote must fail loudly instead of silently merging
    # every following row into one contact.
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header: List[str] = []
        for header in reader:
            if any(cell.strip() for cell in header):
                break
        columns: List[Tuple[int, Column]] = []
        for index, name in enumerate(header):
            column = classify_header(name, index)
            if column:
                columns.append((index, column))
            elif name.strip():
                stats.ignored_columns.append(name)
        if not columns:
            raise ConversionError(
                "ไม่พบคอลัมน์ที่รู้จักในแถวหัวตาราง (เช่น Name, Phone, Email, ชื่อ, เบอร์โทร, อีเมล) "
                f"หัวตารางที่พบ: {', '.join(show(h, 30) for h in header[:10]) or '(ว่าง)'}"
            )
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            stats.rows += 1
            contact = build_contact(row, columns, options, warn, reader.line_num)
            if contact is None:
                stats.skipped += 1
                continue
            stats.written += 1
            yield contact_to_vcard(contact)
    except csv.Error as exc:
        raise ConversionError(f"อ่านไฟล์ CSV ไม่ได้ที่บรรทัด {reader.line_num}: {exc}") from exc


# --------------------------------------------------------------------------
# Files and command line
# --------------------------------------------------------------------------


def read_input(path: str, max_bytes: int) -> bytes:
    if path == "-":
        data = sys.stdin.buffer.read(max_bytes + 1)
    else:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ConversionError(f"ไฟล์ใหญ่เกิน {max_bytes // (1024 * 1024)} MB (ปรับได้ด้วย --max-size)")
    return data


def default_output_path(input_path: str) -> str:
    if input_path == "-":
        return "-"
    root, _ext = os.path.splitext(input_path)
    return root + ".vcf"


def _check_output_path(output: str, force: bool, input_path: Optional[str]) -> None:
    if os.path.isdir(output):
        raise ConversionError(f"{show(output, PATH_SHOW_LIMIT)} เป็นโฟลเดอร์ ไม่ใช่ไฟล์")
    if not os.path.isdir(os.path.dirname(os.path.abspath(output))):
        raise ConversionError(f"ไม่พบโฟลเดอร์ของไฟล์ผลลัพธ์ {show(output, PATH_SHOW_LIMIT)}")
    if not os.path.lexists(output):
        return
    if input_path and input_path != "-":
        try:
            same = os.path.samefile(output, input_path)
        except OSError:
            same = False
        if same:
            raise ConversionError("ไฟล์ผลลัพธ์ต้องไม่ใช่ไฟล์เดียวกับไฟล์ CSV ต้นฉบับ")
    if not force:
        raise ConversionError(f"มีไฟล์ {show(output, PATH_SHOW_LIMIT)} อยู่แล้ว (ใช้ --force เพื่อเขียนทับ)")


_NO_CONTACTS = "ไม่มีรายชื่อที่แปลงได้เลย จึงไม่สร้างไฟล์ผลลัพธ์"


def write_vcards(
    vcards: Iterable[str], output: str, force: bool = False, input_path: Optional[str] = None
) -> int:
    """Write the vCards to *output* ("-" = stdout); returns how many were written.

    A file is written to a private temporary file (mode 0600, contacts are
    personal data) and atomically renamed into place, so a failure never
    leaves a half-written .vcf behind or clobbers an existing file.
    """
    if output == "-":
        count = 0
        for card in vcards:
            sys.stdout.buffer.write(card.encode("utf-8"))
            count += 1
        sys.stdout.buffer.flush()
        if not count:
            raise ConversionError(_NO_CONTACTS)
        return count

    _check_output_path(output, force, input_path)
    directory = os.path.dirname(os.path.abspath(output))
    fd, tmp_path = tempfile.mkstemp(prefix=".csv2vcf-", suffix=".tmp", dir=directory)
    count = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            for card in vcards:
                fh.write(card.encode("utf-8"))
                count += 1
        if not count:
            raise ConversionError(_NO_CONTACTS)
        os.replace(tmp_path, output)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return count


def _delimiter_arg(value: str) -> str:
    value = {"tab": "\t", "\\t": "\t", "comma": ",", "semicolon": ";", "pipe": "|"}.get(value.lower(), value)
    if len(value) != 1 or value in "\"\r\n" or value.isalnum():
        raise argparse.ArgumentTypeError("ต้องเป็นอักขระเดียว เช่น , ; | หรือ tab")
    return value


def _country_code_arg(value: str) -> str:
    value = value.strip().lstrip("+")
    if not re.fullmatch(r"[1-9]\d{0,2}", value):
        raise argparse.ArgumentTypeError("ต้องเป็นตัวเลข 1-3 หลัก เช่น 66")
    return value


def _max_size_arg(value: str) -> int:
    try:
        size = int(value)
    except ValueError:
        size = 0
    if not 0 < size <= MAX_MAX_MB:
        raise argparse.ArgumentTypeError(f"ต้องเป็นจำนวนเต็ม 1-{MAX_MAX_MB} (หน่วย MB)")
    return size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv2vcf",
        description="แปลงไฟล์รายชื่อผู้ติดต่อ .csv เป็นไฟล์ vCard 3.0 (.vcf) "
        "สำหรับนำเข้า Android, iPhone, Google Contacts และ Outlook",
    )
    parser.add_argument("input", help="ไฟล์ CSV ต้นฉบับ (ใช้ - เพื่ออ่านจาก stdin)")
    parser.add_argument("-o", "--output", help="ไฟล์ .vcf ที่จะสร้าง (ค่าเริ่มต้น: ชื่อเดียวกับไฟล์ CSV, ใช้ - เพื่อเขียนออก stdout)")
    parser.add_argument("-e", "--encoding", default="auto", help="encoding ของไฟล์ CSV (ค่าเริ่มต้น: auto = UTF-8 แล้วลอง cp874)")
    parser.add_argument("-d", "--delimiter", type=_delimiter_arg, help="ตัวคั่นคอลัมน์ (ค่าเริ่มต้น: ตรวจจับอัตโนมัติ)")
    parser.add_argument("--country-code", type=_country_code_arg, help="แปลงเบอร์ที่ขึ้นต้นด้วย 0 เป็นรูปแบบสากล เช่น 66: 081... -> +66 81...")
    parser.add_argument("--date-order", choices=("dmy", "mdy"), default="dmy", help="ลำดับวันที่ของวันเกิดแบบ xx/xx/yyyy (ค่าเริ่มต้น: dmy)")
    parser.add_argument("--max-size", type=_max_size_arg, default=DEFAULT_MAX_MB, metavar="MB", help=f"ขนาดไฟล์ CSV สูงสุด (ค่าเริ่มต้น: {DEFAULT_MAX_MB} MB)")
    parser.add_argument("-f", "--force", action="store_true", help="เขียนทับไฟล์ผลลัพธ์ถ้ามีอยู่แล้ว")
    parser.add_argument("-q", "--quiet", action="store_true", help="ไม่แสดงคำเตือนรายแถว")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stderr, "reconfigure"):
        # Never crash on a console that cannot display Thai (e.g. cp437).
        sys.stderr.reconfigure(errors="backslashreplace")

    warning_count = 0

    def warn(line: int, message: str) -> None:
        nonlocal warning_count
        warning_count += 1
        if not args.quiet and warning_count <= MAX_WARNINGS_SHOWN:
            print(f"คำเตือน: บรรทัด {line}: {message}", file=sys.stderr)

    output = args.output or default_output_path(args.input)
    stats = Stats()
    try:
        data = read_input(args.input, args.max_size * 1024 * 1024)
        text, used_encoding = decode_csv_bytes(data, args.encoding)
        if args.encoding == "auto" and used_encoding == "cp874":
            print("หมายเหตุ: ไฟล์ไม่ใช่ UTF-8 จึงอ่านเป็นภาษาไทย Windows (cp874)", file=sys.stderr)
        options = Options(country_code=args.country_code, date_order=args.date_order)
        vcards = iter_vcards(text, args.delimiter, options, warn, stats)
        written = write_vcards(vcards, output, force=args.force, input_path=args.input)
    except ConversionError as exc:
        print(f"csv2vcf: ผิดพลาด: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        where = f" {show(str(exc.filename), PATH_SHOW_LIMIT)}" if exc.filename else ""
        print(f"csv2vcf: ผิดพลาด:{where} {exc.strerror or exc}", file=sys.stderr)
        return 1

    hidden = warning_count - MAX_WARNINGS_SHOWN
    if hidden > 0 and not args.quiet:
        print(f"... และคำเตือนอีก {hidden} รายการ", file=sys.stderr)
    if stats.ignored_columns and not args.quiet:
        names = ", ".join(show(name, 30) for name in stats.ignored_columns[:15])
        more = f" และอีก {len(stats.ignored_columns) - 15} คอลัมน์" if len(stats.ignored_columns) > 15 else ""
        print(f"หมายเหตุ: ไม่ได้ใช้คอลัมน์ {names}{more}", file=sys.stderr)
    target = "stdout" if output == "-" else show(output, PATH_SHOW_LIMIT)
    print(f"แปลงสำเร็จ {written} รายชื่อ -> {target} (ข้าม {stats.skipped} แถว)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
