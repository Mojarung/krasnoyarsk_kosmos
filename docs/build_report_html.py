"""Собирает docs/ML_REPORT.md в один HTML-файл с вшитыми картинками, чтобы пересылать без репозитория.

Запуск: uv run --with markdown python docs/build_report_html.py
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import markdown

SOURCE = Path("docs/ML_REPORT.md")
TARGET = Path("docs/ML_REPORT.html")
STYLE = """
body { font: 16px/1.6 -apple-system, "Segoe UI", Roboto, sans-serif; color: #231d19; background: #fbf8f6; margin: 0; }
main { max-width: 920px; margin: 0 auto; padding: 40px 24px 80px; }
h1 { font-size: 30px; line-height: 1.2; margin: 0 0 20px; }
h2 { font-size: 23px; margin: 48px 0 12px; padding-top: 20px; border-top: 1px solid #d6c9c1; }
h3 { font-size: 18px; margin: 30px 0 8px; }
img { max-width: 100%; height: auto; border-radius: 10px; margin: 8px 0 4px; background: #fff; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14.5px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #e6ddd7; vertical-align: top; }
th { color: #6e615a; font-weight: 600; }
code { font: 13.5px ui-monospace, Consolas, monospace; background: #eee7e2; padding: 1px 5px; border-radius: 5px; }
pre { background: #231d19; color: #f5efeb; padding: 16px 18px; border-radius: 12px; overflow-x: auto; }
pre code { background: none; color: inherit; padding: 0; }
"""


def embed(match: re.Match[str]) -> str:
    path = (SOURCE.parent / match.group(2)).resolve()
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img alt="{match.group(1)}" src="data:image/png;base64,{data}"'


def main() -> None:
    html = markdown.markdown(SOURCE.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    html = re.sub(r'<img alt="([^"]*)" src="([^"]+\.png)"', embed, html)
    title = SOURCE.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
    page = f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>{STYLE}</style></head><body><main>{html}</main></body></html>'
    TARGET.write_text(page, encoding="utf-8")
    print(TARGET, TARGET.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
