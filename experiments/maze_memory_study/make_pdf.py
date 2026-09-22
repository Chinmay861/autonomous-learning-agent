"""Render REPORT.md (with embedded charts) to a styled HTML, then PDF via headless Chrome/Edge."""
import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
MD = HERE / "REPORT.md"
HTML = HERE / "REPORT.html"
PDF = HERE / "REPORT.pdf"
CHARTS = HERE / "analysis" / "charts"

CHART_ORDER = [
    ("performance_trends.png", "Figure 1. Performance trends by episode (moves vs optimal, path efficiency, invalid moves, revisits)."),
    ("quality_comparison.png", "Figure 2. Aggregate quality metrics: success rate, path efficiency, exploration efficiency."),
    ("resource_usage.png", "Figure 3. Resource usage: duration, LLM calls, total tokens, prompt/completion split."),
    ("memory_activity.png", "Figure 4. Memory utilization: items retrieved, memory writes, vector-store growth."),
    ("unseen_eval.png", "Figure 5. Unseen 5x5 evaluation: success, moves, duration."),
]

# Where to inject which figure (before the first H2 whose id contains the key)
INJECT = {
    "7-comparative-metrics-table": ["performance_trends.png", "quality_comparison.png"],
    "8-run-by-run-analysis": ["resource_usage.png"],
    "10-impact-of-persistent-agentic-memory": ["memory_activity.png"],
    "13-final-findings": ["unseen_eval.png"],
}


def img_tag(name: str, caption: str) -> str:
    path = CHARTS / name
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f'<figure class="chart">'
        f'<img src="data:image/png;base64,{data}" alt="{caption}"/>'
        f'<figcaption>{caption}</figcaption></figure>'
    )


CSS = """
@page { size: A4; margin: 15mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #1a1a1a; margin: 0; }
h1 { font-size: 21pt; color: #12365e; border-bottom: 3px solid #12365e; padding-bottom: 6px;
     margin: 0 0 10px 0; }
h2 { font-size: 14.5pt; color: #12365e; margin-top: 22px; margin-bottom: 6px;
     border-bottom: 1px solid #b9c8d8; padding-bottom: 3px; page-break-after: avoid; }
h3 { font-size: 12pt; color: #24507f; margin-top: 14px; margin-bottom: 4px; page-break-after: avoid; }
p { margin: 5px 0; text-align: justify; }
ul, ol { margin: 5px 0 5px 18px; }
li { margin: 2px 0; }
blockquote { border-left: 3px solid #d08a2c; background: #fdf6e9; margin: 8px 0; padding: 6px 10px;
             font-size: 9.8pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 8.6pt;
        page-break-inside: avoid; }
th { background: #12365e; color: #fff; text-align: left; padding: 4px 5px; font-weight: 600; }
td { border: 1px solid #ccd6e0; padding: 3px 5px; vertical-align: top; }
tr:nth-child(even) td { background: #f3f6fa; }
code { font-family: Consolas, "Courier New", monospace; font-size: 9pt; background: #eef2f6;
       padding: 0 3px; border-radius: 2px; }
pre { background: #eef2f6; padding: 7px 9px; border-radius: 4px; overflow-x: hidden;
      page-break-inside: avoid; }
pre code { background: transparent; padding: 0; }
hr { border: none; border-top: 1px solid #b9c8d8; margin: 16px 0; }
figure.chart { margin: 10px 0 14px 0; text-align: center; page-break-inside: avoid; }
figure.chart img { width: 100%; max-width: 620px; border: 1px solid #ccd6e0; border-radius: 4px;
                   padding: 4px; background: #fff; }
figcaption { font-size: 8.6pt; color: #4a5b6d; margin-top: 3px; text-align: center; }
strong { color: #10243d; }
"""


def main() -> int:
    text = MD.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list", "toc"],
    )

    for anchor, names in INJECT.items():
        for name in names:
            caption = dict(CHART_ORDER)[name]
            html_fig = img_tag(name, caption)
            pattern = re.compile(
                r'(<h2[^>]*id="[^"]*' + re.escape(anchor) + r'"[^>]*>)'
            )
            body, n = pattern.subn(html_fig + r"\1", body, count=1)
            if n == 0:
                print(f"WARNING: anchor not found for {anchor} ({name})", file=sys.stderr)

    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Persistent Agentic Memory — Controlled Comparative Study</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )
    HTML.write_text(doc, encoding="utf-8")
    print(f"wrote {HTML} ({len(doc)} chars)")

    chrome = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    exe = chrome if chrome.exists() else edge
    if not exe.exists():
        print("No Chrome/Edge found", file=sys.stderr)
        return 1

    cmd = [
        str(exe), "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=20000",
        f"--print-to-pdf={PDF}",
        HTML.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if not PDF.exists():
        print("PDF not produced. stderr:", proc.stderr[-2000:], file=sys.stderr)
        return 1

    reader = PdfReader(str(PDF))
    print(f"wrote {PDF} | {PDF.stat().st_size / 1024:.0f} KB | {len(reader.pages)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
