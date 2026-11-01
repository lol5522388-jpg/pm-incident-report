"""樓層短答合併（N樓、純數字、用戶確認）。"""

from __future__ import annotations

import re

from app.extract import _UNCERTAIN_FLOOR, _cn_number
from app.gap_policy import LABEL_FLOOR, LABEL_LOCATION
from app.location_assembly import (
    assemble_location,
    block_from_text,
    is_bare_spot_location,
    spot_from_text,
    spot_from_value,
    transcript_implies_floor,
)

_FLOOR_LINE = re.compile(
    r"^(?:第)?(?P<n>\d{1,2})\s*樓\s*\.?$|"
    r"^(?P<cn>[十兩一二三四五六七八九十]+)\s*樓\s*\.?$|"
    r"^第(?P<layer>\d{1,2})\s*層\s*\.?$",
    re.I,
)
_FLOOR_DIGIT_ONLY = re.compile(r"^\d{1,2}\s*\.?$")


def parse_floor_token(text: str) -> int | None:
    raw = (text or "").strip().strip("。．.")
    if not raw:
        return None
    match = _FLOOR_LINE.fullmatch(raw)
    if match:
        if match.group("n") or match.group("layer"):
            n = int(match.group("n") or match.group("layer"))
            return n if 1 <= n <= 99 else None
        cn = match.group("cn")
        n = _cn_number(cn)
        return n if n and 1 <= n <= 99 else None
    if _FLOOR_DIGIT_ONLY.fullmatch(raw):
        n = int(raw.strip())
        return n if 1 <= n <= 99 else None
    loose = re.search(r"(?:第)?(?P<n>\d{1,2})\s*樓", raw)
    if loose and len(raw) <= 12:
        n = int(loose.group("n"))
        return n if 1 <= n <= 99 else None
    return None


def floor_answer_pending(state: dict) -> bool:
    gaps = (state.get("voice") or {}).get("gaps") or []
    if LABEL_FLOOR in gaps or LABEL_LOCATION in gaps:
        return True
    fields = state.get("fields") or {}
    loc = fields.get("location") or {}
    value = loc.get("value") or ""
    transcript = state.get("transcript") or ""
    if loc.get("status") == "confirmed" and value and not re.search(r"\d{1,2}\s*樓|地下|地庫", value):
        if _UNCERTAIN_FLOOR.search(transcript) or (
            is_bare_spot_location(value) and transcript_implies_floor(transcript)
        ):
            return True
    return False


def _spot_without_floor(value: str, transcript: str = "") -> str:
    if re.search(r"走廊", transcript or ""):
        spot = "走廊"
    else:
        spot = spot_from_value(value) or spot_from_text(transcript) or (value or "").strip() or "走廊"
    if spot == "大堂" and re.search(r"大堂巡邏|大堂保安|我係大堂", transcript or ""):
        return "走廊"
    return spot or "走廊"


def apply_floor(state: dict, floor: int, *, user_confirmed: bool) -> None:
    text = state.get("transcript") or ""
    block = block_from_text(text)
    fields = state.setdefault("fields", {})
    loc = fields.get("location") or {}
    spot = _spot_without_floor(loc.get("value") or "", text)
    value = assemble_location(block=block, floor=floor, spot=spot)
    fields["location"] = {
        "value": value,
        "status": "confirmed",
        "origin": "manual" if user_confirmed else "auto",
    }
    floor_field: dict = {
        "value": floor,
        "status": "confirmed",
        "origin": "manual" if user_confirmed else "auto",
    }
    if user_confirmed and _UNCERTAIN_FLOOR.search(text):
        floor_field["note"] = "用戶確認"
    state["floor"] = floor_field
    fields["floor"] = floor_field


def try_absorb_floor(state: dict, turn_text: str) -> bool:
    floor = parse_floor_token(turn_text)
    if floor is None:
        return False
    if not floor_answer_pending(state):
        raw = (turn_text or "").strip().strip("。．.")
        if not (_FLOOR_DIGIT_ONLY.fullmatch(raw) or _FLOOR_LINE.fullmatch(raw)):
            return False
    user_confirmed = bool(_UNCERTAIN_FLOOR.search(state.get("transcript") or ""))
    apply_floor(state, floor, user_confirmed=user_confirmed)
    return True
