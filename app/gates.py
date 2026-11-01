"""欄位閘門。模型或規則抽出的句子，對不上原文、或含禁用詞，就不能進報告。"""

from __future__ import annotations

import re

from app.lexicon import BANNED, UNKNOWN, has_banned

_FIELD_KEYS = ("date", "time", "location", "party", "action", "witness", "injury", "action_taken")
_PUNCT = re.compile(r"[，。、\s：:；;,.「」\"'（）()]")


def compact(text: str) -> str:
    return _PUNCT.sub("", text or "")


def grounded(value: str, source: str) -> bool:
    if not value or value.strip() == UNKNOWN:
        return True
    if has_banned(value):
        return False
    needle = compact(value)
    haystack = compact(source)
    if len(needle) <= 12:
        return needle in haystack
    return needle in haystack or all(part in haystack for part in re.split(r"[，。；]", value) if compact(part))


def merge_llm(heuristic: dict, llm: dict | None, source: str) -> dict:
    """只接受能在口述裡逐字找到、且不含禁用詞的欄位。事件類型不得推翻關鍵詞。"""
    if not llm:
        return heuristic
    merged = {
        "event_type": heuristic["event_type"],
        "fields": {key: dict(value) for key, value in heuristic["fields"].items()},
        "names": list(heuristic["names"]),
        "subjective": list(heuristic["subjective"]),
        "transcript": heuristic["transcript"],
    }
    proposed_event = llm.get("event_type")
    if heuristic["event_type"] == "unknown" and proposed_event in {
        "facility_damage",
        "noise",
        "fall_injury",
        "parking",
        "unknown",
    }:
        merged["event_type"] = proposed_event
    for key in _FIELD_KEYS:
        proposed = llm.get(key)
        if not isinstance(proposed, str) or not proposed.strip():
            continue
        if not grounded(proposed.strip(), source):
            continue
        current = merged["fields"][key]
        if current["status"] == "confirmed" and current.get("value"):
            continue
        merged["fields"][key] = {"value": proposed.strip(), "status": "confirmed", "origin": "llm"}
    for word in llm.get("subjective_spans") or []:
        if isinstance(word, str) and word and word not in {item["word"] for item in merged["subjective"]}:
            if word in BANNED or word in source:
                merged["subjective"].append({"word": word, "status": "pending", "observed": None})
    return merged


def assert_objective(text: str) -> None:
    hits = has_banned(text)
    if hits:
        raise ValueError("事實正文含禁用詞：" + "、".join(hits))
