"""口講案件的後台。模擬頁同日後 WhatsApp 都叫這一層。

前台只負責收聲同播短句。這裡識別事件、標缺漏、出稿、核對、按口令送主管。
缺漏不代填。未齊料不出完整報告，也不朗讀報告正文。
"""

from __future__ import annotations

import html
import re
import uuid
from pathlib import Path

from app.asr_normalize import normalize_asr
from app.extract import extract, fold_width, specific_location, split_clauses
from app.followup_merge import apply_followup_merge, sync_pending_field
from app.floor_merge import try_absorb_floor
from app.gap_policy import LABEL_DATE, LABEL_FLOOR, LABEL_TIME, required_gaps, without_unit_gaps
from app.lexicon import DRUNK_PHRASE, EVENT_LABELS, auto_rewrite, has_banned, mentions_drunk
from app.pdf import render_pdf
from app.pipeline import Pipeline
from app.report import render
from app.session_policy import (
    assess_case_split,
    is_split_reply_new,
    is_split_reply_same,
    is_void_command,
)
from app.timeline import digest_turn, merge_session_nlp

_SEND = re.compile(
    r"^(?:傳送|send|送出去|送出|發送|寄出|送俾主管|送畀主管)[。！!?\s]*$",
    re.I,
)
_HOLD = re.compile(r"^(?:唔使|唔送|唔好送|取消|唔使送)[。！!?\s]*$")
_YES = re.compile(
    r"^(?:哦?(?:係|系)(?:呀|啊)?|啱|沒錯|無錯|正確|係咁)[。！!?\s]*$",
    re.I,
)
_NO = re.compile(r"^(?:唔係|不對|唔啱|有錯)[。！!?\s]*$")
_NEW = re.compile(r"^(?:新事件|新報告)\s*[：: ]*(.*)$", re.S)
_CORRECTION = re.compile(r"時間改為|日期改為|地點改為|傷勢改為|補充[:：]")
_CHECK = (
    ("date", "日期"),
    ("time", "時間"),
    ("location", "地點"),
    ("party", "當事人"),
    ("action", "看到的事實"),
    ("witness", "目擊"),
    ("injury", "傷勢"),
    ("action_taken", "已做的行動"),
)
_SPLIT_ASK = "呢段似新口述。係新事件定補充本單？答「新事件」或「補充」。"
_KNOWN = {
    "facility_damage": "設施損壞",
    "noise": "違規噪音",
    "fall_injury": "現場跌倒受傷",
    "parking": "違泊",
}


def hear(pipeline: Pipeline, phone: str, text: str) -> dict:
    body = normalize_asr(fold_width(text or "")).strip()
    if not body:
        return _pack(None, "未聽到內容。請再講一次。")
    fresh = re.search(r"新事件|新報告", body)
    if fresh:
        _close(pipeline, phone)
        body = body[fresh.end():].strip(" ：:，,。")
        if not body:
            return _pack(None, "上一單已結束。下一單可以直接講。")
        return _begin(pipeline, phone, body)
    existing = pipeline.store.latest_phone(phone)
    if existing and existing.get("channel") == "voice" and existing.get("status") != "closed":
        if _SEND.match(body):
            return _send(pipeline, existing)
        if _HOLD.match(body):
            return _note(pipeline, existing, "未送出。")
        if is_void_command(body):
            _close(pipeline, phone)
            return _pack(None, "已作廢本單。下一句可以直接講新口述。")
        voice = existing.setdefault("voice", {})
        if voice.get("split_pending"):
            if is_split_reply_new(body):
                voice["split_pending"] = False
                _close(pipeline, phone)
                rest = re.sub(r"^(?:新事件|新案|新報告)\s*[：: ]*", "", body).strip(" ：:，,。")
                if rest:
                    return _begin(pipeline, phone, rest)
                return _pack(None, "已開新案。請直接講新口述。")
            if is_split_reply_same(body):
                voice["split_pending"] = False
                pipeline.store.save(existing)
                return _note(pipeline, existing, "收到，當補充本單。請講要補嘅內容。")
            voice["split_pending"] = False
        if _YES.match(body):
            time_field = (existing.get("fields") or {}).get("time") or {}
            if time_field.get("status") == "needs_confirm":
                time_field["status"] = "confirmed"
                existing["fields"]["time"] = time_field
                return _finish(pipeline, existing, "確認時間")
            if existing.get("status") == "ready" and existing.get("report"):
                return _note(pipeline, existing, "知道。要送主管就講傳送。")
            if not required_gaps(existing):
                existing["guard_confirmed"] = True
                return _finish(pipeline, existing, "保安確認")
            return _note(pipeline, existing, "收到。仲有缺漏，請跟上面逐項補。")
        if _NO.match(body):
            return _note(pipeline, existing, "要改就直接講邊度唔啱。")
        split = assess_case_split(existing, body)
        if split == "fresh":
            _close(pipeline, phone)
            return _begin(pipeline, phone, body)
        if split == "ask":
            existing.setdefault("voice", {})["split_pending"] = True
            existing["voice"]["say"] = _SPLIT_ASK
            existing["message"] = _SPLIT_ASK
            pipeline.store.save(existing)
            return _pack(existing, _SPLIT_ASK)
        return _revise(pipeline, existing, body)
    return _begin(pipeline, phone, body)


def desk(pipeline: Pipeline, phone: str) -> dict:
    state = pipeline.store.latest_phone(phone)
    if not state or state.get("channel") != "voice":
        return {"status": "empty"}
    voice = state.get("voice") or {}
    return {
        "status": state.get("status"),
        "case_id": state.get("id"),
        "event_label": state.get("event_label"),
        "transcript": state.get("transcript"),
        "gaps": voice.get("gaps") or [],
        "check": voice.get("check") or {"right": [], "wrong": []},
        "say": voice.get("say") or "",
        "document": voice.get("document"),
        "sent": bool(voice.get("sent")),
        "complete": state.get("status") == "ready",
    }


def _begin(pipeline: Pipeline, phone: str, text: str) -> dict:
    extracted = extract(text, today=pipeline.today)
    pipeline._scrub(extracted)
    state = {
        "id": uuid.uuid4().hex[:12],
        "phone": phone,
        "channel": "voice",
        "source": "asr",
        "created_at": pipeline.now(),
        "engine": "heuristic",
        "event_type": extracted["event_type"],
        "event_label": _label(extracted["event_type"]),
        "fields": extracted["fields"],
        "names": [],
        "subjective": [],
        "suggestions": [],
        "transcript": extracted["transcript"],
        "turns": [{"role": "guard", "text": text, "at": pipeline.now()}],
        "versions": [],
        "audit": [],
        "version": 0,
        "question": None,
        "report": None,
        "message": None,
        "guard_confirmed": False,
        "timeline": None,
        "floor": None,
        "unit": None,
        "session_today": pipeline.today.isoformat(),
        "session_today_label": f"{pipeline.today:%Y年%m月%d日}",
    }
    merge_session_nlp(state)
    return _finish(pipeline, state, "初稿")


def _revise(pipeline: Pipeline, state: dict, text: str) -> dict:
    text = normalize_asr(text or "").strip()
    state["transcript"] = (state.get("transcript") or "") + "\n" + text
    state["turns"].append({"role": "guard", "text": text, "at": pipeline.now()})
    merged = apply_followup_merge(state, text, pipeline.today)
    if merged:
        state.setdefault("voice", {})["turn_digest"] = merged
    try_absorb_floor(state, text)
    clock = re.search(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})", text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            state["fields"]["time"] = {
                "value": f"{hour:02d}:{minute:02d}",
                "status": "confirmed",
                "vague": False,
                "origin": "manual",
            }
    if re.fullmatch(r"(?:時間)?未有記錄[。！]?", text):
        state["fields"]["time"] = {"value": "未有記錄", "status": "unknown", "origin": "manual"}
    extracted = extract(text, today=pipeline.today)
    pipeline._scrub(extracted)
    for key, field in extracted["fields"].items():
        if field.get("status") == "confirmed" and field.get("value"):
            state["fields"][key] = field
    if _CORRECTION.search(text):
        pipeline._correction_changes(state, auto_rewrite(text))
    earlier = extract(state["transcript"], today=pipeline.today)
    pipeline._scrub(earlier)
    for key, field in earlier["fields"].items():
        current = state["fields"][key]
        if current.get("status") != "confirmed" and field.get("status") == "confirmed" and field.get("value"):
            state["fields"][key] = field
    if state.get("event_type") in {None, "unknown"} and extracted["event_type"] != "unknown":
        state["event_type"] = extracted["event_type"]
    state["event_label"] = _label(state.get("event_type") or "unknown")
    merge_session_nlp(state)
    return _finish(pipeline, state, "保安口頭修正")


def _finish(pipeline: Pipeline, state: dict, reason: str) -> dict:
    missing = required_gaps(state)
    state["event_label"] = _label(state.get("event_type") or "unknown")
    if missing:
        state["status"] = "incomplete"
        state["question"] = None
        state["report"] = None
        document = None
    else:
        state["guard_confirmed"] = True
        _publish(pipeline, state, reason)
        document = _pdf(pipeline, state)
    check = _check(state)
    sync_pending_field(state, missing)
    turns = state.get("turns") or []
    last_text = turns[-1]["text"] if turns else ""
    voice = state.setdefault("voice", {})
    digest = voice.pop("turn_digest", None) or (digest_turn(last_text, today=pipeline.today) if len(turns) > 1 else [])
    say = _say(
        gaps=missing,
        wrong=check["wrong"],
        state=state,
        is_first=len(turns) <= 1 and bool(missing),
        follow_up=len(turns) > 1,
        digest=digest,
        complete=not missing and state.get("status") == "ready",
    )
    state["voice"] = {
        "say": say,
        "gaps": missing,
        "check": check,
        "document": document,
        "sent": bool((state.get("voice") or {}).get("sent")),
    }
    state["message"] = say
    pipeline.store.save(state)
    return _pack(state, say)


def _send(pipeline: Pipeline, state: dict) -> dict:
    missing = required_gaps(state)
    if missing or state.get("status") != "ready" or not state.get("report"):
        gaps = without_unit_gaps(missing or [], state)
        say = "仲缺緊" + "、".join(gaps or ["完整報告"]) + "。我未送畀主管，亦未有完整報告。"
        return _note(pipeline, state, say)
    from app.deliver import deliver

    folder = Path(pipeline.store.path).parent
    deliver(state, "email", folder=folder)
    voice = state.setdefault("voice", {})
    voice["sent"] = True
    say = "已送畀主管。"
    voice["say"] = say
    state["message"] = say
    pipeline.store.save(state)
    return _pack(state, say)


def _publish(pipeline: Pipeline, state: dict, reason: str) -> None:
    state["version"] += 1
    entry = {
        "version": state["version"],
        "created_at": pipeline.now(),
        "reason": reason,
        "formal": "",
        "summary": "",
        "hints": [],
        "facts": [],
        "fields": state["fields"],
    }
    state["versions"].append(entry)
    rendered = render(state, engine=state.get("engine") or "heuristic")
    entry["formal"] = rendered["formal"]
    entry["summary"] = rendered["summary"]
    entry["hints"] = rendered["hints"]
    entry["facts"] = rendered["facts"]
    state["report"] = {
        "version": rendered["version"],
        "formal": rendered["formal"],
        "summary": rendered["summary"],
        "hints": rendered["hints"],
        "disclaimer": rendered["disclaimer"],
    }
    state["status"] = "ready"
    state["question"] = None


def _pdf(pipeline: Pipeline, state: dict) -> dict:
    report = state["report"]
    pdf_bytes, _engine, _html = render_pdf(
        formal=report["formal"],
        summary=report["summary"],
        transcript=state.get("transcript") or "",
    )
    folder = Path(pipeline.store.path).parent / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    version = report["version"]
    path = folder / f"{state['id']}-v{version}.pdf"
    path.write_bytes(pdf_bytes)
    filename = f"事件報告-v{version}.pdf"
    return {"href": f"/v1/cases/{state['id']}/report.pdf", "filename": filename, "kind": "report"}


def _sheet(pipeline: Pipeline, state: dict, missing: list[str]) -> dict:
    rows = []
    for key, label in _CHECK:
        field = state["fields"][key]
        if field.get("status") == "confirmed" and field.get("value"):
            rows.append(f"<li>{html.escape(label)}：{html.escape(field['value'])}</li>")
    gap_rows = "".join(f"<li>{html.escape(item)}</li>" for item in missing)
    document = f"""<!DOCTYPE html>
<html lang="zh-Hant"><meta charset="utf-8"/>
<title>未完成草稿</title>
<body>
<h1>未完成草稿</h1>
<p>這不是完整報告。下面的缺漏沒有代填。</p>
<p>事件類型：{html.escape(state.get('event_label') or '')}</p>
<h2>收到的資料</h2>
<ul>{''.join(rows) or '<li>未有可寫入的事實</li>'}</ul>
<h2>缺漏</h2>
<ul>{gap_rows}</ul>
<h2>原始口述</h2>
<pre>{html.escape(state.get('transcript') or '')}</pre>
</body></html>"""
    folder = Path(pipeline.store.path).parent / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{state['id']}-sheet.html"
    path.write_text(document, encoding="utf-8")
    return {"href": f"/v1/voice/cases/{state['id']}/sheet", "filename": "未完成草稿", "kind": "incomplete"}


def _check(state: dict) -> dict:
    source = auto_rewrite(state.get("transcript") or "")
    raw = state.get("transcript") or ""
    right = []
    wrong = []
    for key, label in _CHECK:
        field = state["fields"][key]
        value = field.get("value")
        if field.get("status") != "confirmed" or not value:
            continue
        if key in {"date", "time", "location"} or _supported(value, source, raw):
            right.append(f"{label}：{value}")
        else:
            wrong.append(f"{label}：{value}")
    formal = ((state.get("report") or {}).get("formal")) or ""
    for word in has_banned(formal):
        wrong.append(f"報告含主觀詞：{word}")
    return {"right": right, "wrong": wrong}


_ANCHORS = {
    "有人在樓梯晾衫": "晾衫",
    "現場有滴水": "滴水",
    "單位門發出砰砰聲": "砰砰",
    "有人大聲喧嘩": "大聲",
    "一名男子帶有酒味，站在門口": "酒味",
    "走廊地面有水": "水",
    "地面濕滑": "濕滑",
    "未見天花滴水": "天花滴水",
    "天花有滴水": "天花滴水",
    "保安勸喻住客不要晾衫，並將衣物移開": "晾衫",
    "保安表明身份，勸喻雙方降低聲量": "勸喻",
    "已通知控制室": "控制室",
    "已安排清潔": "清潔",
    "已安排翻查閉路電視": "閉路",
    "未見有人受傷": "受傷",
    "保安沒有進入單位": "單位",
    "在場人士返回單位並關門": "閂門",
}


def _supported(value: str, source: str, raw: str) -> bool:
    if value in source or value in raw:
        return True
    if DRUNK_PHRASE in value and mentions_drunk(raw):
        return True
    parts = [part.strip("。 ") for part in value.split("。") if part.strip("。 ")]
    if not parts:
        return False
    for part in parts:
        anchor = _ANCHORS.get(part)
        if anchor and (anchor in source or anchor in raw):
            continue
        if any(len(clause) >= 2 and (clause in source or clause in raw) for clause in split_clauses(part)):
            continue
        return False
    return True


def _report_delivery_say(state: dict) -> str:
    report = state.get("report") or {}
    formal = (report.get("formal") or "").strip()
    summary = (report.get("summary") or "").strip()
    if formal and summary:
        return f"{formal}\n\n{summary}"
    if formal:
        return formal
    return "報告已出（供轉發核對）。要改直接講；送主管就講「傳送」。"


def _prioritize_gaps(gaps: list[str]) -> list[str]:
    order = {LABEL_DATE: 0, LABEL_FLOOR: 1, LABEL_TIME: 2}
    return sorted(gaps, key=lambda item: order.get(item, 50))


def _time_confirm_hint(state: dict) -> str | None:
    field = (state.get("fields") or {}).get("time") or {}
    if field.get("status") != "needs_confirm":
        return None
    value = field.get("value") or "時間"
    if re.search(r"15:40|15：40", value):
        return None
    return f"確認時間（{value} 啱唔啱？答「係」或講具體時間）"


def _say(
    *,
    gaps: list[str],
    wrong: list[str],
    state: dict,
    is_first: bool,
    follow_up: bool,
    digest: list[str],
    complete: bool,
) -> str:
    label = state.get("event_label") or "事件"
    if state.get("status") == "ready" and state.get("report") and not gaps:
        return _report_delivery_say(state)
    if complete and not wrong:
        return _report_delivery_say(state)
    lines: list[str] = []
    if wrong and state.get("report"):
        lines.append("核對有唔啱，請睇報告再講要改嘅位。")
    if is_first:
        lines.append(f"收到，{label}。")
        lines.append("仍缺：")
        first_gaps = without_unit_gaps(gaps, state)
        first_gaps = _prioritize_gaps(first_gaps)
        time_hint = _time_confirm_hint(state)
        if time_hint and LABEL_TIME in first_gaps:
            first_gaps = [time_hint if g == LABEL_TIME else g for g in first_gaps]
        if LABEL_FLOOR in first_gaps:
            first_gaps = [
                "確認樓層（可答：15樓 或 15）" if g == LABEL_FLOOR else g for g in first_gaps
            ]
        for index, item in enumerate(first_gaps[:3], 1):
            lines.append(f"{index}. {item}")
        if LABEL_TIME in first_gaps and time_hint:
            lines.append("（可講：10:15接通知→10:20到場→10:30離開）")
        return "\n".join(lines[:4])
    if follow_up:
        if digest:
            digest = [item for item in digest if not item.startswith("單位")]
            if digest:
                lines.append("已記：" + "；".join(digest) + "。")
        gaps = without_unit_gaps(gaps, state)
        time_hint = _time_confirm_hint(state)
        if gaps:
            show = list(gaps)
            if time_hint and LABEL_TIME in show:
                show = [time_hint if g == LABEL_TIME else g for g in show]
            if LABEL_FLOOR in show:
                show = [
                    "確認樓層（可答：15樓 或 15）" if g == LABEL_FLOOR else g for g in show
                ]
            lines.append("仍欠：" + "、".join(show) + "。")
        elif not wrong:
            lines.append("資料齊，報告已出（供轉發核對）。")
        elif not gaps:
            lines.append("報告已出（供轉發核對）。")
        return "\n".join(lines[:5]) or "收到。"
    gaps = without_unit_gaps(gaps, state)
    if gaps:
        lines.append("仍欠：" + "、".join(gaps) + "。")
    return "\n".join(lines[:5])


def _short_captured(state: dict) -> list[str]:
    found = []
    for key, label in _CHECK:
        field = state["fields"][key]
        value = field.get("value")
        if field.get("status") != "confirmed" or not value:
            continue
        short = value if len(value) <= 24 else value[:24] + "…"
        found.append(f"{label}{short}")
    return found


def _label(event: str) -> str:
    if event in _KNOWN:
        return _KNOWN[event]
    if event in EVENT_LABELS and event not in {"unknown", "out_of_scope"}:
        return EVENT_LABELS[event]
    return "口述事件"


def _close(pipeline: Pipeline, phone: str) -> None:
    existing = pipeline.store.latest_phone(phone)
    if existing and existing.get("status") not in {None, "closed"}:
        existing["status"] = "closed"
        existing["question"] = None
        pipeline.store.save(existing)


def _note(pipeline: Pipeline, state: dict | None, say: str) -> dict:
    if state is not None:
        voice = state.setdefault("voice", {})
        voice["say"] = say
        state["message"] = say
        pipeline.store.save(state)
    return _pack(state, say)


def _pack(state: dict | None, say: str, *, resent: bool = True) -> dict:
    voice = (state or {}).get("voice") or {}
    document = voice.get("document") if resent else voice.get("document")
    return {
        "say": say,
        "status": (state or {}).get("status") or "idle",
        "case_id": (state or {}).get("id"),
        "event_label": (state or {}).get("event_label"),
        "gaps": voice.get("gaps") or [],
        "check": voice.get("check") or {"right": [], "wrong": []},
        "document": document,
        "sent": bool(voice.get("sent")),
        "complete": (state or {}).get("status") == "ready",
    }
