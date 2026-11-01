"""Qwen3-ASR 1.7B 接入。

預設不在 webhook 進程裡載入模型。設定 ASR_BASE_URL 時，把音訊送到
自行部署的 OpenAI 相容轉寫服務，並帶上熱詞（context / hotwords / prompt）。
設定 ASR_INPROCESS=1 才會在本機載入 Qwen/Qwen3-ASR-1.7B。

時間、地點、人名的近音建議只做標記，不改原文。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.hotwords import load_fuzzy_targets, load_hotwords


def _distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 1:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cjk(text: str) -> bool:
    return bool(text) and all("\u4e00" <= ch <= "\u9fff" for ch in text)


def review_transcript(text: str, targets: list[tuple[str, str]] | None = None) -> list[dict]:
    """找出與熱詞相差一字的片段。不修改 text。"""
    targets = targets if targets is not None else load_fuzzy_targets()
    found: list[dict] = []
    used: set[tuple[int, int]] = set()
    for kind, word in targets:
        if word in text or not _cjk(word) or len(word) < 3:
            continue
        for index in range(0, len(text) - len(word) + 1):
            window = text[index : index + len(word)]
            if not _cjk(window):
                continue
            span = (index, index + len(word))
            if span in used or _distance(window, word) != 1:
                continue
            found.append(
                {
                    "kind": kind,
                    "start": index,
                    "end": index + len(word),
                    "heard": window,
                    "suggestion": word,
                    "status": "pending",
                    "auto_apply": False,
                }
            )
            used.add(span)
            break
    return found


class Qwen3AsrHttp:
    """對自建 vLLM / qwen-asr-serve 的 /v1/audio/transcriptions 發請求。"""

    def __init__(self, base_url: str, model: str = "Qwen/Qwen3-ASR-1.7B"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def transcribe(self, audio: bytes, filename: str = "clip.wav") -> dict:
        import httpx

        hotwords = load_hotwords()
        context = "\n".join(hotwords)
        url = f"{self.base_url}/v1/audio/transcriptions"
        files = {"file": (filename, audio, "application/octet-stream")}
        data = {
            "model": self.model,
            "language": "",
            "response_format": "json",
            # 官方 SDK 把熱詞放在 context；vLLM 有的版本讀 hotwords，有的版本只讀 prompt。
            "hotwords": context,
            "prompt": context,
        }
        response = httpx.post(url, data=data, files=files, timeout=180)
        response.raise_for_status()
        body = response.json()
        text = (body.get("text") or "").strip()
        return {
            "text": text,
            "language": body.get("language"),
            "engine": "qwen3-asr-http",
            "model": self.model,
            "suggestions": review_transcript(text),
        }


class Qwen3AsrLocal:
    """進程內載入。僅在獨立機器、並且 ASR_INPROCESS=1 時使用。"""

    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B"):
        self.model_id = model_id
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        import torch
        from qwen_asr import Qwen3ASRModel

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        self._model = Qwen3ASRModel.from_pretrained(
            self.model_id,
            dtype=dtype,
            device_map=device,
            max_new_tokens=512,
        )
        return self._model

    def transcribe(self, audio: bytes, filename: str = "clip.wav") -> dict:
        hotwords = load_hotwords()
        context = "\n".join(hotwords)
        suffix = Path(filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(audio)
            path = handle.name
        try:
            model = self._load()
            try:
                results = model.transcribe(audio=path, language=None, context=context)
            except TypeError:
                results = model.transcribe(audio=path, language=None)
            text = (results[0].text or "").strip()
            language = getattr(results[0], "language", None)
        finally:
            os.remove(path)
        return {
            "text": text,
            "language": language,
            "engine": "qwen3-asr-local",
            "model": self.model_id,
            "suggestions": review_transcript(text),
        }


def build_asr():
    base = os.environ.get("ASR_BASE_URL", "").strip()
    if base:
        model = os.environ.get("ASR_MODEL", "Qwen/Qwen3-ASR-1.7B")
        return Qwen3AsrHttp(base, model)
    if os.environ.get("ASR_INPROCESS", "").strip() == "1":
        return Qwen3AsrLocal(os.environ.get("ASR_MODEL", "Qwen/Qwen3-ASR-1.7B"))
    return None
