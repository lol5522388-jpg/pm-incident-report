"""語音流程測試：缺時間確認時用「係」；齊必填直接出 PDF 同全文。"""

from app.voice_flow import hear


def hear_report(pipe, phone: str, *lines: str, max_confirm: int = 4):
    last = None
    for line in lines:
        last = hear(pipe, phone, line)
    tries = 0
    while last and not last.get("document") and tries < max_confirm:
        last = hear(pipe, phone, "係")
        tries += 1
    return last
