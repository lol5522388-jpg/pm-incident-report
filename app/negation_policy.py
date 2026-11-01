"""否定反轉表：冇／未有／沒有＋事件 優先於同段其他觸發詞。"""

from __future__ import annotations

import re


def _clauses(text: str) -> list[str]:
    parts: list[str] = []
    for chunk in re.split(r"[。！？!?；;\n]+", text or ""):
        for part in re.split(r"[，,]", chunk):
            part = part.strip()
            if part:
                parts.append(part)
    return parts

# (id, 否定表述, 事件觸發詞)
_EVENT_SPECS: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "fall",
        re.compile(
            r"冇\s*人?\s*跌倒|沒\s*有\s*人?\s*跌倒|未\s*有\s*人?\s*跌倒|"
            r"未\s*見\s*.*跌倒|未\s*有\s*跌倒|暫\s*時\s*無\s*人?\s*跌倒|"
            r"暂\s*時\s*無\s*人?\s*跌倒|无\s*人?\s*跌倒|没有人跌倒"
        ),
        re.compile(r"跌倒|摔倒|跌親|摔低|著地|撐地|坐在地上|向前跌"),
    ),
    (
        "injury",
        re.compile(
            r"冇\s*人?\s*受傷|沒\s*有\s*人?\s*受傷|無\s*人?\s*受傷|未\s*見\s*.*受傷|"
            r"未\s*有\s*受傷|暂\s*無\s*人?\s*受傷|无\s*人?\s*受傷"
        ),
        re.compile(r"受傷|流血|有血|紅腫|瘀|痛到|昏迷"),
    ),
)

# 污水／地滑 不等同跌倒案型（除非口述明確肯定跌倒）
_NON_FALL_CONTEXT = re.compile(
    r"污水|溢流|垃圾房|地\s*滑|好\s*滑|濕\s*滑|小心地\s*滑|水\s*漬"
)


def _spec(event_id: str) -> tuple[re.Pattern[str], re.Pattern[str]] | None:
    for eid, deny, trigger in _EVENT_SPECS:
        if eid == event_id:
            return deny, trigger
    return None


def denied_in_text(text: str, event_id: str) -> bool:
    pair = _spec(event_id)
    if not pair:
        return False
    deny, trigger = pair
    raw = text or ""
    if deny.search(raw):
        return True
    for clause in _clauses(raw):
        if deny.search(clause):
            return True
    return False


def asserted_in_text(text: str, event_id: str) -> bool:
    pair = _spec(event_id)
    if not pair:
        return False
    deny, trigger = pair
    raw = text or ""
    if denied_in_text(raw, event_id):
        return False
    for clause in _clauses(raw):
        if deny.search(clause):
            continue
        if trigger.search(clause):
            return True
    return bool(trigger.search(raw))


def fall_asserted(text: str) -> bool:
    raw = text or ""
    pair = _spec("fall")
    if not pair:
        return False
    deny, trigger = pair
    if deny.search(raw):
        return False
    for clause in _clauses(raw):
        if deny.search(clause):
            continue
        if trigger.search(clause):
            return True
    return False


def injury_asserted(text: str) -> bool:
    if denied_in_text(text, "injury"):
        return False
    return asserted_in_text(text, "injury")


def injury_status_phrase(text: str) -> str | None:
    """否定受傷／跌倒時的可寫狀態。"""
    raw = text or ""
    if denied_in_text(raw, "fall") and denied_in_text(raw, "injury"):
        return "未有人跌倒；未有受傷記錄"
    if denied_in_text(raw, "fall"):
        return "未有人跌倒"
    if denied_in_text(raw, "injury"):
        return "未有受傷記錄"
    if re.search(r"冇人受傷|無人受傷|沒有人受傷|未見有人受傷", raw):
        return "未見有人受傷"
    return None


def forbidden_fact_substrings(text: str) -> tuple[str, ...]:
    """報告嚴謹版不得當作已發生事實的片段。"""
    raw = text or ""
    out: list[str] = []
    if denied_in_text(raw, "fall"):
        out.extend(["跌倒受傷", "向前跌倒", "摔倒受傷", "現場跌倒受傷"])
    return tuple(dict.fromkeys(out))


def spec_count() -> int:
    return len(_EVENT_SPECS)
