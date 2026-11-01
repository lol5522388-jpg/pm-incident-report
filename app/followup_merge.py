"""短答合併：問緊邊個欄，短句只寫入該欄。"""

from __future__ import annotations

import re
from datetime import date

from app.date_patterns import apply_date_field, parse_date_text, strip_date_prefix
from app.floor_merge import try_absorb_floor
from app.gap_policy import LABEL_DATE, LABEL_FLOOR, LABEL_LOCATION, LABEL_TIME
from app.session_policy import is_session_control

_FIELD_BY_LABEL = {
    LABEL_DATE: "date",
    LABEL_TIME: "time",
    LABEL_FLOOR: "floor",
    LABEL_LOCATION: "location",
}


def pending_field_from_gaps(gaps: list[str]) -> str | None:
    order = (LABEL_DATE, LABEL_FLOOR, LABEL_LOCATION, LABEL_TIME)
    for label in order:
        if label in gaps:
            return _FIELD_BY_LABEL[label]
    return None


def sync_pending_field(state: dict, gaps: list[str]) -> None:
    voice = state.setdefault("voice", {})
    pending = pending_field_from_gaps(gaps)
    if pending:
        voice["pending_field"] = pending
    else:
        voice.pop("pending_field", None)


def _is_short_turn(text: str) -> bool:
    body = (text or "").strip()
    return len(body) <= 48 or is_session_control(body)


def apply_followup_merge(state: dict, text: str, today: date) -> list[str]:
    """短答只 merge 問緊嘅欄。返回 digest 短句（如 已記 YYYY-MM-DD）。"""
    voice = state.get("voice") or {}
    pending = voice.get("pending_field")
    raw = (text or "").strip()
    if not raw:
        return []

    if pending in {"floor", "location"} and _is_short_turn(raw):
        if try_absorb_floor(state, text):
            floor = (state.get("fields") or {}).get("floor") or {}
            loc = (state.get("fields") or {}).get("location") or {}
            value = floor.get("value")
            place = loc.get("value") or ""
            if value and place:
                return [f"地點 {place}"]
            if value:
                return [f"樓層 {value} 樓"]
            return ["樓層已記"]

    if pending == "time" and _is_short_turn(raw):
        from app.extract import _clock

        clock = _clock(strip_date_prefix(raw))
        if clock.get("status") == "confirmed" and clock.get("value"):
            state.setdefault("fields", {})["time"] = {**clock, "origin": "manual"}
            return [f"時間 {clock['value']}"]
        if clock.get("status") == "needs_confirm" and clock.get("value"):
            state.setdefault("fields", {})["time"] = {**clock, "origin": "manual"}
            return [f"時間 {clock['value']}"]

    parsed_date = parse_date_text(raw, today)
    if parsed_date and (pending == "date" or _date_only_turn(raw)):
        apply_date_field(state, parsed_date)
        return [f"已記 {parsed_date.iso}"]

    return []


def _date_only_turn(text: str) -> bool:
    stripped = strip_date_prefix(text)
    if len(stripped) > 40:
        return False
    return bool(
        re.search(
            r"年|月|/|\.|今日|今天|今個日|尋日|昨天|琴日|前日|前天|\d{4}-\d{2}-\d{2}",
            stripped,
        )
    )
