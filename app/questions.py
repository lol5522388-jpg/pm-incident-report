"""一次只問一項。按鈕標題符合 WhatsApp 20 字上限。"""

from __future__ import annotations

_BUTTONS = {
    "unknown": {"id": "unknown", "title": "未能確定"},
    "none_injury": {"id": "none_injury", "title": "沒有人受傷"},
    "none_party": {"id": "none_party", "title": "現場沒有其他人"},
    "none_action": {"id": "none_action", "title": "未有採取行動"},
    "confirm": {"id": "confirm", "title": "正確"},
    "reject": {"id": "reject", "title": "不正確"},
    "omit": {"id": "omit", "title": "省略主觀描述"},
    "accept": {"id": "accept", "title": "採用熱詞"},
    "keep": {"id": "keep", "title": "保持原話"},
    "facility_damage": {"id": "facility_damage", "title": "設施損壞"},
    "noise": {"id": "noise", "title": "噪音"},
    "fall_injury": {"id": "fall_injury", "title": "跌倒受傷"},
    "out": {"id": "out", "title": "其他暫不處理"},
}


def _pick(*keys: str) -> list[dict]:
    buttons = [_BUTTONS[key] for key in keys]
    for button in buttons:
        if len(button["title"]) > 20:
            raise ValueError(button["title"])
    return buttons


def missing(field: str, known: dict) -> dict:
    date = (known.get("date") or {}).get("value")
    clock = (known.get("time") or {}).get("value")
    prompts = {
        "when": "請補充事件日期同時間，時間要到分鐘，例如 2026-10-22 22:15。"
        + (f"目前聽到的時間是 {clock}。" if clock else "")
        + (f"目前聽到的日期是 {date}。" if date else "")
        + "未能確定就撳按鈕，不要估。",
        "location": "請補充具體地點：座數或大廈、樓層、位置。例如 A座3樓後樓梯。",
        "party": "請只講看到的人：人數、衣著、髮型或約略年齡。沒有其他人就撳按鈕。不要寫態度或動機。",
        "action": "請按先後講你看到或聽到的動作。不要加原因。",
        "witness": "請講你當時站在哪裡，看得到或聽得到的範圍到哪裡。",
        "injury": "請講看得到的傷勢，或對方親口講的痛楚。沒有人受傷要明確回答。未講過不可當沒有事。",
        "action_taken": "請講你已經做了什麼，例如通知主管、放置告示、致電 999。未有行動就撳按鈕。",
    }
    button_keys = {
        "when": ("unknown",),
        "location": ("unknown",),
        "party": ("none_party", "unknown"),
        "action": ("unknown",),
        "witness": ("unknown",),
        "injury": ("none_injury", "unknown"),
        "action_taken": ("none_action", "unknown"),
    }
    return {"field": field, "text": prompts[field], "buttons": _pick(*button_keys[field]), "input": "text"}


def confirm_when(date_value: str, time_value: str) -> dict:
    return {
        "field": "when_confirm",
        "text": f"請確認日期時間是否為 {date_value} {time_value}。語音轉寫的時間不會自動採用。",
        "buttons": _pick("confirm", "reject"),
        "input": "choice",
    }


def confirm_location(value: str) -> dict:
    return {
        "field": "location_confirm",
        "text": f"請確認地點是否為「{value}」。語音轉寫的地點不會自動採用。",
        "buttons": _pick("confirm", "reject"),
        "input": "choice",
    }


def confirm_name(name: str, index: int) -> dict:
    return {
        "field": f"name:{index}",
        "text": f"口述中的姓名「{name}」需要你確認。時間、地點、人名不會由系統改寫。",
        "buttons": _pick("confirm", "reject"),
        "input": "choice",
    }


def fix_name(name: str, index: int) -> dict:
    return {
        "field": f"name_fix:{index}",
        "text": f"請講正確姓名，取代「{name}」。不想寫姓名就撳未能確定。",
        "buttons": _pick("unknown"),
        "input": "text",
    }


def suggestion(item: dict, index: int) -> dict:
    return {
        "field": f"asr:{index}",
        "text": (
            f"熱詞近音：「{item['heard']}」可能是「{item['suggestion']}」。"
            "這是建議，不會自動改。地點與人名必須由你確認。"
        ),
        "buttons": _pick("accept", "keep"),
        "input": "choice",
    }


def subjective(word: str, index: int) -> dict:
    return {
        "field": f"subjective:{index}",
        "text": (
            f"「{word}」是主觀描述，不能寫進事實。請改講看得到或聽得到的行為，"
            "例如音量、用詞、手勢。沒有這類觀察就省略。"
        ),
        "buttons": _pick("omit"),
        "input": "text",
    }


def event_type() -> dict:
    return {
        "field": "event_type",
        "text": "這段口述未能歸入本期三類。請選：設施損壞、噪音、跌倒受傷，或其他（暫不生成報告）。",
        "buttons": _pick("facility_damage", "noise", "fall_injury", "out"),
        "input": "choice",
    }


def bad_correction(words: list[str]) -> dict:
    shown = "、".join(words)
    return {
        "field": "correction",
        "text": f"修正內容含主觀詞「{shown}」，這次沒有改報告。請只講可觀察事實。",
        "buttons": _pick("omit"),
        "input": "text",
    }
