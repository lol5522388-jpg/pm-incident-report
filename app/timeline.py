"""時間軸同補料解析（箭頭、接通知／到場／完結、樓層／室）。"""

from __future__ import annotations

import re

_STEP_TIME = re.compile(r"(?:約\s*)?(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})")
_CN_STEP = re.compile(
    r"(?:約\s*)?(?P<h>\d{1,2})\s*[点點時]\s*(?P<m>\d{1,2})\s*分?\s*(?P<label>接通知|接到通知|到場|到场|完結|完结|離開|离开|聞聲|通知控制室|通知|入單位|入屋|離開現場)?"
)
_LOOSE_STEP = re.compile(
    r"(?:約\s*)?(?P<h>\d{1,2})\s*[:：点點]\s*(?P<m>\d{1,2})\s*分?\s*(?P<label>接通知|接到通知|到場|到场|完結|完结|離開|离开|聞聲|通知控制室|通知|入單位|入屋)?"
)
_CN_ORAL_STEP = re.compile(
    r"(?:約\s*)?"
    r"(?P<h>[零〇一二三四五六七八九十两兩\d]{1,3})\s*[点點]"
    r"(?:(?P<m>[零〇一二三四五六七八九十两兩\d]{1,3}|半))?\s*分?\s*"
    r"(?P<label>接通知|接到通知|據報|据报|到場見|到场见|到場|到场|完結|完结|離開|离开|見到|闻到|闻聲)?"
)
_EVENT_DATE = re.compile(r"事件日期\s*(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})")
_CONFIRM_LOC = re.compile(r"位置確認\s*(?P<loc>[^；;\n]+)")
_UNIT_UNKNOWN = re.compile(
    r"單位號未有記錄|单位号未有记录|"
    r"單位[^\n。，；]{0,16}(?:睇唔到|看不到|未能|唔知|未知|不清楚)|"
    r"(?:睇唔到|看不到)[^\n。，；]{0,12}(?:單位|幾樓|楼层)"
)
_FLOOR_UNIT = re.compile(
    r"(?P<block>[A-Za-z])\s*座?\s*(?P<floor>\d{1,2})\s*樓\s*(?P<unit>\d{3,4}[A-Za-z]?)\s*(?:室|号|號)?"
)
_FLOOR_ONLY = re.compile(r"(?P<block>[A-Za-z])\s*座?\s*(?P<floor>\d{1,2})\s*樓")
_UNIT_SLASH = re.compile(r"(?P<floor>\d{1,2})\s*樓\s*(?P<unit>\d{3,4})|(?:^|[、，/\s])(?P<unit_only>\d{3,4})(?:室|号|號)?(?:$|[、，/\s])")


def _stamp(h: str, m: str) -> str:
    return f"{int(h):02d}:{int(m):02d}"


def _stamp_cn(h_raw: str, m_raw: str | None) -> str | None:
    from app.extract import _cn_number

    if h_raw.isdigit():
        hour = int(h_raw)
    else:
        hour = _cn_number(h_raw)
    if hour is None or not (0 <= hour <= 23):
        return None
    if not m_raw or m_raw == "半":
        minute = 30 if m_raw == "半" else 0
    elif m_raw.isdigit():
        minute = int(m_raw)
    else:
        minute = _cn_number(m_raw)
    if minute is None or not (0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _pack_timeline(steps: list[dict]) -> dict | None:
    if len(steps) < 2:
        return None
    start, end = steps[0], steps[-1]
    approx = any(step.get("approx") for step in steps)
    span = f"約 {start['time']} 至 {end['time']}" if approx else f"{start['time']}–{end['time']}"
    return {
        "start": start["time"],
        "end": end["time"],
        "span": span,
        "steps": steps,
    }


def parse_timeline(text: str) -> dict | None:
    raw = text or ""
    if "→" not in raw and "->" not in raw:
        return None
    steps: list[dict] = []
    for segment in re.split(r"→|->", raw):
        segment = segment.strip(" ；;，,")
        match = _STEP_TIME.search(segment) or _LOOSE_STEP.search(segment)
        if not match:
            continue
        stamp = _stamp(match.group("h"), match.group("m"))
        label = (match.groupdict().get("label") or "").strip()
        approx = "約" in segment[: match.start() + 8]
        steps.append({"time": stamp, "label": label, "approx": approx})
    return _pack_timeline(steps)


def parse_timeline_loose(text: str) -> dict | None:
    found = parse_timeline(text)
    if found:
        return found
    raw = text or ""
    steps: list[dict] = []
    seen: set[str] = set()
    for match in _CN_ORAL_STEP.finditer(raw):
        stamp = _stamp_cn(match.group("h"), match.group("m"))
        if not stamp or stamp in seen:
            continue
        seen.add(stamp)
        label = (match.groupdict().get("label") or "").strip()
        window = raw[max(0, match.start() - 4) : match.start() + 6]
        approx = "約" in window
        steps.append({"time": stamp, "label": label, "approx": approx})
    for pattern in (_LOOSE_STEP, _CN_STEP, _STEP_TIME):
        for match in pattern.finditer(raw):
            stamp = _stamp(match.group("h"), match.group("m"))
            if stamp in seen:
                continue
            seen.add(stamp)
            label = (match.groupdict().get("label") or "").strip()
            window = raw[max(0, match.start() - 4) : match.start() + 6]
            approx = "約" in window
            steps.append({"time": stamp, "label": label, "approx": approx})
    steps.sort(key=lambda item: item["time"])
    return _pack_timeline(steps)


def parse_location_loose(text: str) -> dict:
    raw = text or ""
    out: dict = {}
    match = _FLOOR_UNIT.search(raw)
    if match:
        block = match.group("block")
        floor = match.group("floor")
        unit = match.group("unit")
        loc = f"{block}座{floor}樓" if block else f"{floor}樓"
        out["location"] = {"value": loc, "status": "confirmed", "origin": "manual"}
        out["unit"] = {"value": unit, "status": "confirmed", "origin": "manual"}
        return out
    floor = _FLOOR_ONLY.search(raw)
    if floor:
        block = floor.group("block")
        f = floor.group("floor")
        loc = f"{block}座{f}樓" if block else f"{f}樓"
        out["location"] = {"value": loc, "status": "confirmed", "origin": "manual"}
    slash = _UNIT_SLASH.search(raw)
    if slash:
        if slash.group("unit"):
            u = slash.group("unit")
            f = slash.group("floor")
            if f and "location" not in out:
                out["location"] = {"value": f"{f}樓", "status": "confirmed", "origin": "manual"}
            out["unit"] = {"value": u, "status": "confirmed", "origin": "manual"}
        elif slash.group("unit_only"):
            out["unit"] = {"value": slash.group("unit_only"), "status": "confirmed", "origin": "manual"}
    return out


def parse_supplement(text: str, *, today=None) -> dict:
    """從齊料補句抽出日期、時間軸、地點、單位狀態。"""
    from datetime import date as date_cls

    from app.date_patterns import parse_date_text

    raw = text or ""
    out: dict = {}
    today = today or date_cls.today()
    parsed = parse_date_text(raw, today)
    if parsed:
        out["date"] = {"value": parsed.label_zh, "status": "confirmed", "origin": "manual"}
        out["date_iso"] = parsed.iso
    elif _EVENT_DATE.search(raw):
        date_match = _EVENT_DATE.search(raw)
        y, mo, d = int(date_match.group("y")), int(date_match.group("mo")), int(date_match.group("d"))
        out["date"] = {"value": f"{y}年{mo:02d}月{d:02d}日", "status": "confirmed", "origin": "manual"}
        out["date_iso"] = f"{y:04d}-{mo:02d}-{d:02d}"
    loc = _CONFIRM_LOC.search(raw)
    if loc:
        out["location"] = {"value": loc.group("loc").strip(), "status": "confirmed", "origin": "manual"}
    if _UNIT_UNKNOWN.search(raw):
        out["unit"] = {"value": "未有記錄", "status": "unknown", "origin": "manual"}
    timeline = parse_timeline_loose(raw)
    if timeline:
        out["timeline"] = timeline
        out["time"] = {
            "value": timeline["span"],
            "status": "confirmed",
            "origin": "manual",
            "vague": False,
        }
    out.update({k: v for k, v in parse_location_loose(raw).items() if k not in out})
    return out


def merge_session_nlp(state: dict) -> None:
    """把整段對話口述合併入時間、地點、單位（唔重置 session）。"""
    from app.extract import apply_written_facts
    from app.floor_merge import try_absorb_floor

    text = state.get("transcript") or ""
    if not text.strip():
        return
    turns = state.get("turns") or []
    if turns:
        try_absorb_floor(state, turns[-1].get("text") or "")
    from datetime import date as date_cls

    today = date_cls.today()
    if state.get("session_today"):
        today = date_cls.fromisoformat(state["session_today"])
    sup = parse_supplement(text, today=today)
    if sup.get("date"):
        state["fields"]["date"] = sup["date"]
        if sup.get("date_iso"):
            state["date_iso"] = sup["date_iso"]
    if sup.get("location"):
        new_val = sup["location"]["value"]
        old_val = (state.get("fields") or {}).get("location", {}).get("value") or ""
        keep_floor = old_val and re.search(r"\d{1,2}\s*樓", old_val) and not re.search(
            r"\d{1,2}\s*樓", new_val
        )
        if not keep_floor:
            block = re.search(r"([A-Za-z])\s*座", old_val) or re.search(r"([A-Za-z])\s*座", text)
            if block and not re.search(r"[A-Za-z]\s*座", new_val):
                new_val = f"{block.group(1)}座{new_val}"
            state["fields"]["location"] = {**sup["location"], "value": new_val}
    if sup.get("unit"):
        state["unit"] = sup["unit"]
        state["fields"]["unit"] = sup["unit"]
    if sup.get("timeline"):
        time_field = (state.get("fields") or {}).get("time") or {}
        if time_field.get("origin") != "correction":
            state["timeline"] = sup["timeline"]
            state["fields"]["time"] = sup["time"]
    apply_written_facts(state.setdefault("fields", {}), text)
    from app.gap_policy import note_conditional_fields

    note_conditional_fields(state)


def digest_turn(text: str, *, today=None) -> list[str]:
    """本句新吸收（供 Bot 短回覆）。"""
    from datetime import date as date_cls

    from app.date_patterns import parse_date_text
    from app.floor_merge import parse_floor_token

    hints: list[str] = []
    today = today or date_cls.today()
    floor = parse_floor_token(text)
    if floor is not None:
        hints.append(f"樓層 {floor} 樓")
    parsed = parse_date_text(text, today)
    if parsed:
        hints.append(f"已記 {parsed.iso}")
    sup = parse_supplement(text, today=today)
    if sup.get("timeline"):
        tl = sup["timeline"]
        hints.append(f"時間 {tl['start']}–{tl['end']}")
    elif sup.get("time"):
        hints.append(f"時間 {sup['time']['value']}")
    if sup.get("location"):
        hints.append(f"地點 {sup['location']['value']}")
    if sup.get("unit") and sup["unit"].get("status") == "confirmed":
        hints.append(f"單位 {sup['unit']['value']}")
    if sup.get("date_iso") and not any(h.startswith("已記") for h in hints):
        hints.append(f"已記 {sup['date_iso']}")
    elif sup.get("date"):
        hints.append(f"日期 {sup['date']['value']}")
    return hints
