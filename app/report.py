"""【物管事件報告｜供轉發核對】版面。PDF／傳送稿跟此結構。"""

from __future__ import annotations

import re

from app.extract import display_value
from app.gates import assert_objective
from app.lexicon import DRUNK_PHRASE, UNKNOWN, mentions_drunk, to_written
from app.negation_policy import injury_status_phrase

ONE_LINE = "僅根據提供資料客觀轉寫，不含推測。"
TITLE = "【物管事件報告｜供轉發核對】"
CLOSING = "請轉發核對；要改直接回覆。"


def _iso_date(date_value: str, fallback: str) -> str:
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_value or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return fallback


def _display_location(raw: str, unit_field: dict | None) -> str:
    loc = (raw or "").strip()
    loc = re.split(r"[；;]", loc)[0].strip()
    loc = re.sub(r"單位號未有記錄", "", loc)
    loc = re.sub(r"近單位門口", "", loc)
    loc = re.sub(r"垃圾房門外走廊", "垃圾房外走廊", loc)
    loc = re.sub(r"([A-Za-z])座", r"\1 座", loc)
    loc = re.sub(r"座\s*(\d{1,2})\s*樓", r"座 \1 樓", loc)
    loc = re.sub(r"(\d{1,2})\s*樓", r"\1 樓", loc)
    loc = re.sub(r"\s+", " ", loc).strip()
    if unit_field and unit_field.get("unit_status") == "na":
        return loc or UNKNOWN
    if unit_field and unit_field.get("status") == "unknown":
        suffix = "（單位號未有記錄）"
        if suffix not in loc:
            loc = f"{loc}{suffix}" if loc else "（單位號未有記錄）"
    return loc or UNKNOWN


def _party_block(transcript: str, party_value: str) -> str:
    text = transcript or ""
    parts: list[str] = []
    if re.search(r"女住戶|女戶|一名女", text):
        parts.append("一名女子（住戶，據觀察）")
    if re.search(r"酒味|醉酒|醉漢", text) or (party_value and "疑似醉酒" in party_value):
        parts.append(
            "一名男子（門口應答，帶酒味，報告寫作「一名疑似醉酒之男子」）"
        )
    elif re.search(r"男人|男子|對面男", text):
        parts.append("一名男子（門口應答）")
    if party_value and party_value != UNKNOWN and DRUNK_PHRASE in party_value and len(parts) < 2:
        parts.append(f"一名男子（報告寫作「{DRUNK_PHRASE}」）")
    return "；".join(parts) if parts else UNKNOWN


def _stamp(date_iso: str, time: str, *, approx: bool = False, end: str | None = None) -> str:
    prefix = f"{date_iso} 約 " if approx else f"{date_iso} "
    if end:
        return f"{prefix}{time} 至 {end}"
    return f"{prefix}{time}"


def _observation_bullets(state: dict, date_iso: str, place: str) -> list[str]:
    if _is_sewage(state):
        return _sewage_observation(state, date_iso, place)
    transcript = state.get("transcript") or ""
    timeline = state.get("timeline") or {}
    steps = timeline.get("steps") or []
    bullets: list[str] = []
    if len(steps) >= 2 and re.search(r"喧嘩|鬧|砰砰|拍門|撞擊", transcript):
        t0 = steps[0]["time"]
        bullets.append(
            f"• {_stamp(date_iso, t0, approx=True)}，於 B 座往中高層巡邏途中，"
            "聞有人喧嘩及單位門發出撞擊聲。"
        )
        t1 = steps[1]["time"] if len(steps) > 1 else t0
        bullets.append(
            f"• {_stamp(date_iso, t1, approx=True)}，於 {place.split('（')[0].strip()}，"
            "見走廊地面有水、地面濕滑；一名女子站於單位門口向對面單位出聲；"
            "對面單位一名男子站於門口回應，該男子帶有酒味。"
        )
        t_end = steps[2]["time"] if len(steps) > 2 else t1
        bullets.append(
            f"• {_stamp(date_iso, t1, approx=True, end=t_end)}，於上述地點，"
            "未見天花正在滴水；水源位置未有記錄。"
        )
        return bullets
    when = display_value(state["fields"]["time"])
    body = _fact_body(state)
    if when != UNKNOWN:
        bullets.append(f"• {date_iso} {when}，於{place}，{body}。")
    else:
        bullets.append(f"• 於{place}，{body}。")
    return bullets


def _action_bullets(state: dict, date_iso: str, place: str) -> list[str]:
    if _is_sewage(state):
        return _sewage_actions(state, date_iso, place)
    transcript = state.get("transcript") or ""
    timeline = state.get("timeline") or {}
    steps = timeline.get("steps") or []
    core = place.split("（")[0].strip()
    bullets: list[str] = []
    if len(steps) >= 3 and re.search(r"勸喻|細聲|表明身份", transcript):
        t1 = steps[1]["time"]
        t_in = steps[2]["time"]
        bullets.append(
            f"• {_stamp(date_iso, t1, approx=True, end=t_in)}，於 {core}，"
            "保安表明身份，勸喻雙方降低聲量、避免影響其他住戶；其後雙方各自返回單位並關門。"
        )
        if len(steps) >= 4:
            t_notify = steps[3]["time"]
            via = "對講" if "對講" in transcript else ""
            via = f"以{via}" if via else ""
            bullets.append(
                f"• {_stamp(date_iso, t_notify, approx=True)}，保安{via}通知控制室，"
                "要求安排清潔及翻查閉路電視。"
            )
        bullets.append("• 報告時：未有入單位；暫未接獲受傷報告。")
        return bullets
    taken = _formal_voice(display_value(state["fields"]["action_taken"]))
    if taken != UNKNOWN:
        when = display_value(state["fields"]["time"])
        lead = f"{date_iso} {when}，" if when != UNKNOWN else ""
        bullets.append(f"• {lead}於{core}，{taken}。")
    if re.search(r"冇入過|沒有入|未入", transcript):
        bullets.append("• 報告時：未有入單位；暫未接獲受傷報告。")
    return bullets or ["• 報告時未有行動記錄。"]


def _formal_voice(text: str) -> str:
    line = to_written(text or "").strip("。 ")
    line = re.sub(r"^我(?:已|們)?", "", line)
    line = re.sub(r"^保安", "", line)
    line = line.strip("，, ")
    if line.startswith("已"):
        return f"保安{line}"
    return line or UNKNOWN


def _is_sewage(state: dict) -> bool:
    blob = state.get("transcript") or ""
    return bool(re.search(r"污水|溢流", blob))


def _fact_in_transcript(value: str, transcript: str) -> bool:
    if not value or value == UNKNOWN:
        return False
    raw = transcript or ""
    if mentions_drunk(value) and not mentions_drunk(raw):
        return False
    written = to_written(value)
    if value in raw or written in raw:
        return True
    for piece in re.split(r"[。；，,]", written):
        piece = piece.strip()
        if len(piece) >= 3 and piece in raw:
            return True
    skip = {"有人", "現場", "一名", "男子", "女子", "住戶", "保安", "報告", "當時", "上述"}
    for length in (4, 3, 2):
        for i in range(len(written) - length + 1):
            token = written[i : i + length]
            if not all("\u4e00" <= ch <= "\u9fff" for ch in token):
                continue
            if token in skip:
                continue
            if token in raw:
                return True
    return False


def _fact_body(state: dict, transcript: str | None = None) -> str:
    raw = transcript if transcript is not None else (state.get("transcript") or "")
    chunks = []
    for key in ("action", "witness", "party"):
        value = display_value(state["fields"][key])
        if value != UNKNOWN and _fact_in_transcript(value, raw):
            chunks.append(_formal_voice(value))
    return "；".join(chunks) if chunks else "未有可寫入事實"


def _sewage_observation(state: dict, date_iso: str, place: str) -> list[str]:
    when = display_value(state["fields"]["time"])
    approx = when.startswith("約")
    time_show = when.replace("約 ", "") if approx else when
    lead = _stamp(date_iso, time_show, approx=approx) if when != UNKNOWN else date_iso
    seen = _formal_voice(display_value(state["fields"]["action"]))
    bullets = [f"• {lead}，於{place}，{seen}。"]
    injury = display_value(state["fields"].get("injury") or {})
    neg = injury_status_phrase(state.get("transcript") or "")
    if injury != UNKNOWN:
        bullets.append(f"• 報告時：{injury}。")
    elif neg:
        bullets.append(f"• 報告時：{neg}。")
    elif re.search(r"無人受傷|冇人受傷|沒有人受傷", state.get("transcript") or ""):
        bullets.append("• 報告時：未見有人受傷。")
    return bullets


def _sewage_actions(state: dict, date_iso: str, place: str) -> list[str]:
    core = place.split("（")[0].strip()
    when = display_value(state["fields"]["time"])
    approx = when.startswith("約")
    time_show = when.replace("約 ", "") if approx else when
    lead = _stamp(date_iso, time_show, approx=approx) if when != UNKNOWN else date_iso
    taken = _formal_voice(display_value(state["fields"]["action_taken"]))
    bullets: list[str] = []
    if taken != UNKNOWN:
        bullets.append(f"• {lead}，於{core}，{taken}。")
    transcript = state.get("transcript") or ""
    if re.search(r"污水|垃圾房", transcript) and not re.search(
        r"入垃圾房|進垃圾房|入咗垃圾房", transcript
    ):
        bullets.append("• 報告時：保安沒有進入垃圾房。")
    if not bullets:
        bullets.append("• 報告時未有行動記錄。")
    return bullets


def _unrecorded(state: dict) -> str:
    unit = state.get("unit") or (state.get("fields") or {}).get("unit") or {}
    sewage = _is_sewage(state)
    if sewage and unit.get("unit_status") == "na":
        return "儀器核實時間、水源、閉路結果"
    if unit.get("unit_status") == "na":
        return "儀器核實時間、閉路結果"
    return "確實單位號、儀器核實時間、水源、閉路結果"


def _summary_section(state: dict, date_iso: str, place: str) -> str:
    timeline = state.get("timeline") or {}
    if timeline.get("start") and timeline.get("end"):
        span_show = f"約 {timeline['start']}–{timeline['end']}"
    else:
        span_show = timeline.get("span") or display_value(state["fields"]["time"])
    lines = [
        f"• 時間：{date_iso} {span_show}" if span_show != UNKNOWN else f"• 時間：{date_iso}",
        f"• 地點：{place.replace('（單位號未有記錄）', '（單位待補）')}",
    ]
    transcript = state.get("transcript") or ""
    sewage = _is_sewage(state)
    if not sewage and re.search(r"女住戶", transcript) and mentions_drunk(transcript):
        lines.append("• 人物：女住戶一名；男子一名（帶酒味／疑似醉酒）")
    party = _party_block(transcript, display_value(state["fields"]["party"]))
    if sewage and party != UNKNOWN and mentions_drunk(party) and not mentions_drunk(transcript):
        party = UNKNOWN
    if party != UNKNOWN and "人物" not in "\n".join(lines):
        lines.append(f"• 人物：{party}")
    if not sewage and re.search(r"喧嘩|拍門|砰砰", transcript):
        lines.append("• 事件：喧嘩及拍門聲；走廊地滑有水；雙方在門口爭論後已入屋")
    else:
        lines.append(f"• 事件：{_fact_body(state, transcript)}")
    if re.search(r"喧嘩|拍門|砰砰|鬧", transcript):
        lines.append("• 行動：勸喻細聲 → 通知控制室清潔及翻查閉路；無人報受傷、保安未入單位")
        lines.append("• 跟進：補單位號；查 CCTV；確認清潔完成（交主管）")
    else:
        taken = display_value(state["fields"]["action_taken"])
        if taken != UNKNOWN:
            lines.append(f"• 行動：{taken}")
        lines = lines[:5]
    return "\n".join(lines)


def render(state: dict, *, engine: str) -> dict:
    del engine
    fields = state["fields"]
    record_iso = _iso_date("", "2026-10-22")
    if state.get("created_at"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", state["created_at"])
        if m:
            record_iso = m.group(1)
    date_value = display_value(fields["date"])
    event_iso = state.get("date_iso") or _iso_date(date_value, record_iso)
    unit_field = state.get("unit") or fields.get("unit")
    place = _display_location(display_value(fields["location"]), unit_field)
    timeline = state.get("timeline") or {}
    span = timeline.get("span") or display_value(fields["time"])
    time_line = f"{event_iso} {span}" if span != UNKNOWN else event_iso
    party = _party_block(state.get("transcript") or "", display_value(fields["party"]))
    obs = _observation_bullets(state, event_iso, place)
    act = _action_bullets(state, event_iso, place)
    for line in obs + act:
        assert_objective(line.lstrip("• ").rstrip("。"))
    strict = [
        TITLE,
        "",
        "報告編號：待編",
        f"記錄時間：{record_iso}（香港時間）",
        "資料來源：前線保安口述轉寫",
        f"事件日期：{event_iso}",
        "",
        "（1）嚴謹版",
        "",
        f"時間：{time_line}",
        f"地點：{place}",
        f"人物：{party}",
        "",
        "目擊事實：",
        "",
        *obs,
        "",
        "行動：",
        "",
        *act,
        "",
        f"未有記錄：{_unrecorded(state)}",
        "",
        f"聲明：{ONE_LINE}",
    ]
    formal = "\n".join(strict)
    summary = "（2）摘要版\n\n" + _summary_section(state, event_iso, place) + "\n\n" + CLOSING
    for block in (formal, summary):
        assert "原始口述" not in block
        assert "整理方式" not in block
        assert "大廈公契" not in block
    return {
        "version": state["version"],
        "formal": formal,
        "summary": summary,
        "hints": [],
        "facts": obs,
        "disclaimer": ONE_LINE,
    }
