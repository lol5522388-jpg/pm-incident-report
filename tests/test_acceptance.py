import json
import os
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.asr import review_transcript
from app.extract import extract
from app.fixtures import (
    ELEVATOR,
    FALL_COMPLETE,
    FALL_SUBJECTIVE,
    LEAK_COMPLETE,
    LEAK_INCOMPLETE,
    NOISE_COMPLETE,
    NOISE_INCOMPLETE,
    PARKING,
)
from app.gates import merge_llm
from app.pipeline import CaseError, Pipeline
from app.prompt import SYSTEM_PROMPT
from app.store import Store

FACT = re.compile(r"^• .+")
STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(
        Store(tmp_path / "cases.db"),
        today=date(2026, 10, 22),
        now=STAMP,
        engine="heuristic",
    )


def facts(formal: str) -> list[str]:
    return [line for line in formal.splitlines() if FACT.match(line) or line.startswith("• ")]


def points(summary: str) -> list[str]:
    numbered = [line for line in summary.splitlines() if re.match(r"^\d+\. ", line)]
    if numbered:
        return numbered
    return [line for line in summary.splitlines() if line.startswith("• ")]


def test_prompt_locks_the_three_rules():
    assert "純客觀" in SYSTEM_PROMPT
    assert "零幻覺" in SYSTEM_PROMPT
    assert "未有記錄" in SYSTEM_PROMPT
    assert "不提供法律意見" in SYSTEM_PROMPT


def test_evening_cantonese_time_and_vague_time():
    exact = extract("晚上十點十五分，A座3樓走廊有人唱歌。", today=date(2026, 10, 22))
    vague = extract("晚上十點幾，A座3樓走廊有人唱歌。", today=date(2026, 10, 22))
    assert exact["fields"]["time"] == {"value": "22:15", "status": "confirmed", "origin": "auto"}
    assert vague["fields"]["time"]["status"] == "needs_confirm"
    assert vague["fields"]["time"]["value"].startswith("約 ")


def test_leak_incomplete_asks_time_and_refuses_skip(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(LEAK_INCOMPLETE)
    assert view["status"] == "collecting"
    assert view["event_type"] == "facility_damage"
    assert view["report"] is None
    assert view["question"]["field"] == "when"
    with pytest.raises(CaseError) as caught:
        pipe.answer(view["case_id"], field="injury", choice="none_injury")
    assert caught.value.status == 409


def test_leak_complete_confirms_name_then_writes_two_versions(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(LEAK_COMPLETE)
    assert view["question"]["field"] == "name:0"
    assert "「陳Sir」" in view["question"]["text"]
    view = pipe.answer(view["case_id"], field="name:0", choice="confirm")
    assert view["status"] == "ready"
    formal = view["report"]["formal"]
    assert "（1）嚴謹版" in formal
    assert "目擊事實：" in formal
    assert facts(formal) or "22:15" in formal
    assert "22:15" in formal
    assert "海晴閣" in formal
    assert "後樓梯" in formal
    assert "陳Sir" in formal
    assert "不提供法律意見" not in formal
    assert "大廈公契" not in formal
    assert "來源聲明" not in formal
    assert formal.count("僅根據提供資料客觀轉寫，不含推測。") == 1
    assert len(points(view["report"]["summary"])) <= 5
    assert "可疑" not in formal


def test_drunk_phrase_enters_formal_report_and_attitude_does_not(tmp_path):
    pipe = make_pipe(tmp_path)
    elevator = pipe.ingest(ELEVATOR)
    assert elevator["status"] == "ready"
    assert "疑似醉酒" not in elevator["report"]["formal"]
    assert "電梯門無法打開" in elevator["report"]["formal"]
    view = pipe.ingest("昨晚大概10點幾，A座後樓梯有個醉漢搞事，推倒椅子，態度很差")
    answers = {
        "when": {"text": "2026-10-22 22:15"},
        "location": {"text": "A座3樓後樓梯"},
        "party": {"text": "一名疑似醉酒之男子"},
        "action": {"text": "推倒椅子"},
        "witness": {"choice": "unknown"},
        "injury": {"choice": "none_injury"},
        "action_taken": {"choice": "none_action"},
    }
    for _ in range(12):
        if view["status"] != "collecting":
            break
        field = view["question"]["field"]
        assert field in answers, view["question"]
        assert not field.startswith("subjective"), view["question"]
        view = pipe.answer(view["case_id"], field=field, **answers[field])
    formal = view["report"]["formal"]
    assert view["status"] == "ready", view.get("question")
    assert "疑似醉酒之男子" in formal
    assert "推倒椅子" in formal
    assert "醉漢" not in formal
    assert "搞事" not in formal
    assert "態度很差" not in formal
    assert "態度很差" not in view["report"]["summary"]
    assert "未有行動記錄" in formal


def test_subjective_words_never_enter_the_facts(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(FALL_SUBJECTIVE)
    assert view["question"]["field"] == "injury"
    view = pipe.answer(view["case_id"], field="injury", text="右膝有血，人仍然清醒")
    formal = view["report"]["formal"]
    summary = view["report"]["summary"]
    assert view["status"] == "ready"
    assert view["question"] is None
    assert "態度好差" not in formal
    assert "態度好差" not in summary
    assert "構成犯罪" not in formal
    assert "態度好差" in view["transcript"]


def test_complete_fall_and_noise_reports(tmp_path):
    pipe = make_pipe(tmp_path)
    fall = pipe.ingest(FALL_COMPLETE)
    assert fall["status"] == "ready"
    assert fall["event_type"] == "fall_injury"
    assert "第314章" not in fall["report"]["formal"]
    assert "右膝有血" in fall["report"]["formal"]
    assert "15:40" in fall["report"]["formal"]
    assert len(points(fall["report"]["summary"])) <= 5
    noise = pipe.ingest(NOISE_COMPLETE)
    assert noise["status"] == "ready"
    assert noise["event_type"] == "noise"
    assert "第400章" not in noise["report"]["formal"]
    assert "22:05" in noise["report"]["formal"]
    assert "1203" in noise["report"]["formal"]
    assert "（1）嚴謹版" in noise["report"]["formal"]
    assert "22:05" in noise["report"]["formal"]


def test_noise_gap_loop_strips_subjective_words(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(NOISE_INCOMPLETE)
    answers = {
        "when": {"text": "2026-10-22 22:10"},
        "location": {"text": "C座12樓走廊"},
        "party": {"text": "一名穿黑色上衣的短髮男子"},
        "action": {"text": "打開單位門大聲唱歌"},
        "witness": {"text": "我在12樓走廊聽到歌聲"},
        "injury": {"choice": "none_injury"},
        "action_taken": {"text": "我已到場勸喻並通知主管"},
        "subjective:0": {"choice": "omit"},
        "subjective:1": {"choice": "omit"},
    }
    for _ in range(12):
        if view["status"] != "collecting":
            break
        field = view["question"]["field"]
        assert field in answers, view["question"]
        view = pipe.answer(view["case_id"], field=field, **answers[field])
    assert view["status"] == "ready"
    assert "搞事" not in view["report"]["formal"]
    assert "態度惡劣" not in view["report"]["formal"]
    assert "22:10" in view["report"]["formal"]
    assert "唱歌" in view["report"]["formal"]


def test_parking_does_not_produce_a_formal_report(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(PARKING)
    assert view["status"] == "out_of_scope"
    assert view["event_type"] == "parking"
    assert view["report"] is None
    assert "不會出嚴謹版" in view["message"]
    assert "法律結論" in view["message"]


def test_correction_keeps_old_version_and_only_changes_requested_fields(tmp_path):
    pipe = make_pipe(tmp_path)
    view = pipe.ingest(ELEVATOR)
    assert view["status"] == "ready"
    assert view["version"] == 1
    before = view["versions"][0]["formal"]
    assert "09:05" in before
    view = pipe.correct(view["case_id"], "時間改為09:12。補充：按鈕燈為紅色。")
    assert view["version"] == 2
    after = view["report"]["formal"]
    assert "09:12" in after
    assert "09:05" not in after
    assert "電梯大堂" in after
    assert "按鈕燈為紅色" in after
    assert "09:05" in view["versions"][0]["formal"]
    assert view["audit"][0]["old"] == "09:05"
    assert view["audit"][0]["new"] == "09:12"
    rejected = pipe.correct(view["case_id"], "補充：對方態度惡劣。")
    assert rejected["version"] == 2
    assert "態度惡劣" not in rejected["report"]["formal"]
    assert rejected["question"]["field"] == "correction"


def test_new_incident_does_not_rewrite_the_finished_report(tmp_path):
    pipe = make_pipe(tmp_path)
    first = pipe.ingest(ELEVATOR, phone="85290000000")
    assert first["status"] == "ready"
    paused = pipe.receive_phone("85290000000", "新事件")
    assert paused["status"] == "idle"
    nxt = pipe.receive_phone("85290000000", LEAK_INCOMPLETE)
    assert nxt["case_id"] != first["case_id"]
    assert nxt["event_type"] == "facility_damage"
    assert nxt["status"] == "collecting"


def test_asr_flags_time_place_and_does_not_rewrite_until_confirmed(tmp_path):
    pipe = make_pipe(tmp_path)
    text = (
        "今日15:40，海情閣B座地下大堂近電梯門，一名穿白色上衣黑色長褲、短髮男子行過時向前跌倒，右膝有血。"
        "我喺大堂接待處見到全程。沒有人受傷。我已經通知主管。"
    )
    view = pipe.ingest(text, source="asr")
    assert view["question"]["field"] == "when_confirm"
    assert "海情閣" in view["transcript"]
    assert "海晴閣" not in view["transcript"]
    view = pipe.answer(view["case_id"], field="when_confirm", choice="confirm")
    assert view["question"]["field"] == "location_confirm"
    view = pipe.answer(view["case_id"], field="location_confirm", choice="confirm")
    assert view["question"]["field"] == "asr:0"
    assert "海晴閣" in view["question"]["text"]
    view = pipe.answer(view["case_id"], field="asr:0", choice="accept")
    assert view["status"] == "ready"
    assert "海晴閣" in view["transcript"]
    assert "海晴閣" in view["report"]["formal"]
    assert "海情閣" not in view["report"]["formal"]


def test_llm_hallucination_is_dropped():
    text = "今日15:40，B座地下大堂近電梯門，一名穿白衫男子向前跌倒。我見到全程。我已經通知主管。"
    heuristic = extract(text, today=date(2026, 10, 22))
    merged = merge_llm(heuristic, {"injury": "右腿骨折並已送院", "event_type": "noise"}, text)
    assert merged["fields"]["injury"]["status"] == "missing"
    assert merged["event_type"] == "fall_injury"


def test_near_homophone_suggestion_is_not_automatic():
    suggestions = review_transcript("海情閣後樓梯漏水")
    assert suggestions
    assert suggestions[0]["suggestion"] == "海晴閣"
    assert suggestions[0]["auto_apply"] is False


def test_api_deliver_and_whatsapp_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_DEV_ALLOW", "1")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ASR_BASE_URL", raising=False)
    monkeypatch.delenv("ASR_INPROCESS", raising=False)
    app = create_app(db_path=tmp_path / "api.db", today=date(2026, 10, 22), now=STAMP, engine="heuristic")
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200

    created = client.post("/v1/cases", json={"text": ELEVATOR, "source": "text"})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "ready"
    blocked = client.post("/v1/cases", json={"text": LEAK_INCOMPLETE})
    denied = client.post(
        f"/v1/cases/{blocked.json()['case_id']}/deliver",
        json={"channel": "both"},
    )
    assert denied.status_code == 409

    sent = client.post(f"/v1/cases/{body['case_id']}/deliver", json={"channel": "both", "to": "boss@example.com"})
    assert sent.status_code == 200
    payload = sent.json()
    assert payload["pdf_engine"] in {"fpdf2", "weasyprint"}
    assert open(payload["pdf"], "rb").read().startswith(b"%PDF")
    html = open(payload["html"], encoding="utf-8").read()
    assert "僅根據提供資料客觀轉寫，不含推測" in html
    assert "【物管事件報告" in html
    assert "原始口述" not in html
    assert "大廈公契" not in html
    channels = {item["channel"]: item for item in payload["channels"]}
    assert channels["email"]["status"] == "queued_dry_run"
    assert channels["print"]["status"] == "queued"
    assert "不直接控制硬件" in json.loads(open(channels["print"]["path"], encoding="utf-8").read())["note"]

    challenge = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "abc"})
    assert challenge.status_code == 200
    assert challenge.text == "abc"

    first = client.post(
        "/webhook/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": "85290000000", "id": "wamid.1", "type": "text", "text": {"body": LEAK_INCOMPLETE}}
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    assert first.status_code == 200
    outbound = first.json()["results"][0]["outbound"]["payload"]
    assert outbound["type"] == "interactive"
    assert "時間" in outbound["interactive"]["body"]["text"]
    button_id = outbound["interactive"]["action"]["buttons"][0]["reply"]["id"]
    case_id, field, choice = button_id.split("|")
    assert field == "when"
    assert choice == "unknown"

    audio = client.post(
        "/webhook/whatsapp",
        json={"entry": [{"changes": [{"value": {"messages": [{"from": "85290000000", "id": "wamid.2", "type": "audio", "audio": {"id": "media-1"}}]}}]}]},
    )
    spoken = audio.json()["results"][0]
    assert spoken["outbound"]["payload"]["type"] == "text"
    assert "語音" in spoken["outbound"]["payload"]["text"]["body"]

    button = client.post(
        "/webhook/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "85290000000",
                                        "id": "wamid.3",
                                        "type": "interactive",
                                        "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "未能確定"}},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    nxt = button.json()["results"][0]["outbound"]["payload"]
    assert nxt["type"] == "interactive"
    assert "當事人" in nxt["interactive"]["body"]["text"] or "看到的人" in nxt["interactive"]["body"]["text"]

    chat = client.post("/v1/wa/turn", json={"phone": "85292222222", "text": ELEVATOR})
    assert chat.status_code == 200
    bubbles = chat.json()["bubbles"]
    assert any("摘要" in item["text"] for item in bubbles)
    assert any(item.get("document") for item in bubbles)
    pdf_href = next(item["document"]["href"] for item in bubbles if item.get("document"))
    pdf = client.get(pdf_href)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    page = client.get("/wa")
    assert page.status_code == 200
    assert "WhatsApp" in page.text

    asr = client.post("/v1/asr", files={"file": ("clip.wav", b"not-audio", "audio/wav")})
    assert asr.status_code == 503

    monkeypatch.setenv("WHATSAPP_APP_SECRET", "topsecret")
    raw = b'{"entry":[]}'
    rejected = client.post("/webhook/whatsapp", content=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=dead"})
    assert rejected.status_code == 403
    os.environ.pop("WHATSAPP_APP_SECRET", None)
