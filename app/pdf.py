"""PDF。優先用 WeasyPrint；Windows 上通常沒有 GTK，就改用內嵌中文字型的 fpdf2。"""

from __future__ import annotations

import html
from pathlib import Path

_FONTS = (
    Path(r"C:\Windows\Fonts\msjh.ttc"),
    Path(r"C:\Windows\Fonts\msjhbd.ttc"),
    Path(r"C:\Windows\Fonts\mingliu.ttc"),
    Path(r"C:\Windows\Fonts\kaiu.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
)


def build_html(*, formal: str, summary: str, transcript: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>事件報告草稿</title>
<style>
  body {{ font-family: "Microsoft JhengHei", "Noto Sans CJK TC", sans-serif; margin: 24px; color: #1c1c1c; }}
  h1 {{ font-size: 20px; }}
  pre {{ white-space: pre-wrap; font-family: inherit; line-height: 1.55; }}
  .note {{ color: #6b2d2d; }}
</style>
</head>
<body>
<h1>事件報告</h1>
<pre>{html.escape(formal)}</pre>
<h1>摘要</h1>
<pre>{html.escape(summary)}</pre>
</body>
</html>
"""


def _fpdf(formal: str, summary: str, transcript: str) -> bytes:
    from fpdf import FPDF

    font = next((path for path in _FONTS if path.exists()), None)
    if font is None:
        raise RuntimeError("找不到中文字型，無法生成 PDF。")
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.add_font("body", "", str(font))
    pdf.set_font("body", size=11)
    del transcript
    block = formal + "\n\n" + summary
    pdf.multi_cell(0, 7, block)
    return bytes(pdf.output())


def render_pdf(*, formal: str, summary: str, transcript: str) -> tuple[bytes, str, str]:
    document = build_html(formal=formal, summary=summary, transcript=transcript)
    try:
        from weasyprint import HTML

        return HTML(string=document).write_pdf(), "weasyprint", document
    except Exception:
        return _fpdf(formal, summary, transcript), "fpdf2", document
