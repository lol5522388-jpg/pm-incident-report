"""ASR 口語變體表 → 正規化（表驅動）。"""

from __future__ import annotations

import re

# (regex, replacement) — 順序固定；只擴表
ASR_VARIANTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"污[水誰]"), "污水"),
    (re.compile(r"溢[流留]"), "溢流"),
    (re.compile(r"([A-Za-z])\s*做(?=\s*\d|\s*[楼樓])"), r"\1座"),
    (re.compile(r"([A-Za-z])\s*坐(?=\s*\d|\s*[楼樓])"), r"\1座"),
    (re.compile(r"([A-Za-z])\s*做(?=\s*垃圾)"), r"\1座"),
    (re.compile(r"([A-Za-z])\s*座\s*座"), r"\1座"),
    (re.compile(r"(?<!\d)(\d{1,2})\s*[楼樓]"), r"\1樓"),
    (re.compile(r"八\s*楼"), "8樓"),
    (re.compile(r"8\s*楼"), "8樓"),
    (re.compile(r"十\s*五\s*楼"), "15樓"),
    (re.compile(r"后\s*楼梯"), "後樓梯"),
    (re.compile(r"后楼梯"), "後樓梯"),
    (re.compile(r"三\s*點\s*四\s*十"), "三點四十"),
    (re.compile(r"十\s*一\s*點\s*幾"), "十一點幾"),
    (re.compile(r"垃[圾极]房"), "垃圾房"),
    (re.compile(r"單\s*位\s*號\s*碼\s*無\s*涉\s*及"), "單位號碼無涉及"),
    (re.compile(r"好\s*臭"), "好臭"),
    (re.compile(r"告\s*示\s*牌"), "告示牌"),
]


def normalize_asr(text: str) -> str:
    out = text or ""
    for pattern, repl in ASR_VARIANTS:
        out = pattern.sub(repl, out)
    return out


def variant_rule_count() -> int:
    return len(ASR_VARIANTS)
