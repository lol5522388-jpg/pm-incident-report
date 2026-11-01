"""送出草稿。電郵在未設定 SMTP 時只寫入 outbox。列印只排隊，不接觸打印機。"""

from __future__ import annotations

import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.hotwords import ROOT
from app.pdf import render_pdf

_OUTBOX = ROOT / "data" / "outbox"
_PRINTS = ROOT / "data" / "print_queue"
_PDFS = ROOT / "data" / "pdf"


def deliver(state: dict, channel: str, to: str | None = None, folder: Path | None = None) -> dict:
    report = state["report"]
    pdf_bytes, engine, document = render_pdf(
        formal=report["formal"],
        summary=report["summary"],
        transcript=state["transcript"],
    )
    base = folder or ROOT / "data"
    pdf_dir = base / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{state['id']}-v{report['version']}"
    pdf_path = pdf_dir / f"{stem}.pdf"
    html_path = pdf_dir / f"{stem}.html"
    pdf_path.write_bytes(pdf_bytes)
    html_path.write_text(document, encoding="utf-8")
    result = {
        "case_id": state["id"],
        "version": report["version"],
        "pdf": str(pdf_path),
        "html": str(html_path),
        "pdf_engine": engine,
        "channels": [],
    }
    if channel in {"email", "both"}:
        result["channels"].append(_email(state, pdf_bytes, stem, to, base / "outbox"))
    if channel in {"print", "both"}:
        result["channels"].append(_print_job(state, pdf_path, base / "print_queue"))
    if channel == "whatsapp":
        result["channels"].append(_whatsapp(state, pdf_bytes, stem, to))
    if channel not in {"email", "print", "both", "whatsapp"}:
        raise ValueError("channel 必須是 email、print、both 或 whatsapp。")
    return result


def _email(state: dict, pdf_bytes: bytes, stem: str, to: str | None, outbox: Path) -> dict:
    recipient = to or os.environ.get("SUPERVISOR_EMAIL", "supervisor@localhost")
    sender = os.environ.get("SMTP_FROM", "reports@localhost")
    message = EmailMessage()
    message["Subject"] = f"事件報告草稿 {state['id']} v{state['report']['version']}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "附件是事件報告草稿，須由保安或主管確認簽署。系統不提供法律意見。\n\n"
        + state["report"]["summary"]
    )
    message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"{stem}.pdf")
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{stem}.eml"
        path.write_bytes(message.as_bytes())
        return {"channel": "email", "status": "queued_dry_run", "to": recipient, "path": str(path)}
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if os.environ.get("SMTP_TLS", "1") != "0":
            smtp.starttls()
        user = os.environ.get("SMTP_USER", "").strip()
        if user:
            smtp.login(user, os.environ.get("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return {"channel": "email", "status": "sent", "to": recipient}


def _whatsapp_digits(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 8:
        return "852" + digits
    return digits


def _whatsapp(state: dict, pdf_bytes: bytes, stem: str, to: str | None) -> dict:
    from app.whatsapp import document_payload, send, upload_pdf

    recipient = _whatsapp_digits(to)
    if not recipient:
        return {"channel": "whatsapp", "status": "error", "reason": "請填已加入測試名單的 WhatsApp 號碼。"}
    version = state["report"]["version"]
    note = send(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": f"事件報告草稿 v{version}。要保安或主管確認。系統不提供法律意見。\n\n" + state["report"]["summary"],
            },
        }
    )
    document = None
    try:
        media_id = upload_pdf(pdf_bytes, f"{stem}.pdf")
    except Exception as exc:
        media_id = None
        document = {"status": "error", "reason": str(exc)}
    if media_id:
        document = send(document_payload(recipient, media_id, f"事件報告-{stem}.pdf"))
    status = "sent" if note.get("status") == "sent" else note.get("status") or "error"
    return {
        "channel": "whatsapp",
        "status": status,
        "to": recipient,
        "from": "+1 555-203-0310",
        "text": note,
        "document": document,
    }


def _print_job(state: dict, pdf_path: Path, queue: Path) -> dict:
    queue.mkdir(parents=True, exist_ok=True)
    printer = os.environ.get("PRINTER_NAME", "").strip() or "unset"
    job = {
        "case_id": state["id"],
        "version": state["report"]["version"],
        "printer": printer,
        "pdf": str(pdf_path),
        "note": "由後台電腦連接網絡打印機列印。WhatsApp 不直接控制硬件。",
    }
    path = queue / f"{state['id']}-v{state['report']['version']}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"channel": "print", "status": "queued", "printer": printer, "path": str(path)}
