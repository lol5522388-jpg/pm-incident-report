"""地點組裝：座／樓層／位置片段由表驅動合併，禁止淨位置而口述有樓。"""

from __future__ import annotations

import re
from typing import Callable

from app.extract import _UNCERTAIN_FLOOR

# 位置片段（長者優先匹配）
_SPOT_NAMES: tuple[str, ...] = (
    "消防樓梯",
    "後樓梯",
    "電梯大堂",
    "垃圾房門外走廊",
    "垃圾房門外",
    "垃圾房",
    "接待處",
    "梯間",
    "走廊",
    "大堂",
    "車位",
    "門口",
    "通道",
    "樓梯",
    "天台",
    "平台",
    "困梯",
    "電梯",
    "地庫",
    "地下",
    "渠口",
    "沙井",
    "車場",
    "工地",
)

_SPOT_ALT = "|".join(re.escape(s) for s in _SPOT_NAMES)
_BARE_SPOT = re.compile(rf"^(?:{'|'.join(re.escape(s) for s in _SPOT_NAMES)})$")

_BLOCK = re.compile(r"([A-Za-z])\s*座")
_FLOOR_NUM = re.compile(r"(?<!\d)(?P<n>\d{1,2})\s*樓|第(?P<layer>\d{1,2})\s*層")
_FLOOR_UNCERTAIN_CTX = re.compile(r"\d{1,2}\s*定\s*\d{1,2}|[十兩一二三四五六七八九十]{1,4}\s*定\s*")
_ESTATE_AFTER_FLOOR = re.compile(
    r"(?<!\d)(?P<n>\d{1,2})\s*樓\s*[\u4e00-\u9fff]{2,8}(?:邨|苑|閣|園|軒|居|大廈|中心)"
)
_ESTATE_NAME = re.compile(r"[\u4e00-\u9fff]{2,8}(?:邨|苑|閣|園|軒|居|大廈|中心|[\u4e00-\u9fff]{2,6}樓)")

# 由口述擷取完整地點（表驅動，按優先序）→ (regex, 是否淨「地下」)
_ASSEMBLY_SPECS: tuple[tuple[str, bool], ...] = (
    (rf"(?P<block>[A-Za-z])座\s*(?P<floor>\d{{1,2}})\s*樓\s*(?P<spot>{_SPOT_ALT})", False),
    (rf"(?P<floor>\d{{1,2}})\s*樓\s*(?P<spot>{_SPOT_ALT})", False),
    (rf"第(?P<floor>\d{{1,2}})\s*層\s*(?P<spot>{_SPOT_ALT})", False),
    (rf"(?P<block>[A-Za-z])座\s*(?P<floor>\d{{1,2}})\s*樓\s*垃圾房(?:門外)?(?:走廊)?", False),
    (rf"(?P<floor>\d{{1,2}})\s*樓\s*垃圾房(?:門外)?(?:走廊)?", False),
    (r"(?P<block>[A-Za-z])座\s*地下", True),
    (r"(?P<block>[A-Za-z])座\s*地庫", True),
)
_ASSEMBLY_FROM_TEXT: tuple[tuple[re.Pattern[str], bool], ...] = tuple(
    (re.compile(p, re.I), underground) for p, underground in _ASSEMBLY_SPECS
)


def block_from_text(text: str) -> str:
    match = _BLOCK.search(text or "")
    return f"{match.group(1)}座" if match else ""


def spot_from_text(text: str) -> str | None:
    raw = text or ""
    for name in _SPOT_NAMES:
        if name in raw.replace(" ", ""):
            return name
    return None


def spot_from_value(value: str) -> str:
    spot = re.sub(r"\s+", "", (value or "").strip())
    spot = re.sub(r"^[A-Za-z]座", "", spot)
    spot = re.sub(r"^\d{1,2}樓", "", spot)
    spot = re.sub(r"^地下", "", spot)
    spot = re.sub(r"^地庫", "", spot)
    return spot or ""


def is_bare_spot_location(value: str) -> bool:
    compact = re.sub(r"\s+", "", (value or "").strip())
    if not compact:
        return False
    if re.search(r"\d{1,2}樓|地下|地庫", compact):
        return False
    if re.search(r"[A-Za-z]座", compact):
        return False
    return bool(_BARE_SPOT.fullmatch(compact))


def _floor_int_from_match(text: str, match: re.Match[str]) -> int | None:
    n = match.group("n") or match.group("layer")
    if not n:
        return None
    start, end = match.span()
    window = text[max(0, start - 6) : min(len(text), end + 8)]
    if _FLOOR_UNCERTAIN_CTX.search(window):
        return None
    estate_window = text[start : min(len(text), end + 14)]
    if _ESTATE_AFTER_FLOOR.match(estate_window):
        return None
    val = int(n)
    return val if 1 <= val <= 99 else None


def definite_floor_from_text(text: str) -> int | None:
    """口述有單一確定樓層（非十五定十六）。"""
    if _UNCERTAIN_FLOOR.search(text or ""):
        return None
    for match in _FLOOR_NUM.finditer(text or ""):
        n = _floor_int_from_match(text, match)
        if n is not None:
            return n
    return None


def transcript_implies_floor(text: str) -> bool:
    """口述曾提及樓層數字（含不確定）。"""
    return bool(re.search(r"(?<!\d)\d{1,2}\s*樓|第\d{1,2}\s*層", text or ""))


def assemble_location(*, block: str = "", floor: int | None = None, spot: str = "") -> str:
    parts: list[str] = []
    if block:
        parts.append(block if block.endswith("座") else f"{block}座")
    if floor is not None:
        parts.append(f"{floor}樓")
    if spot:
        parts.append(re.sub(r"\s+", "", spot))
    return "".join(parts)


def _from_groups(groups: dict[str, str | None], *, underground: bool = False) -> str | None:
    block_raw = groups.get("block")
    block = f"{block_raw}座" if block_raw else ""
    if underground:
        return assemble_location(block=block, spot="地下")
    floor_raw = groups.get("floor")
    floor = int(floor_raw) if floor_raw and floor_raw.isdigit() else None
    spot = groups.get("spot") or ""
    if not block and floor is None and not spot:
        return None
    return assemble_location(block=block, floor=floor, spot=spot)


def assembly_rule_count() -> int:
    return len(_ASSEMBLY_SPECS)


def canonical_from_transcript(text: str) -> str | None:
    raw = text or ""
    if _ESTATE_AFTER_FLOOR.search(raw) and not re.search(
        rf"(?<!\d)\d{{1,2}}\s*樓\s*(?:{_SPOT_ALT})", raw
    ):
        return None
    for pattern, underground in _ASSEMBLY_FROM_TEXT:
        match = pattern.search(raw)
        if not match:
            continue
        if not underground and "spot" in match.groupdict() and match.group("floor"):
            estate_window = raw[match.start() : min(len(raw), match.end() + 14)]
            if _ESTATE_AFTER_FLOOR.match(estate_window):
                continue
        built = _from_groups(match.groupdict(), underground=underground)
        if built:
            return built
    return None


def enrich_location_value(value: str, transcript: str) -> str:
    """補齊缺樓／缺座而口述已有。"""
    compact_val = re.sub(r"\s+", "", (value or "").strip())
    if not compact_val:
        canon = canonical_from_transcript(transcript)
        return canon or compact_val

    if _ESTATE_NAME.search(compact_val) or _ESTATE_AFTER_FLOOR.search(transcript or ""):
        return compact_val

    if re.search(r"[A-Za-z]座\d{1,2}樓", compact_val):
        return compact_val
    if re.search(r"\d{1,2}樓", compact_val) and not is_bare_spot_location(compact_val):
        block = block_from_text(transcript)
        if block and not compact_val.startswith(block):
            return f"{block}{compact_val}"
        return compact_val

    canon = canonical_from_transcript(transcript)
    if canon and len(canon) >= len(compact_val):
        return canon

    block = block_from_text(transcript)
    floor = definite_floor_from_text(transcript)
    spot = spot_from_value(compact_val) or spot_from_text(transcript) or compact_val
    if re.search(r"走廊", transcript or "") and spot == "大堂":
        if re.search(r"大堂巡邏|大堂保安|我係大堂", transcript or ""):
            spot = "走廊"
    if floor is not None or block:
        merged = assemble_location(block=block, floor=floor, spot=spot if is_bare_spot_location(compact_val) else spot_from_value(compact_val) or spot)
        if merged:
            return merged
    return compact_val


def _drop_bare_if_transcript_has_floor(candidates: list[str], transcript: str) -> list[str]:
    if not transcript_implies_floor(transcript):
        return candidates
    has_rich = any(not is_bare_spot_location(c) for c in candidates)
    if not has_rich:
        canon = canonical_from_transcript(transcript)
        if canon:
            candidates.append(canon)
        enriched = [
            enrich_location_value(c, transcript)
            for c in candidates
            if is_bare_spot_location(c)
        ]
        candidates.extend(enriched)
    return [c for c in candidates if c and (not is_bare_spot_location(c) or not transcript_implies_floor(transcript))]


def pick_best_location(
    candidates: list[str],
    transcript: str,
    *,
    prefer_corridor_over_lobby: bool = False,
) -> str | None:
    pool = list(dict.fromkeys(re.sub(r"\s+", "", c) for c in candidates if c))
    pool = _drop_bare_if_transcript_has_floor(pool, transcript)
    if not pool:
        return None
    if prefer_corridor_over_lobby and re.search(r"走廊", transcript or ""):
        with_corridor = [item for item in pool if "走廊" in item]
        if with_corridor:
            return max(with_corridor, key=len)
        without_lobby = [item for item in pool if item != "大堂"]
        if without_lobby:
            return max(without_lobby, key=len)
    return max(pool, key=len)


def infer_location_from_text(
    text: str,
    exact_matcher: Callable[[str], str | None],
    *,
    extra_snippets: Callable[[str], list[str]] | None = None,
) -> str | None:
    raw = text or ""
    candidates: list[str] = []
    exact = exact_matcher(raw)
    if exact:
        candidates.append(exact.strip())
    if extra_snippets:
        candidates.extend(extra_snippets(raw))
    canon = canonical_from_transcript(raw)
    if canon:
        candidates.append(canon)
    prefer_corridor = bool(re.search(r"走廊", raw))
    return pick_best_location(candidates, raw, prefer_corridor_over_lobby=prefer_corridor)


def enforce_location_integrity(fields: dict, transcript: str) -> None:
    loc = fields.get("location") or {}
    value = (loc.get("value") or "").strip()
    if not value and not transcript:
        return
    new_val = enrich_location_value(value, transcript) if value else (canonical_from_transcript(transcript) or "")
    if not new_val:
        return
    if new_val != re.sub(r"\s+", "", value):
        fields["location"] = {
            **loc,
            "value": new_val,
            "status": "confirmed",
            "origin": loc.get("origin") or "auto",
        }
