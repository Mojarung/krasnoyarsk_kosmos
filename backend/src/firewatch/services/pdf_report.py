"""PDF аналитической справки: показатели, векторные графики в палитре интерфейса, методика."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

FONT_CANDIDATES = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
)
Color = tuple[int, int, int]
FIRE: Color = (226, 71, 15)
BURN: Color = (247, 127, 0)
SATELLITE: Color = (43, 143, 196)
SEVERITY: dict[int, Color] = {1: (233, 180, 0), 2: (247, 127, 0), 3: (157, 2, 8)}
INK: Color = (34, 26, 20)
MUTED: Color = (111, 93, 82)
TRACK: Color = (238, 223, 213)

PAGE_WIDTH_MM = 190.0
CHART_HEIGHT_MM = 26.0
BAR_ROW_MM = 5.6
BAR_LABEL_MM = 46.0
BAR_VALUE_MM = 34.0
MAX_BAR_ROWS = 6


class PdfUnavailableError(RuntimeError):
    pass


def _fonts() -> tuple[str, str]:
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            return regular, bold
    raise PdfUnavailableError(
        "Для PDF нужен шрифт с кириллицей (DejaVu Sans или Arial). Доступны JSON, CSV и XLSX."
    )


def _number(value: float) -> str:
    text = f"{value:,.1f}" if isinstance(value, float) and value < 100 and value % 1 else f"{value:,.0f}"
    return text.replace(",", " ").replace(".", ",")


def _months_between(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    months, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _day(value: str) -> str:
    """Дата запроса в привычном виде: 01.04.2019 вместо 2019-04-01."""
    return f"{date.fromisoformat(value):%d.%m.%Y}"


def _stamp(value: str) -> str:
    """Отметка времени для шапки: 19.09.2026 11:18 (UTC+0). В JSON она остаётся по ISO."""
    moment = datetime.fromisoformat(value)
    offset = moment.utcoffset()
    hours = round(offset.total_seconds() / 3600) if offset else 0
    return f"{moment:%d.%m.%Y %H:%M} (UTC{hours:+d})"


def _heading(pdf: FPDF, text: str) -> None:
    pdf.ln(3)
    pdf.set_font("body", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")


def _ensure_space(pdf: FPDF, height_mm: float) -> None:
    if pdf.get_y() + height_mm > pdf.h - pdf.b_margin:
        pdf.add_page()


def severity_bar(pdf: FPDF, items: list[dict[str, Any]]) -> None:
    total = sum(item["area_ha"] for item in items)
    if total <= 0:
        return
    _ensure_space(pdf, 24)
    _heading(pdf, "Распределение площади по степеням поражения")
    x, y = pdf.l_margin, pdf.get_y() + 1
    for item in items:
        width = PAGE_WIDTH_MM * item["area_ha"] / total
        pdf.set_fill_color(*SEVERITY[item["severity"]])
        pdf.rect(x, y, width, 5, style="F")
        x += width
    pdf.set_y(y + 7)
    pdf.set_font("body", "", 9)
    for item in items:
        pdf.set_fill_color(*SEVERITY[item["severity"]])
        pdf.rect(pdf.get_x(), pdf.get_y() + 1.2, 2.4, 2.4, style="F")
        pdf.set_x(pdf.get_x() + 4)
        pdf.set_text_color(*INK)
        pdf.cell(
            58, 5, f"{item['label']}: {_number(item['area_ha'])} га, {item['share']:.1%}".replace(".", ",")
        )
    pdf.ln(6)


def month_chart(
    pdf: FPDF, title: str, months: list[str], values: dict[str, float], color: Color, unit: str
) -> None:
    series = [values.get(month, 0.0) for month in months]
    peak = max(series, default=0.0)
    if peak <= 0:
        return
    _ensure_space(pdf, CHART_HEIGHT_MM + 20)
    _heading(pdf, title)
    peak_month = months[series.index(peak)]
    pdf.set_font("body", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        0,
        5,
        f"Всего {_number(sum(series))} {unit}, пик {peak_month}: {_number(peak)} {unit}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    left, top = pdf.l_margin, pdf.get_y() + 1
    step = PAGE_WIDTH_MM / len(months)
    pdf.set_fill_color(*color)
    for index, value in enumerate(series):
        if value > 0:
            height = max(0.6, CHART_HEIGHT_MM * value / peak)
            pdf.rect(
                left + index * step + step * 0.12,
                top + CHART_HEIGHT_MM - height,
                step * 0.76,
                height,
                style="F",
            )
    pdf.set_draw_color(*TRACK)
    pdf.line(left, top + CHART_HEIGHT_MM, left + PAGE_WIDTH_MM, top + CHART_HEIGHT_MM)

    pdf.set_font("body", "", 7.5)
    for index, month in enumerate(months):
        if index == 0 or month.endswith("-01"):
            pdf.text(left + index * step, top + CHART_HEIGHT_MM + 3.4, month[:4])
    pdf.set_y(top + CHART_HEIGHT_MM + 6)


def bar_list(pdf: FPDF, title: str, rows: list[tuple[str, float]], color: Color, unit: str) -> None:
    rows = sorted((r for r in rows if r[1] > 0), key=lambda r: -r[1])[:MAX_BAR_ROWS]
    if not rows:
        return
    _ensure_space(pdf, 12 + BAR_ROW_MM * len(rows))
    _heading(pdf, title)
    total, peak = sum(v for _, v in rows), rows[0][1]
    track = PAGE_WIDTH_MM - BAR_LABEL_MM - BAR_VALUE_MM
    pdf.set_font("body", "", 9)
    for label, value in rows:
        y = pdf.get_y()
        pdf.set_text_color(*INK)
        pdf.cell(BAR_LABEL_MM, BAR_ROW_MM, label)
        pdf.set_fill_color(*TRACK)
        pdf.rect(pdf.l_margin + BAR_LABEL_MM, y + 1.4, track, 2.8, style="F")
        pdf.set_fill_color(*color)
        pdf.rect(pdf.l_margin + BAR_LABEL_MM, y + 1.4, track * value / peak, 2.8, style="F")
        pdf.set_x(pdf.l_margin + BAR_LABEL_MM + track)
        pdf.set_text_color(*MUTED)
        share = f"{value / total:.0%}" if total else ""
        pdf.cell(
            BAR_VALUE_MM,
            BAR_ROW_MM,
            f"{_number(value)} {unit}  {share}",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )


def render(report: dict[str, Any], rows: list[tuple[str, str, Any, str]]) -> bytes:
    regular, bold = _fonts()
    pdf = FPDF(format="A4")
    pdf.add_font("body", "", regular)
    pdf.add_font("body", "B", bold)
    pdf.set_margins(10, 12, 10)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_font("body", "B", 16)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "Аналитическая справка по природным пожарам", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("body", "", 9)
    pdf.set_text_color(*MUTED)
    query = report["query"]
    pdf.cell(
        0,
        5,
        f"Период {_day(query['date_from'])} - {_day(query['date_to'])}."
        f" Сформировано {_stamp(report['generated_at'])}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    section = None
    for name, metric, value, unit in rows:
        if name == "Запрос":
            continue
        if name != section:
            section = name
            _heading(pdf, name)
        pdf.set_font("body", "", 9.5)
        pdf.set_text_color(*INK)
        pdf.set_draw_color(*TRACK)
        pdf.cell(128, 6, metric, border="B")
        formatted = _number(value) if isinstance(value, int | float) else str(value)
        pdf.cell(0, 6, f"{formatted} {unit}".strip(), border="B", align="R", new_x="LMARGIN", new_y="NEXT")

    burn, hot = report["burn"], report["hotspots"]
    months = _months_between(query["date_from"], query["date_to"])
    severity_bar(pdf, burn["by_severity"])
    month_chart(
        pdf,
        "Термоточки природных пожаров по месяцам",
        months,
        {m["month"]: m["n"] for m in hot["by_month"]},
        FIRE,
        "точек",
    )
    month_chart(
        pdf,
        "Площадь гарей по месяцам",
        months,
        {m["month"]: m["area_ha"] for m in burn["by_month"]},
        BURN,
        "га",
    )
    bar_list(
        pdf, "Гари по типу территории", [(r["label"], r["area_ha"]) for r in burn["by_landcover"]], BURN, "га"
    )
    bar_list(
        pdf,
        "Термоточки по типу территории",
        [(r["label"], r["n"]) for r in hot["by_landcover"]],
        FIRE,
        "точек",
    )
    bar_list(
        pdf, "Термоточки по спутникам", [(k, v) for k, v in hot["by_satellite"].items()], SATELLITE, "точек"
    )

    _ensure_space(pdf, 40)
    _heading(pdf, "Методика")
    pdf.set_font("body", "", 8.5)
    pdf.set_text_color(*MUTED)
    for body in (*report["method"].values(), report["restoration"]["disclaimer"]):
        pdf.multi_cell(0, 4.6, body, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    return bytes(pdf.output())
