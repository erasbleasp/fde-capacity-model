"""Build docs/recommendation_memo.pdf from docs/recommendation_memo.md (the Markdown is the source).

    .venv/bin/pip install markdown          # dev-only; not needed by the dashboard
    brew install weasyprint                 # or have Brave / Chrome installed
    .venv/bin/python scripts/build_memo_pdf.py

Renders the Markdown to HTML styled like the dashboard (red tag and rule, serif headline, Fira Sans
body), then prints it to a one-page US Letter PDF with WeasyPrint, falling back to a headless
Chromium browser (Brave or Chrome) with a throwaway profile. Fonts load from Google Fonts, so it
needs a network connection.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "recommendation_memo.md"
OUT = ROOT / "docs" / "recommendation_memo.pdf"
BROWSERS = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"]

CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fira+Sans:ital,wght@0,400;0,600;0,700;1,400&family=Source+Serif+4:opsz,wght@8..60,700&display=block");
@page { size: Letter; margin: 0.5in 0.6in 0.45in 0.6in; }
* { box-sizing: border-box; }
body { font-family: "Fira Sans", system-ui, sans-serif; font-size: 9.6pt; line-height: 1.37; color: #0C0C0C; margin: 0; }
.rule { position: relative; border-top: 1px solid #E3120B; height: 9px; }
.rule::before { content: ""; position: absolute; left: 0; top: -1px; width: 34px; height: 8px; background: #E3120B; }
h1 { font-family: "Source Serif 4", Georgia, serif; font-size: 20pt; line-height: 1.1; margin: 2px 0 4px; }
h1 + p { color: #3F5661; font-size: 8.8pt; margin: 0 0 4px; }
h2 { font-size: 10.8pt; margin: 9px 0 3px; padding-top: 5px; border-top: 1px solid #B7C6CF; }
p { margin: 0 0 4px; }
ul, ol { margin: 0 0 4px; padding-left: 15px; }
li { margin: 0 0 3px; }
a { color: #006BA2; text-decoration: none; }
strong { font-weight: 600; }
em { color: #3F5661; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 2px; font-size: 8.9pt; }
th { text-align: left; font-weight: 600; border-bottom: 1px solid #0C0C0C; padding: 2px 6px 3px 0; }
td { border-bottom: 1px solid #E9EDF0; padding: 2px 6px 2px 0; }
tr:last-child td { border-bottom: 1px solid #B7C6CF; }
body > p:last-child { margin-top: 6px; font-size: 8.4pt; }
"""


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    sys.exit("Need WeasyPrint (brew install weasyprint) or a Chromium browser (Brave, Chrome, Chromium).")


def main():
    body = markdown.markdown(SRC.read_text(), extensions=["tables"])
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>FDE capacity memo</title>'
            f'<style>{CSS}</style></head><body><div class="rule"></div>{body}</body></html>')
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "memo.html"
        page.write_text(html)
        if shutil.which("weasyprint"):
            subprocess.run(["weasyprint", str(page), f"{tmp}/memo.pdf"], check=True, timeout=120)
        else:
            subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            "--no-first-run", f"--user-data-dir={tmp}/profile", "--virtual-time-budget=15000",
                            f"--print-to-pdf={tmp}/memo.pdf", page.as_uri()],
                           check=True, capture_output=True, timeout=120)
        shutil.copy(Path(tmp) / "memo.pdf", OUT)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
