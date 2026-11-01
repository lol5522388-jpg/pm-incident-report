"""WhatsApp Business Cloud API 的收發形狀。

未設定 token 時只組好 payload，不呼叫 Graph。語音檔下載亦要 token，
所以語音正式接入放在 ASR_BASE_URL 與 WHATSAPP_TOKEN 都齊之後。
"""

from __future__ import annotations

import hashlib
import hmac
import os

import httpx


def verify_signature(raw: bytes, header: str, secret: str) -> bool:
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, header or "")


def parse_inbound(payload: dict) -> list[dict]:
    messages = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for item in value.get("messages") or []:
                kind = item.get("type")
                base = {
                    "from": item.get("from"),
                    "message_id": item.get("id"),
                    "kind": kind,
                }
                if kind == "text":
                    base["text"] = ((item.get("text") or {}).get("body") or "").strip()
                    messages.append(base)
                elif kind == "interactive":
                    interactive = item.get("interactive") or {}
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    case_id, field, choice = _split_id(reply.get("id") or "")
                    base.update({"case_id": case_id, "field": field, "choice": choice, "text": reply.get("title") or ""})
                    messages.append(base)
                elif kind == "audio":
                    base["media_id"] = (item.get("audio") or {}).get("id")
                    messages.append(base)
    return messages


def _split_id(value: str) -> tuple[str, str, str]:
    parts = value.split("|", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]


INTRO = (
    "我係事件報告草稿。你而家喺 WhatsApp 直接講就得，語音或者打字都得。\n"
    "漏咗時間、地點、邊個、做過咩、你見到幾多、有冇人受傷、你做咗咩，我會逐樣問。\n"
    "稿要你或者主管確認先算數。我唔提供法律意見。\n"
    "開新一單就打「新事件」。"
)


def message_text(view: dict) -> str:
    question = view.get("question")
    if question:
        return ("收到。我只記你講到嘅嘢，唔會自己加。\n\n" + question["text"])[:1024]
    if view.get("status") == "ready" and view.get("report"):
        version = view["report"]["version"]
        return (
            f"稿做好咗，v{version}。你而家睇。唔啱就直接再講，例如：時間改為22:20。補充：水每秒滴一下。\n"
            "開新一單就打「新事件」。\n"
            "呢份要你或者主管確認先算數。我唔提供法律意見。\n\n"
            + view["report"]["summary"]
        )[:4096]
    return (view.get("message") or "已收到。")[:4096]


def chat_bubbles(view: dict, document: dict | None = None) -> list[dict]:
    question = view.get("question")
    if question:
        buttons = [
            {
                "title": button["title"],
                "id": f"{view.get('case_id') or ''}|{question['field']}|{button['id']}",
            }
            for button in question["buttons"]
        ]
        return [{"text": message_text(view), "buttons": buttons}]
    bubbles = [{"text": message_text(view), "buttons": []}]
    if document:
        bubbles.append(
            {
                "text": "PDF 草稿喺下面，可以開或者轉發俾主管。",
                "buttons": [],
                "document": {"filename": document["filename"], "href": document["href"]},
            }
        )
    return bubbles


def outbound_payload(to: str, view: dict) -> dict:
    text = message_text(view)
    question = view.get("question")
    if not question:
        return _text_payload(to, text)
    buttons = question["buttons"]
    if len(buttons) <= 3:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"{view.get('case_id') or ''}|{question['field']}|{button['id']}",
                                "title": button["title"][:20],
                            },
                        }
                        for button in buttons
                    ]
                },
            },
        }
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "選擇",
                "sections": [
                    {
                        "title": "請選",
                        "rows": [
                            {
                                "id": f"{view.get('case_id') or ''}|{question['field']}|{button['id']}",
                                "title": button["title"][:24],
                            }
                            for button in buttons
                        ],
                    }
                ],
            },
        },
    }


def document_payload(to: str, media_id: str, filename: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": "事件報告草稿。要保安或主管確認。唔係法律意見。"},
    }


def _text_payload(to: str, text: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }


def _credentials() -> tuple[str, str]:
    return os.environ.get("WHATSAPP_TOKEN", "").strip(), os.environ.get("WHATSAPP_PHONE_ID", "").strip()


def send(payload: dict) -> dict:
    token, phone_id = _credentials()
    if not token or not phone_id:
        return {"status": "not_sent", "reason": "未設定 WHATSAPP_TOKEN / WHATSAPP_PHONE_ID", "payload": payload}
    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    try:
        response = httpx.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        detail = str(exc)
        response = getattr(exc, "response", None)
        if response is not None:
            detail = (response.text or detail)[:500]
        return {"status": "error", "reason": detail, "payload": payload}
    return {"status": "sent", "body": response.json(), "payload": payload}


def send_all(payloads: list[dict]) -> list[dict]:
    return [send(payload) for payload in payloads]


def download_media(media_id: str) -> bytes | None:
    token, _phone_id = _credentials()
    if not token or not media_id:
        return None
    meta = httpx.get(
        f"https://graph.facebook.com/v21.0/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    meta.raise_for_status()
    url = meta.json().get("url")
    if not url:
        return None
    audio = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    audio.raise_for_status()
    return audio.content


def upload_pdf(pdf_bytes: bytes, filename: str) -> str | None:
    token, phone_id = _credentials()
    if not token or not phone_id:
        return None
    response = httpx.post(
        f"https://graph.facebook.com/v21.0/{phone_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("id")
