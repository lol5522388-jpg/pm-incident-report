"""可選的大語言模型抽取。沒有金鑰就不會呼叫。輸出仍要經過 gates.merge_llm。"""

from __future__ import annotations

import json
import os
import re

from app.prompt import SYSTEM_PROMPT, user_prompt


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _openai(transcript: str, hotwords: list[str]) -> dict | None:
    import httpx

    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
    key = os.environ.get("LLM_API_KEY", "")
    response = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(transcript, hotwords)},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json(content)


def _anthropic(transcript: str, hotwords: list[str]) -> dict | None:
    import httpx

    model = os.environ.get("LLM_MODEL", "claude-sonnet-4-5")
    key = os.environ.get("LLM_API_KEY", "")
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2000,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt(transcript, hotwords)}],
        },
        timeout=60,
    )
    response.raise_for_status()
    parts = response.json().get("content") or []
    text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
    return _parse_json(text)


def extract_with_llm(transcript: str, hotwords: list[str]) -> dict | None:
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider in {"", "none", "heuristic"}:
        return None
    if provider == "anthropic":
        return _anthropic(transcript, hotwords)
    return _openai(transcript, hotwords)
