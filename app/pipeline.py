"""追問狀態機。缺任何必填項都不出最終報告，也不能跳題。"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import date, datetime

from app.asr import review_transcript
from app.extract import extract, fold_width, specific_location, split_clauses
from app.gates import merge_llm
from app.hotwords import load_hotwords
from app.lexicon import EVENT_LABELS, UNKNOWN, auto_rewrite, has_banned, mentions_drunk, rewrite_drunk
from app.llm import extract_with_llm
from app.questions import (
    bad_correction,
    confirm_location,
    confirm_name,
    confirm_when,
    event_type,
    fix_name,
    missing,
    subjective,
    suggestion,
)
from app.report import render
from app.store import Store

READY_MSG = "草稿已完成，須由保安或主管確認簽署。系統不提供法律意見。"
OUT_OF_SCOPE_MSG = (
    "這段口述是違泊或其他本期不處理的類別。"
    "v0.1 只為設施損壞、違規噪音、現場跌倒受傷生成報告，"
    "因此不會出嚴謹版或摘要版，也不會下法律結論。口述已保存。"
)
_FILL = {
    "none_injury": ("injury", "沒有人受傷"),
    "none_party": ("party", "現場沒有其他人"),
    "none_action": ("action_taken", "報告時未有行動記錄"),
}
_FIELD_LABELS = (
    ("date", "日期"),
    ("time", "時間"),
    ("location", "地點"),
    ("party", "當事人"),
    ("action", "觀察"),
    ("witness", "目擊範圍"),
    ("injury", "傷勢"),
    ("action_taken", "已採取行動"),
)


class CaseError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class Pipeline:
    def __init__(self, store: Store, *, today: date | None = None, now: datetime | None = None, engine: str = "heuristic"):
        self.store = store
        self.today = today or date.today()
        self._now = now
        self.engine = engine

    def now(self) -> str:
        if self._now is not None:
            return self._now.isoformat(timespec="seconds")
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def ingest(self, text: str, *, source: str = "text", phone: str | None = None) -> dict:
        cleaned = fold_width(text or "").strip()
        if not cleaned:
            raise CaseError(400, "沒有口述內容。")
        extracted = extract(cleaned, today=self.today)
        engine = self.engine
        if engine == "llm":
            try:
                proposed = extract_with_llm(cleaned, load_hotwords())
                extracted = merge_llm(extracted, proposed, cleaned)
            except Exception as exc:
                engine = "heuristic"
                extracted["engine_note"] = f"大語言模型未能使用，已改用規則抽取：{exc}"
        self._scrub(extracted)
        if source == "asr":
            for key in ("date", "time", "location"):
                field = extracted["fields"][key]
                if field["status"] == "confirmed":
                    field["status"] = "needs_confirm"
            suggestions = review_transcript(cleaned)
        else:
            suggestions = []
        state = {
            "id": uuid.uuid4().hex[:12],
            "phone": phone,
            "source": source,
            "created_at": self.now(),
            "engine": engine,
            "engine_note": extracted.get("engine_note"),
            "event_type": extracted["event_type"],
            "fields": extracted["fields"],
            "names": extracted["names"],
            "subjective": extracted["subjective"],
            "suggestions": suggestions,
            "transcript": extracted["transcript"],
            "turns": [{"role": "guard", "text": cleaned, "at": self.now(), "source": source}],
            "versions": [],
            "audit": [],
            "version": 0,
            "question": None,
            "report": None,
            "message": None,
            "_needs_publish": True,
        }
        self._sync(state, "初稿")
        self.store.save(state)
        return self.public(state)

    def answer(self, case_id: str, *, field: str, text: str | None = None, choice: str | None = None) -> dict:
        state = self._load(case_id)
        if state["status"] == "ready":
            pending = state.get("question") or {}
            if pending.get("field") == "correction":
                if choice == "omit" or not (text or "").strip():
                    state["question"] = None
                    self.store.save(state)
                    return self.public(state)
                return self.correct(case_id, text or "")
            raise CaseError(409, "報告已完成。請用修正模式補充。")
        if state["status"] != "collecting" or not state.get("question"):
            raise CaseError(409, "這個案件現在不接受補充。")
        current = state["question"]["field"]
        if field != current:
            raise CaseError(409, "請先回答目前這一題，不能跳過。")
        if not self._apply(state, field, (text or "").strip(), choice):
            self.store.save(state)
            return self.public(state)
        state["turns"].append({"role": "guard", "text": text or choice or "", "at": self.now(), "field": field})
        self._sync(state, "初稿")
        self.store.save(state)
        return self.public(state)

    def correct(self, case_id: str, text: str) -> dict:
        state = self._load(case_id)
        if state["status"] != "ready":
            raise CaseError(409, "報告尚未完成，不能進入修正模式。")
        utterance = auto_rewrite(fold_width(text or "").strip())
        if not utterance:
            state["question"] = bad_correction(["評價"])
            state["message"] = "這次修正沒有寫入。"
            self.store.save(state)
            return self.public(state)
        hits = has_banned(utterance)
        if hits:
            state["question"] = bad_correction(hits)
            state["message"] = "這次修正沒有寫入。"
            self.store.save(state)
            return self.public(state)
        location_change = re.search(r"地點改為\s*([^。；\n]+)", utterance)
        if location_change and not specific_location(location_change.group(1)):
            state["question"] = {
                "field": "correction",
                "text": "地點要同時有座數或大廈、樓層、位置。這次沒有改報告。",
                "buttons": [{"id": "omit", "title": "省略主觀描述"}],
                "input": "text",
            }
            state["message"] = "這次修正沒有寫入。"
            self.store.save(state)
            return self.public(state)
        changes = self._correction_changes(state, utterance)
        state["turns"].append({"role": "guard", "text": utterance, "at": self.now(), "field": "correction"})
        state["_last_correction"] = utterance
        self._publish(state, "保安修正", changes)
        self.store.save(state)
        return self.public(state)

    def receive_phone(self, phone: str, text: str, *, source: str = "text") -> dict:
        body = fold_width(text or "").strip()
        if re.match(r"^(新事件|新報告)", body):
            self._close_latest(phone)
            body = re.sub(r"^(新事件|新報告)\s*[：: ]*", "", body).strip()
            if not body:
                return self._idle("好，下一單直接講發生咩事。語音或者打字都得。")
            return self.ingest(body, source=source, phone=phone)
        existing = self.store.latest_phone(phone)
        if existing and existing["status"] == "collecting" and existing.get("question"):
            return self.answer(existing["id"], field=existing["question"]["field"], text=body)
        if existing and existing["status"] == "ready":
            return self.correct(existing["id"], body)
        return self.ingest(body, source=source, phone=phone)

    def _close_latest(self, phone: str) -> None:
        existing = self.store.latest_phone(phone)
        if existing and existing["status"] in {"ready", "collecting", "out_of_scope"}:
            existing["status"] = "closed"
            existing["question"] = None
            existing["message"] = "保安開咗新一單。"
            self.store.save(existing)

    def _idle(self, message: str) -> dict:
        return {
            "case_id": "",
            "status": "idle",
            "event_type": "unknown",
            "event_label": "",
            "engine": self.engine,
            "question": None,
            "report": None,
            "message": message,
            "captured": [],
            "version": 0,
            "versions": [],
            "audit": [],
            "transcript": "",
        }

    def receive_button(self, case_id: str, field: str, choice: str) -> dict:
        return self.answer(case_id, field=field, choice=choice)

    def get(self, case_id: str) -> dict:
        return self.public(self._load(case_id))

    def require_ready(self, case_id: str) -> dict:
        state = self._load(case_id)
        if state["status"] != "ready" or not state.get("report"):
            raise CaseError(409, "報告未完成，不能送出或列印。")
        return state

    def public(self, state: dict) -> dict:
        report = None
        if state["status"] == "ready" and state.get("report"):
            report = {
                "version": state["report"]["version"],
                "formal": state["report"]["formal"],
                "summary": state["report"]["summary"],
                "hints": state["report"]["hints"],
                "disclaimer": state["report"]["disclaimer"],
            }
        captured = []
        for key, label in _FIELD_LABELS:
            field = state["fields"][key]
            if field["status"] in {"confirmed", "unknown"} and field.get("value"):
                captured.append(
                    {"field": key, "label": label, "value": field["value"], "status": field["status"]}
                )
        return {
            "case_id": state["id"],
            "status": state["status"],
            "event_type": state["event_type"],
            "event_label": EVENT_LABELS.get(state["event_type"], state["event_type"]),
            "engine": state["engine"],
            "question": state.get("question"),
            "report": report,
            "message": state.get("message"),
            "captured": captured,
            "version": state["version"],
            "versions": [
                {
                    "version": item["version"],
                    "formal": item["formal"],
                    "summary": item["summary"],
                    "reason": item["reason"],
                    "created_at": item["created_at"],
                }
                for item in state["versions"]
            ],
            "audit": state["audit"],
            "transcript": state["transcript"],
        }

    def _load(self, case_id: str) -> dict:
        state = self.store.get(case_id)
        if not state:
            raise CaseError(404, "找不到案件。")
        return state

    def _sync(self, state: dict, reason: str) -> None:
        if state["event_type"] in {"parking", "out_of_scope"}:
            state["status"] = "out_of_scope"
            state["question"] = None
            state["message"] = OUT_OF_SCOPE_MSG
            state["_needs_publish"] = False
            return
        question = self._next(state)
        if question:
            state["status"] = "collecting"
            state["question"] = question
            state["message"] = "還有必填項未齊，報告未發出。"
            return
        if state.get("_needs_publish") or not state["versions"]:
            self._publish(state, reason)
            return
        state["status"] = "ready"
        state["question"] = None
        state["message"] = READY_MSG

    def _publish(self, state: dict, reason: str, changes: list[tuple[str, str, str]] | None = None) -> None:
        state["version"] += 1
        stamp = self.now()
        for field, old, new in changes or []:
            state["audit"].append(
                {
                    "version": state["version"],
                    "at": stamp,
                    "field": field,
                    "old": old or "（空）",
                    "new": new,
                }
            )
        entry = {
            "version": state["version"],
            "created_at": stamp,
            "reason": reason,
            "formal": "",
            "summary": "",
            "hints": [],
            "facts": [],
            "fields": copy.deepcopy(state["fields"]),
        }
        state["versions"].append(entry)
        rendered = render(state, engine=state["engine"])
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
        state["_needs_publish"] = False
        if reason == "初稿":
            state["message"] = READY_MSG
        else:
            state["message"] = f"已記錄修正，現為 v{state['version']}。先前版本仍保留。仍須人工確認簽署。"

    def _next(self, state: dict) -> dict | None:
        if state["event_type"] == "unknown" and not (state["fields"]["action"].get("value")):
            return event_type()
        fields = state["fields"]
        if fields["date"]["status"] == "missing" or fields["time"]["status"] == "missing":
            return missing("when", fields)
        if fields["date"]["status"] == "needs_confirm" or fields["time"]["status"] == "needs_confirm":
            return confirm_when(fields["date"].get("value") or "日期未有記錄", fields["time"].get("value") or "時間未有記錄")
        if fields["location"]["status"] == "missing":
            return missing("location", fields)
        if fields["location"]["status"] == "needs_confirm":
            return confirm_location(fields["location"].get("value") or "")
        for key in ("party", "action", "witness", "injury", "action_taken"):
            if fields[key]["status"] in {"missing", "needs_confirm"}:
                return missing(key, fields)
        for index, name in enumerate(state["names"]):
            if name["status"] == "pending":
                return confirm_name(name["value"], index)
            if name["status"] == "fixing":
                return fix_name(name["value"], index)
        for index, item in enumerate(state["suggestions"]):
            if item["status"] == "pending":
                return suggestion(item, index)
        for index, item in enumerate(state["subjective"]):
            if item["status"] == "pending":
                return subjective(item["word"], index)
        return None

    def _apply(self, state: dict, field: str, text: str, choice: str | None) -> bool:
        if field == "event_type":
            if choice == "out":
                state["event_type"] = "out_of_scope"
                return True
            if choice in {"facility_damage", "noise", "fall_injury"}:
                state["event_type"] = choice
                return True
            self._reask(state, "請用按鈕選擇事件類型。")
            return False
        if field == "when":
            if not self._apply_when(state, text, choice):
                self._reask(state, "未能讀出到分鐘的時間。請用 22:15 這種寫法。")
                return False
            return True
        if field == "when_confirm":
            return self._confirm_pair(state, ("date", "time"), choice)
        if field == "location_confirm":
            return self._confirm_pair(state, ("location",), choice)
        if field == "location":
            if choice == "unknown":
                self._set_unknown(state, "location")
                return True
            found = specific_location(text)
            if not found:
                self._reask(state, "地點仍不夠具體。要有座數或大廈、樓層、位置。")
                return False
            state["fields"]["location"] = {"value": found, "status": "confirmed", "origin": "manual"}
            return True
        if field.startswith("name_fix:"):
            index = int(field.split(":", 1)[1])
            name = state["names"][index]
            if choice == "unknown" or not text:
                self._replace_name(state, name["value"], "姓名未有記錄")
                name["value"] = "姓名未有記錄"
                name["status"] = "confirmed"
                return True
            if has_banned(text):
                self._reask(state, "姓名欄不能寫主觀描述。")
                return False
            self._replace_name(state, name["value"], text)
            name["value"] = text
            name["status"] = "confirmed"
            return True
        if field.startswith("name:"):
            index = int(field.split(":", 1)[1])
            if choice == "confirm":
                state["names"][index]["status"] = "confirmed"
                return True
            if choice == "reject":
                state["names"][index]["status"] = "fixing"
                return True
            self._reask(state, "請確認姓名是否正確。")
            return False
        if field.startswith("asr:"):
            index = int(field.split(":", 1)[1])
            item = state["suggestions"][index]
            if choice == "accept":
                self._accept_suggestion(state, item)
                return True
            if choice == "keep":
                item["status"] = "kept"
                return True
            self._reask(state, "請選擇採用熱詞或保持原話。")
            return False
        if field.startswith("subjective:"):
            index = int(field.split(":", 1)[1])
            item = state["subjective"][index]
            if choice == "omit" or choice == "unknown":
                item["status"] = "omitted"
                item["observed"] = None
                return True
            if not text:
                self._reask(state, "請描述看得到或聽得到的行為，或撳省略。")
                return False
            text = auto_rewrite(text)
            if has_banned(text):
                self._reask(state, "這句仍有主觀詞。請只講行為，或撳省略。")
                return False
            if mentions_drunk(text):
                text = rewrite_drunk(text) or text
            item["status"] = "resolved"
            item["observed"] = text
            current = state["fields"]["action"].get("value") or ""
            state["fields"]["action"]["value"] = f"{current}。可觀察行為：{text}" if current else text
            state["fields"]["action"]["status"] = "confirmed"
            state["fields"]["action"]["origin"] = "manual"
            return True
        if choice == "unknown":
            self._set_unknown(state, field)
            return True
        if choice in _FILL:
            key, value = _FILL[choice]
            if key != field:
                self._reask(state, "這個按鈕不屬於目前的問題。")
                return False
            state["fields"][key] = {"value": value, "status": "confirmed", "origin": "manual"}
            return True
        if not text:
            self._reask(state, "請打字補充，或撳按鈕。")
            return False
        text = auto_rewrite(text)
        if not text:
            self._reask(state, "這句是評價，已刪走。請改講看得到或聽得到的行為。")
            return False
        if has_banned(text):
            self._reask(state, "這句有主觀詞，不能寫進事實。請改講看得到或聽得到的行為。")
            return False
        if mentions_drunk(text):
            text = rewrite_drunk(text) or text
        state["fields"][field] = {"value": text, "status": "confirmed", "origin": "manual"}
        return True

    def _apply_when(self, state: dict, text: str | None, choice: str | None) -> bool:
        if choice == "unknown":
            for key in ("date", "time"):
                if state["fields"][key]["status"] != "confirmed":
                    self._set_unknown(state, key)
            return True
        parsed = extract(text or "", today=self.today)
        for key in ("date", "time"):
            got = parsed["fields"][key]
            if got["status"] == "confirmed" and got.get("value"):
                state["fields"][key] = {**got, "origin": "manual", "status": "confirmed"}
        date_ok = state["fields"]["date"]["status"] in {"confirmed", "unknown"}
        time_ok = state["fields"]["time"]["status"] in {"confirmed", "unknown"}
        return date_ok and time_ok

    def _confirm_pair(self, state: dict, keys: tuple[str, ...], choice: str | None) -> bool:
        if choice == "confirm":
            for key in keys:
                if state["fields"][key].get("value"):
                    state["fields"][key]["status"] = "confirmed"
                    state["fields"][key]["origin"] = "manual"
            return True
        if choice == "reject":
            for key in keys:
                if state["fields"][key]["status"] == "needs_confirm":
                    state["fields"][key] = {"value": None, "status": "missing", "origin": "manual"}
            return True
        self._reask(state, "請選擇正確或不正確。")
        return False

    def _accept_suggestion(self, state: dict, item: dict) -> None:
        heard, suggested = item["heard"], item["suggestion"]
        state["transcript"] = state["transcript"].replace(heard, suggested, 1)
        for field in state["fields"].values():
            if field.get("value") and heard in field["value"]:
                field["value"] = field["value"].replace(heard, suggested, 1)
        location = state["fields"]["location"]
        if item["kind"] == "place" and location.get("value") and suggested not in location["value"]:
            location["value"] = suggested + location["value"]
        item["status"] = "accepted"

    def _replace_name(self, state: dict, old: str, new: str) -> None:
        if not old or old == new:
            return
        for field in state["fields"].values():
            if field.get("value") and old in field["value"]:
                field["value"] = field["value"].replace(old, new)

    def _set_unknown(self, state: dict, key: str) -> None:
        state["fields"][key] = {"value": UNKNOWN, "status": "unknown", "origin": "manual"}

    def _reask(self, state: dict, note: str) -> None:
        question = dict(state["question"])
        question["text"] = note + question["text"]
        state["question"] = question
        state["message"] = note

    def _correction_changes(self, state: dict, utterance: str) -> list[tuple[str, str, str]]:
        changes: list[tuple[str, str, str]] = []
        clock = re.search(r"時間改為\s*(\d{1,2})[:：](\d{2})", utterance)
        if clock:
            hour, minute = int(clock.group(1)), int(clock.group(2))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise CaseError(400, "時間不在 00:00 至 23:59。")
            new = f"{hour:02d}:{minute:02d}"
            old = state["fields"]["time"].get("value")
            state["fields"]["time"] = {"value": new, "status": "confirmed", "origin": "correction"}
            changes.append(("time", old or "", new))
        day = re.search(r"日期改為\s*(\d{4})年(\d{1,2})月(\d{1,2})日", utterance)
        if day:
            new = f"{int(day.group(1)):04d}年{int(day.group(2)):02d}月{int(day.group(3)):02d}日"
            old = state["fields"]["date"].get("value")
            state["fields"]["date"] = {"value": new, "status": "confirmed", "origin": "correction"}
            changes.append(("date", old or "", new))
        place = re.search(r"地點改為\s*([^。；\n]+)", utterance)
        if place:
            new = specific_location(place.group(1)) or place.group(1).strip()
            old = state["fields"]["location"].get("value")
            state["fields"]["location"] = {"value": new, "status": "confirmed", "origin": "correction"}
            changes.append(("location", old or "", new))
        injury = re.search(r"傷勢改為\s*([^。；\n]+)", utterance)
        if injury:
            new = injury.group(1).strip()
            old = state["fields"]["injury"].get("value")
            state["fields"]["injury"] = {"value": new, "status": "confirmed", "origin": "correction"}
            changes.append(("injury", old or "", new))
        supplement = re.search(r"補充[:：]\s*(.+)", utterance, re.S)
        extra = supplement.group(1).strip("。 \n") if supplement else ""
        if not changes and not extra:
            extra = utterance
        if extra:
            old = state["fields"]["action"].get("value") or ""
            new = f"{old}。追加：{extra}" if old else extra
            state["fields"]["action"]["value"] = new
            state["fields"]["action"]["status"] = "confirmed"
            state["fields"]["action"]["origin"] = "correction"
            changes.append(("action", old, new))
        return changes

    def _scrub(self, extracted: dict) -> None:
        for field in extracted["fields"].values():
            value = field.get("value")
            if not value or not has_banned(value):
                continue
            kept = [clause for clause in split_clauses(value) if not has_banned(clause)]
            field["value"] = "，".join(kept) if kept else None
            if not field["value"]:
                field["status"] = "missing"
