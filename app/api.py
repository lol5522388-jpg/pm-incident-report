"""FastAPI。文字案件是主路徑；WhatsApp webhook 接到同一條狀態機。"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.asr import build_asr
from app.channel import _pdf, converse
from app.deliver import deliver
from app.hotwords import ROOT
from app.pipeline import CaseError, Pipeline
from app.store import Store
from app.voice_flow import desk, hear
from app.whatsapp import parse_inbound, verify_signature

_WEB = Path(__file__).with_name("web")


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class IngestBody(BaseModel):
    text: str
    source: str = "text"
    phone: str | None = None


class AnswerBody(BaseModel):
    field: str
    text: str | None = None
    choice: str | None = None


class CorrectBody(BaseModel):
    text: str


class DeliverBody(BaseModel):
    channel: str = Field(pattern="^(email|print|both|whatsapp)$")
    to: str | None = None


def create_app(
    db_path: str | Path | None = None,
    today: date | None = None,
    now: datetime | None = None,
    engine: str | None = None,
) -> FastAPI:
    resolved = engine or ("llm" if os.environ.get("LLM_PROVIDER") else "heuristic")
    path = Path(db_path) if db_path else ROOT / "data" / "guard.db"
    pipeline = Pipeline(Store(path), today=today, now=now, engine=resolved)
    app = FastAPI(title="物管防禦性事件報告", version="0.1.0", default_response_class=_UTF8)
    app.state.pipeline = pipeline

    @app.exception_handler(CaseError)
    async def _case_error(_request: Request, exc: CaseError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "version": "0.1.0",
            "engine": resolved,
            "whatsapp": bool(os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID")),
            "asr": build_asr() is not None,
        }

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((_WEB / "index.html").read_text(encoding="utf-8"))

    @app.get("/wa", response_class=HTMLResponse)
    def whatsapp_desk():
        return HTMLResponse((_WEB / "wa.html").read_text(encoding="utf-8"))

    @app.get("/try", response_class=HTMLResponse)
    def try_page():
        return HTMLResponse((_WEB / "try.html").read_text(encoding="utf-8"))

    @app.get("/desk", response_class=HTMLResponse)
    def desk_page():
        return HTMLResponse((_WEB / "desk.html").read_text(encoding="utf-8"))

    @app.post("/v1/voice/hear")
    def voice_hear(body: IngestBody):
        return hear(pipeline, body.phone or "sim", body.text)

    @app.get("/v1/voice/desk")
    def voice_desk(phone: str = "sim"):
        return desk(pipeline, phone)

    @app.get("/v1/voice/cases/{case_id}/sheet")
    def voice_sheet(case_id: str):
        path = Path(pipeline.store.path).parent / "pdf" / f"{case_id}-sheet.html"
        if not path.exists():
            raise HTTPException(status_code=404, detail="未有草稿")
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @app.post("/v1/cases")
    def create_case(body: IngestBody):
        return pipeline.ingest(body.text, source=body.source, phone=body.phone)

    @app.get("/v1/cases/{case_id}")
    def read_case(case_id: str):
        return pipeline.get(case_id)

    @app.post("/v1/cases/{case_id}/answers")
    def answer_case(case_id: str, body: AnswerBody):
        return pipeline.answer(case_id, field=body.field, text=body.text, choice=body.choice)

    @app.post("/v1/cases/{case_id}/corrections")
    def correct_case(case_id: str, body: CorrectBody):
        return pipeline.correct(case_id, body.text)

    @app.post("/v1/cases/{case_id}/deliver")
    def deliver_case(case_id: str, body: DeliverBody):
        state = pipeline.require_ready(case_id)
        return deliver(state, body.channel, to=body.to, folder=Path(pipeline.store.path).parent)

    @app.get("/v1/cases/{case_id}/report.pdf")
    def report_pdf(case_id: str):
        state = pipeline.require_ready(case_id)
        version = state["report"]["version"]
        path = Path(pipeline.store.path).parent / "pdf" / f"{case_id}-v{version}.pdf"
        if not path.exists():
            _pdf(pipeline, {"status": "ready", "case_id": case_id, "report": state["report"]})
        if not path.exists():
            raise HTTPException(status_code=404, detail="未有 PDF")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.post("/v1/wa/turn")
    async def wa_turn(request: Request):
        message = await _wa_message(request)
        result = converse(pipeline, message, notify=bool(message.get("notify")))
        return {"bubbles": result["bubbles"], "document": result["document"], "view": result["view"]}

    @app.post("/v1/asr")
    async def transcribe(file: UploadFile):
        engine_impl = build_asr()
        if engine_impl is None:
            raise HTTPException(
                status_code=503,
                detail="未設定 ASR_BASE_URL 或 ASR_INPROCESS。可先把轉寫文字送到 /v1/cases，source 填 asr。",
            )
        audio = await file.read()
        result = engine_impl.transcribe(audio, file.filename or "clip.wav")
        view = pipeline.ingest(result["text"], source="asr")
        view["asr"] = {"engine": result["engine"], "model": result["model"]}
        return view

    @app.get("/webhook/whatsapp")
    def verify(request: Request):
        query = request.query_params
        expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        if query.get("hub.mode") == "subscribe" and expected and query.get("hub.verify_token") == expected:
            return PlainTextResponse(query.get("hub.challenge") or "")
        raise HTTPException(status_code=403, detail="驗證失敗")

    @app.post("/webhook/whatsapp")
    async def incoming(request: Request):
        raw = await request.body()
        _authorize(raw, request.headers.get("X-Hub-Signature-256", ""))
        payload = json.loads(raw.decode("utf-8") or "{}")
        results = []
        for message in parse_inbound(payload):
            results.append(_handle_message(pipeline, message))
        return {"results": results}

    return app


def _authorize(raw: bytes, signature: str) -> None:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    if secret:
        if not verify_signature(raw, signature, secret):
            raise HTTPException(status_code=403, detail="簽名不符")
        return
    if os.environ.get("WHATSAPP_DEV_ALLOW") != "1":
        raise HTTPException(status_code=403, detail="未設定 WHATSAPP_DEV_ALLOW 或 WHATSAPP_APP_SECRET")


def _handle_message(pipeline: Pipeline, message: dict) -> dict:
    return converse(pipeline, message)


async def _wa_message(request: Request) -> dict:
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        upload = form.get("audio")
        audio = await upload.read() if upload is not None and hasattr(upload, "read") else None
        return {
            "from": str(form.get("phone") or "local"),
            "kind": "audio",
            "audio_bytes": audio,
            "filename": getattr(upload, "filename", None) or "voice.webm",
            "notify": str(form.get("notify") or "") == "1",
        }
    body = await request.json()
    return {
        "from": body.get("phone") or "local",
        "kind": "text",
        "text": body.get("text") or "",
        "choice_id": body.get("choice_id") or "",
        "source": body.get("source") or "text",
        "notify": bool(body.get("notify")),
    }


class _UTF8(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")


app = create_app()
