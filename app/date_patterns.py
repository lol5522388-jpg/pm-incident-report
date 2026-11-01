"""日期 pattern 表：通用解析，禁止單案 if。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# 剝離前綴（順序：長者先）
DATE_PREFIXES = (
    r"事件日期\s*",
    r"日期係\s*",
    r"日期是\s*",
    r"日期\s*",
)

# 相對日
RELATIVE_DAY = (
    ("today", re.compile(r"今日|今天|今個日")),
    ("yesterday", re.compile(r"尋日|昨天|琴日|昨個日")),
    ("day_before", re.compile(r"前日|前天|前個日")),
)

# 結構化：name 供測試覆蓋統計
DATE_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    (
        "iso_dash",
        re.compile(r"(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})"),
    ),
    (
        "yyyy_ymd",
        re.compile(r"(?P<y>\d{4})\s*年\s*(?P<mo>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日號号]"),
    ),
    (
        "yy_ymd",
        re.compile(r"(?P<y>\d{2})\s*年\s*(?P<mo>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日號号]"),
    ),
    (
        "md_cn",
        re.compile(r"(?P<mo>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日號号]"),
    ),
    (
        "slash_md",
        re.compile(r"(?<!\d)(?P<mo>\d{1,2})\s*[/／]\s*(?P<d>\d{1,2})(?!\d)"),
    ),
    (
        "dot_md",
        re.compile(r"(?<!\d)(?P<mo>\d{1,2})\s*[\.．]\s*(?P<d>\d{1,2})(?!\d)"),
    ),
]


@dataclass(frozen=True)
class DateParse:
    iso: str
    label_zh: str
    pattern: str


def strip_date_prefix(text: str) -> str:
    raw = (text or "").strip().strip("。．.,，")
    for prefix in DATE_PREFIXES:
        raw = re.sub(rf"^{prefix}", "", raw, flags=re.I).strip()
    return raw


def _year_ok(y: int, today: date) -> bool:
    return today.year - 1 <= y <= today.year + 1


def _resolve_yy(yy: int, today: date) -> int:
    y = 2000 + yy if yy <= 99 else yy
    if y > today.year + 1:
        y -= 100
    return y


def _pack(y: int, mo: int, d: int, today: date, pattern: str) -> DateParse | None:
    if not _year_ok(y, today):
        return None
    try:
        value = date(y, mo, d)
    except ValueError:
        return None
    iso = f"{value:%Y-%m-%d}"
    label = f"{value:%Y年%m月%d日}"
    return DateParse(iso=iso, label_zh=label, pattern=pattern)


def parse_date_text(text: str, today: date) -> DateParse | None:
    """從一句（可含前綴）解析日期；失敗返回 None。"""
    raw = strip_date_prefix(text)
    if not raw:
        return None
    for name, pattern in RELATIVE_DAY:
        if pattern.search(raw):
            if name == "today":
                target = today
            elif name == "yesterday":
                target = today - timedelta(days=1)
            else:
                target = today - timedelta(days=2)
            return DateParse(
                iso=f"{target:%Y-%m-%d}",
                label_zh=f"{target:%Y年%m月%d日}",
                pattern=name,
            )
    for name, regex in DATE_REGEXES:
        match = regex.search(raw)
        if not match:
            continue
        groups = match.groupdict()
        explicit_year = "y" in groups and groups.get("y")
        if explicit_year:
            y_raw = groups["y"]
            y = int(y_raw)
            if len(y_raw) == 2:
                y = _resolve_yy(y, today)
        else:
            y = today.year
            before = raw[max(0, match.start() - 6) : match.start()]
            if re.search(r"\d{4}\s*年", before):
                continue
        mo = int(groups["mo"])
        d = int(groups["d"])
        packed = _pack(y, mo, d, today, name)
        if packed:
            return packed
        if explicit_year and name in {"yyyy_ymd", "yy_ymd", "iso_dash"}:
            return None
    return None


def apply_date_field(state: dict, parsed: DateParse) -> None:
    fields = state.setdefault("fields", {})
    fields["date"] = {
        "value": parsed.label_zh,
        "status": "confirmed",
        "origin": "manual",
    }
    state["date_iso"] = parsed.iso


def pattern_catalog() -> list[str]:
    names = [name for name, _ in RELATIVE_DAY]
    names.extend(name for name, _ in DATE_REGEXES)
    names.append("prefix_strip")
    return names
