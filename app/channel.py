"""保安在 WhatsApp 裡的一輪對話。網頁版同真號碼用同一套。"""

from __future__ import annotations

import re
from pathlib import Path

from app.asr import build_asr
from app.pdf import render_pdf
from app.pipeline import CaseError, Pipeline
from app.whatsapp import (
    INTRO,
    chat_bubbles,
    document_payload,
    download_media,
    message_text,
    outbound_payload,
    send_all,
    upload_pdf,
)

_GREETING = re.compile(r"^(你好|哈囉|哈啰|hello|hi|開始|有冇人)[!！。.\s]*$", re.I)


def converse(pipeline: Pipeline, message: dict, *, notify: bool = True) -> dict:
    phone = str(message.get("from") or "local")
    prepared = _normalize(message)
    if prepared.get("kind") == "audio":
        return _from_audio(pipeline, phone, prepared, notify=notify)
    if _GREETING.match((prepared.get("text") or "").strip()):
        existing = pipeline.store.latest_phone(phone)
        if not (existing and existing["status"] == "collecting"):
            return _pack(pipeline, phone, pipeline._idle(INTRO), None, notify=notify)
    try:
        if prepared.get("kind") == "interactive":
            view = pipeline.receive_button(prepared.get("case_id") or "", prepared.get("field") or "", prepared.get("choice") or "")
        else:
            view = pipeline.receive_phone(phone, prepared.get("text") or "", source=prepared.get("source") or "text")
    except CaseError as exc:
        view = pipeline._idle(exc.message)
    document = _pdf(pipeline, view)
    return _pack(pipeline, phone, view, document, notify=notify)


def _from_audio(pipeline: Pipeline, phone: str, message: dict, *, notify: bool = True) -> dict:
    text, note = _transcript(message)
    if not text:
        existing = pipeline.store.latest_phone(phone)
        if existing and existing["status"] == "collecting" and existing.get("question"):
            pending = pipeline.public(existing)
            note = note + "\n\n而家呢條仲未答：\n" + pending["question"]["text"]
        view = pipeline._idle(note)
        return _pack(pipeline, phone, view, None, notify=notify)
    try:
        view = pipeline.receive_phone(phone, text, source="asr")
    except CaseError as exc:
        view = pipeline._idle(exc.message)
    return _pack(pipeline, phone, view, _pdf(pipeline, view), notify=notify)


def _transcript(message: dict) -> tuple[str | None, str]:
    audio = message.get("audio_bytes")
    if audio is None and message.get("media_id"):
        try:
            audio = download_media(message["media_id"])
        except Exception:
            audio = None
    if not audio:
        return None, "收到你條語音。我而家攞唔到段錄音。請打字講一次。"
    engine = build_asr()
    if engine is None:
        return None, (
            "收到你條語音。轉寫機未開，我唔會亂估你講過咩。"
            "請打字再講一次。主管開咗 Qwen3-ASR 之後，呢度的語音會直接變文字。"
        )
    try:
        result = engine.transcribe(audio, message.get("filename") or "voice.ogg")
    except Exception as exc:
        return None, f"段語音轉寫失敗。請打字講一次。（{exc}）"
    text = (result.get("text") or "").strip()
    if not text:
        return None, "段語音轉寫之後係空白。請再講一次，或者打字。"
    return text, ""


def _pdf(pipeline: Pipeline, view: dict) -> dict | None:
    if view.get("status") != "ready" or not view.get("case_id") or not view.get("report"):
        return None
    state = pipeline.require_ready(view["case_id"])
    pdf_bytes, _engine, _html = render_pdf(
        formal=state["report"]["formal"],
        summary=state["report"]["summary"],
        transcript=state.get("transcript") or "",
    )
    folder = Path(pipeline.store.path).parent / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    version = view["report"]["version"]
    filename = f"事件報告-{view['case_id']}-v{version}.pdf"
    path = folder / f"{view['case_id']}-v{version}.pdf"
    path.write_bytes(pdf_bytes)
    return {"filename": filename, "href": f"/v1/cases/{view['case_id']}/report.pdf", "bytes": pdf_bytes}


def _pack(pipeline: Pipeline, phone: str, view: dict, document: dict | None, *, notify: bool = True) -> dict:
    del pipeline
    bubbles = chat_bubbles(view, document)
    payloads = [outbound_payload(phone, view)]
    media_id = None
    if notify and document and document.get("bytes"):
        try:
            media_id = upload_pdf(document["bytes"], document["filename"])
        except Exception:
            media_id = None
        if media_id:
            payloads.append(document_payload(phone, media_id, document["filename"]))
    sent = send_all(payloads) if notify else []
    safe_document = None
    if document:
        safe_document = {"filename": document["filename"], "href": document["href"]}
    return {
        "status": "ok",
        "view": view,
        "bubbles": bubbles,
        "document": safe_document,
        "outbound": {"payload": payloads[0], "payloads": payloads, "sent": sent},
        "reply": message_text(view),
    }


def _normalize(message: dict) -> dict:
    choice_id = message.get("choice_id") or ""
    if choice_id:
        case_id, field, choice = _split(choice_id)
        return {
            "from": message.get("from"),
            "kind": "interactive",
            "case_id": case_id,
            "field": field,
            "choice": choice,
            "text": message.get("text") or "",
        }
    if message.get("kind") == "interactive":
        case_id, field, choice = message.get("case_id"), message.get("field"), message.get("choice")
        if not case_id and message.get("id"):
            case_id, field, choice = _split(message["id"])
        return {**message, "case_id": case_id, "field": field, "choice": choice}
    kind = message.get("kind") or "text"
    return {**message, "kind": kind, "source": "asr" if kind == "audio" else message.get("source") or "text"}


def _split(value: str) -> tuple[str, str, str]:
    parts = value.split("|", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]

