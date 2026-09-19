"""PDF аналитической справки: самодостаточный печатный документ.

Справку читают отдельно от интерфейса и часто на бумаге. Поэтому каждая страница
называет территорию и период, а первая несёт обзорную карту: без неё по документу
невозможно понять, какую именно местность он описывает - на защите это и был
первый вопрос. Всё рисуется векторно, без растровых подложек и обращений в сеть:
справка формируется в офлайн-контуре и должна быть воспроизводима побайтово при
тех же данных.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

from fpdf import FPDF

from firewatch.domain.catalog import SEVERITY_COLORS
from firewatch.services import territory

FONT_CANDIDATES = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
)

Color = tuple[int, int, int]
Point = tuple[float, float]

INK: Color = (32, 24, 18)
MUTED: Color = (116, 98, 86)
HAIR: Color = (219, 208, 198)
TRACK: Color = (238, 228, 219)
PAPER: Color = (247, 243, 238)
FIRE: Color = (200, 62, 12)
BURN: Color = (223, 110, 20)
SATELLITE: Color = (40, 112, 152)
QUERY: Color = (28, 88, 122)
LAND: Color = (238, 232, 224)
LAND_EDGE: Color = (183, 168, 154)
SUBJECT_EDGE: Color = (206, 195, 185)

MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 12.0, 13.0, 16.0
SEVERITY_ROW_W = 99.0
CONTENT_W = 210.0 - 2 * MARGIN_X

MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip
MONTHS_SHORT = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_NOM = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)  # fmt: skip


class PdfUnavailableError(RuntimeError):
    pass


# ── форматирование ────────────────────────────────────────────────────────────


NBSP = "\u00a0"
"""\u0420\u0430\u0437\u0434\u0435\u043b\u0438\u0442\u0435\u043b\u044c \u0440\u0430\u0437\u0440\u044f\u0434\u043e\u0432 \u0438 \u043e\u0442\u0431\u0438\u0432\u043a\u0430 \u0437\u043d\u0430\u043a\u0430 \u043f\u0440\u043e\u0446\u0435\u043d\u0442\u0430. \u0422\u043e\u043d\u043a\u0438\u0439 U+2009 \u043f\u0435\u0440\u0435\u043d\u043e\u0441\u0438\u0442\u0441\u044f \u043f\u043e
\u0441\u0442\u0440\u043e\u043a\u0435, \u0438 \u00ab%\u00bb \u0443\u0435\u0437\u0436\u0430\u043b \u043d\u0430 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u0443\u044e \u0441\u0442\u0440\u043e\u043a\u0443 \u0432 \u0443\u0437\u043a\u043e\u0439 \u043a\u043e\u043b\u043e\u043d\u043a\u0435 \u043f\u0430\u0441\u043f\u043e\u0440\u0442\u0430 \u0442\u0435\u0440\u0440\u0438\u0442\u043e\u0440\u0438\u0438."""


def _int(value: float) -> str:
    return f"{round(value):,}".replace(",", NBSP)


def _num(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", NBSP).replace(".", ",")


def _ha(value: float) -> str:
    return _int(value) if value >= 10 else _num(value, 1)


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}".replace(".", ",") + NBSP + "%"


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def _period(date_from: str, date_to: str) -> str:
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if start.year == end.year:
        return f"с {start.day} {MONTHS_GEN[start.month - 1]} по {_day(date_to)} года"
    return f"с {_day(date_from)} года по {_day(date_to)} года"


def _month_label(month: str, with_year: bool = False) -> str:
    year, index = month.split("-")
    short = MONTHS_SHORT[int(index) - 1]
    return f"{short} {year[2:]}" if with_year else short


def _month_full(month: str) -> str:
    year, index = month.split("-")
    return f"{MONTHS_NOM[int(index) - 1]} {year}"


def _months_between(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    months, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _fonts() -> tuple[str, str]:
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            return regular, bold
    raise PdfUnavailableError(
        "Для PDF нужен шрифт с кириллицей (DejaVu Sans или Arial). Доступны JSON, CSV и XLSX."
    )


# ── документ ──────────────────────────────────────────────────────────────────


class Spravka(FPDF):
    """Колонтитулы повторяют территорию и период: вырванная из пачки страница
    остаётся привязанной к местности, а не превращается в безымянные цифры."""

    def __init__(self, title: str, period: str) -> None:
        super().__init__(format="A4")
        self.doc_title = title
        self.doc_period = period
        self.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
        self.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
        self.set_title(f"Аналитическая справка о природных пожарах. {title}")
        self.set_creator("Кордон")

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(8)
        self.set_font("body", "", 8)
        self.set_text_color(*MUTED)
        self.cell(CONTENT_W * 0.62, 4, self.doc_title)
        self.cell(CONTENT_W * 0.38, 4, self.doc_period, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*HAIR)
        self.set_line_width(0.2)
        self.line(MARGIN_X, 14, 210 - MARGIN_X, 14)
        self.set_y(19)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_draw_color(*HAIR)
        self.set_line_width(0.2)
        self.line(MARGIN_X, self.get_y() - 1.5, 210 - MARGIN_X, self.get_y() - 1.5)
        self.set_font("body", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(CONTENT_W * 0.7, 4, "Кордон · мониторинг природных пожаров по данным ДЗЗ")
        self.cell(CONTENT_W * 0.3, 4, f"с. {self.page_no()} из {{nb}}", align="R")


def _heading(pdf: FPDF, text: str, space_before: float = 4.0, needs: float = 24.0) -> None:
    """needs - сколько места должно остаться под самим блоком: заголовок, оставшийся
    один в подвале страницы, читается как обрыв."""
    _ensure(pdf, space_before + 6 + needs)
    pdf.ln(space_before)
    pdf.set_font("body", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")


def _note(pdf: FPDF, text: str, size: float = 8.0) -> None:
    pdf.set_font("body", "", size)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(CONTENT_W, 4.2, text, align="L", new_x="LMARGIN", new_y="NEXT")


def _ensure(pdf: FPDF, height: float) -> None:
    if pdf.get_y() + height > pdf.h - MARGIN_BOTTOM:
        pdf.add_page()


# ── обзорная карта ────────────────────────────────────────────────────────────


def _query_rings(geometry: dict[str, Any]) -> list[list[Point]]:
    if geometry["type"] == "Polygon":
        return [[(x, y) for x, y, *_ in geometry["coordinates"][0]]]
    if geometry["type"] == "MultiPolygon":
        return [[(x, y) for x, y, *_ in part[0]] for part in geometry["coordinates"]]
    return []


def _bounds(rings: list[list[Point]]) -> tuple[float, float, float, float]:
    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _scale_bar(pdf: FPDF, x: float, y: float, km_per_mm: float) -> float:
    """Масштабная линейка: без неё по карте нельзя оценить размер территории.
    Живёт в подписи под картой, а не поверх неё: внутри кадра она непременно
    ложилась на контур запроса, который занимает рамку целиком."""
    nice = [50, 100, 200, 300, 500, 1000]
    km = min(nice, key=lambda v: abs(v - 22 * km_per_mm))
    width = km / km_per_mm
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.5)
    pdf.line(x, y, x + width, y)
    pdf.set_line_width(0.3)
    pdf.line(x, y - 1.1, x, y + 1.1)
    pdf.line(x + width, y - 1.1, x + width, y + 1.1)
    pdf.set_font("body", "", 6.5)
    pdf.set_text_color(*INK)
    label = f"{km} км"
    pdf.text(x + width + 1.5, y + 1, label)
    return width + 1.5 + pdf.get_string_width(label)


def _minimap(pdf: FPDF, x: float, y: float, w: float, h: float, report: dict[str, Any]) -> float:
    outlines = territory.map_outlines()
    query = _query_rings(report["query"]["geometry"])
    frame = outlines["aoi"] + query
    west, south, east, north = _bounds(frame)
    pad_x, pad_y = (east - west) * 0.05, (north - south) * 0.05
    west, south, east, north = west - pad_x, south - pad_y, east + pad_x, north + pad_y

    kx = math.cos(math.radians((south + north) / 2))
    scale = min(w / ((east - west) * kx), h / (north - south))
    origin_x = x + (w - (east - west) * kx * scale) / 2
    origin_y = y + (h - (north - south) * scale) / 2

    def project(ring: list[Point]) -> list[Point]:
        return [(origin_x + (lon - west) * kx * scale, origin_y + (north - lat) * scale) for lon, lat in ring]

    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*HAIR)
    pdf.set_line_width(0.25)
    pdf.rect(x, y, w, h, style="DF")

    # Субъекты выходят за границу мониторинга, поэтому всё содержимое режется рамкой.
    with pdf.rect_clip(x, y, w, h):
        pdf.set_fill_color(*LAND)
        pdf.set_draw_color(*LAND_EDGE)
        pdf.set_line_width(0.35)
        for ring in outlines["aoi"]:
            pdf.polygon(project(ring), style="DF")

        pdf.set_draw_color(*SUBJECT_EDGE)
        pdf.set_line_width(0.2)
        for region in outlines["regions"]:
            for ring in region["rings"]:
                pdf.polygon(project(ring), style="D")

        with pdf.local_context(fill_opacity=0.18):
            pdf.set_fill_color(*QUERY)
            for ring in query:
                pdf.polygon(project(ring), style="F")
        pdf.set_draw_color(*QUERY)
        pdf.set_line_width(0.6)
        for ring in query:
            pdf.polygon(project(ring), style="D")

        pdf.set_font("body", "", 6.2)
        pdf.set_text_color(*MUTED)
        for region in outlines["regions"]:
            label_x, label_y = project([region["label_at"]])[0]
            text_w = pdf.get_string_width(region["short"])
            # Подпись субъекта у края кадра обрезалась рамкой: держим её внутри.
            left = min(max(label_x - text_w / 2, x + 1.5), x + w - text_w - 1.5)
            pdf.text(left, label_y, region["short"])

        pdf.set_fill_color(*FIRE)
        for burn in report["burn"]["largest"][:5]:
            dot_x, dot_y = project([(burn["lon"], burn["lat"])])[0]
            pdf.circle(dot_x - 0.9, dot_y - 0.9, 0.9, style="F")

    return 111.32 / scale


def _map_caption(pdf: FPDF, x: float, y: float, km_per_mm: float) -> None:
    """Подпись карты: легенда, масштаб и указатель севера одной строкой."""
    pdf.set_font("body", "", 7)
    for color, label, edge in (
        (QUERY, "территория запроса", QUERY),
        (LAND, "граница мониторинга", LAND_EDGE),
        (FIRE, "пять крупнейших гарей", FIRE),
    ):
        pdf.set_fill_color(*color)
        pdf.set_draw_color(*edge)
        pdf.set_line_width(0.3)
        pdf.rect(x, y - 1.6, 2.6, 2.6, style="DF")
        pdf.set_text_color(*MUTED)
        pdf.text(x + 4, y + 0.6, label)
        x += pdf.get_string_width(label) + 9

    x += 3
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.3)
    pdf.line(x, y + 1, x, y - 2.6)
    pdf.line(x, y - 2.6, x - 1.1, y - 1.3)
    pdf.line(x, y - 2.6, x + 1.1, y - 1.3)
    pdf.set_font("body", "", 6.5)
    pdf.set_text_color(*INK)
    pdf.text(x + 2, y + 0.6, "север")
    x += 2 + pdf.get_string_width("север") + 7
    _scale_bar(pdf, x, y, km_per_mm)


# ── блоки справки ─────────────────────────────────────────────────────────────


def _cover(pdf: FPDF, report: dict[str, Any]) -> None:
    place = report["territory"]
    pdf.set_font("body", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 4, "КОРДОН · МОНИТОРИНГ ПРИРОДНЫХ ПОЖАРОВ ПО ДАННЫМ ДЗЗ", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.set_font("body", "B", 19)
    pdf.set_text_color(*INK)
    pdf.cell(0, 9, "Аналитическая справка", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)
    pdf.set_font("body", "B", 13)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 6.5, place["name"], align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("body", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5.5, _period(report["query"]["date_from"], report["query"]["date_to"]),
             new_x="LMARGIN", new_y="NEXT")  # fmt: skip

    pdf.ln(2.5)
    top = pdf.get_y()
    # Рамка карты почти квадратная: в кадр всегда входит и граница мониторинга, и
    # запрос, а их объединение вытянуто по вертикали. Широкая рамка давала поля.
    map_w, map_h = 64.0, 80.0
    passport_x, passport_w = MARGIN_X + map_w + 7, CONTENT_W - map_w - 7
    rows = _passport_rows(place)
    height = max(map_h, _passport_height(pdf, passport_w - 8, rows))
    km_per_mm = _minimap(pdf, MARGIN_X, top, map_w, height, report)
    _map_caption(pdf, MARGIN_X, top + height + 4, km_per_mm)
    _passport(pdf, passport_x, top, passport_w, height, rows)
    pdf.set_y(top + height + 8)


def _passport_rows(place: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Паспорт территории: что запрошено, в каких координатах и что из этого
    покрыто данными. Именно он отвечает на вопрос «про какую местность документ»."""
    area = place["monitoring_area"]
    covered = area["covered_share"]
    if covered >= 0.999:
        coverage = "целиком внутри границы мониторинга"
    elif covered <= 0:
        coverage = "за пределами границы мониторинга, данных нет"
    else:
        coverage = f"{_pct(covered, 0)} площади, {_int(area['covered_km2'])} км². Вне границы данных нет"

    subjects = place["subjects"]
    if subjects:
        listing = "\n".join(
            f"{s['name']}, {_pct(s['share_of_query'], 0)} запроса"
            + (", целиком" if s["whole"] else f", охвачено {_pct(s['share_of_subject'], 0)}")
            for s in subjects
        )
    else:
        listing = "нет субъектов территории мониторинга"

    return [
        ("Тип запроса", place["kind_label"], False),
        ("Площадь запроса", f"{_int(place['area_km2'])} км²", True),
        ("Координаты (WGS 84)", place["bbox_label"], False),
        ("Покрыто данными", coverage, False),
        ("Субъекты Российской Федерации", listing, False),
        (
            "Территория мониторинга",
            f"{area['name']}, {_int(area['area_km2'])} км². "
            f"Данные за сезоны {area['seasons']}, месяцы {area['months']}",
            False,
        ),
    ]


def _passport_height(pdf: FPDF, inner_w: float, rows: list[tuple[str, str, bool]]) -> float:
    """Высота плашки считается по числу строк после переноса: прибитая гвоздём
    высота обрезала перечень субъектов у широких запросов."""
    total = 6.0
    for _, value, bold in rows:
        pdf.set_font("body", "B" if bold else "", 8.8)
        lines = pdf.multi_cell(inner_w, 4.2, value, align="L", dry_run=True, output="LINES")
        total += 3.6 + 4.2 * max(1, len(lines)) + 1.4
    return total


def _passport(pdf: FPDF, x: float, y: float, w: float, h: float, rows: list[tuple[str, str, bool]]) -> None:
    pdf.set_fill_color(*PAPER)
    pdf.rect(x, y, w, h, style="F")
    inner_x, inner_w = x + 4, w - 8
    pdf.set_y(y + 4)
    for label, value, bold in rows:
        pdf.set_x(inner_x)
        pdf.set_font("body", "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(inner_w, 3.6, label, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(inner_x)
        pdf.set_font("body", "B" if bold else "", 8.8)
        pdf.set_text_color(*INK)
        pdf.multi_cell(inner_w, 4.2, value, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.4)


def _headline(pdf: FPDF, report: dict[str, Any]) -> None:
    burn, hot = report["burn"], report["hotspots"]
    share = burn.get("burned_share")
    tiles = [
        ("Пройдено огнём", _ha(burn["total_ha"]), "га"),
        ("Доля территории", _pct(share, 2) if share is not None else "нет данных", ""),
        ("Контуров гарей", _int(burn["contours"]), "шт"),
        ("Очагов пожаров", _int(hot["fire_clusters"]), "шт"),
    ]
    _ensure(pdf, 24)
    top = pdf.get_y()
    width = CONTENT_W / len(tiles)
    pdf.set_draw_color(*HAIR)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN_X, top, 210 - MARGIN_X, top)
    for index, (label, value, unit) in enumerate(tiles):
        x = MARGIN_X + index * width
        pdf.set_xy(x, top + 2.5)
        pdf.set_font("body", "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(width, 4, label)
        pdf.set_xy(x, top + 7)
        pdf.set_font("body", "B", 17)
        pdf.set_text_color(*INK)
        pdf.cell(pdf.get_string_width(value) + 1, 8, value)
        if unit:
            pdf.set_font("body", "", 9)
            pdf.set_text_color(*MUTED)
            pdf.cell(10, 8, unit)
        if index:
            pdf.set_draw_color(*HAIR)
            pdf.line(x - 3, top + 3, x - 3, top + 16)
    pdf.set_y(top + 17)
    pdf.set_draw_color(*HAIR)
    pdf.line(MARGIN_X, pdf.get_y(), 210 - MARGIN_X, pdf.get_y())
    pdf.set_y(pdf.get_y() + 1)
    # Пустой результат - это тоже ответ, и он должен быть сказан словами: колонка
    # нулей читается как сбой выгрузки, а не как «здесь не горело».
    if burn["total_ha"] <= 0:
        pdf.ln(2)
        _note(
            pdf,
            "В границах запроса за указанный период контуров гарей не обнаружено. "
            "Проверьте период: данные собраны за сезоны "
            f"{report['territory']['monitoring_area']['seasons']}, месяцы "
            f"{report['territory']['monitoring_area']['months']}.",
            size=9,
        )


def _severity(pdf: FPDF, report: dict[str, Any]) -> None:
    items = [item for item in report["burn"]["by_severity"] if item["area_ha"] > 0]
    total = sum(item["area_ha"] for item in items)
    if total <= 0:
        return
    _ensure(pdf, 30)
    _heading(pdf, "Распределение площади по степеням поражения")
    top = pdf.get_y() + 0.5
    x = MARGIN_X
    for item in items:
        width = CONTENT_W * item["area_ha"] / total
        pdf.set_fill_color(*SEVERITY_COLORS[item["severity"]])
        pdf.set_draw_color(*HAIR)
        pdf.set_line_width(0.2)
        pdf.rect(x, top, width, 6.5, style="DF")
        x += width
    pdf.set_y(top + 9)

    for item in items:
        y = pdf.get_y()
        pdf.set_fill_color(*SEVERITY_COLORS[item["severity"]])
        pdf.set_draw_color(*HAIR)
        pdf.rect(MARGIN_X, y + 1.6, 2.8, 2.8, style="DF")
        pdf.set_x(MARGIN_X + 5)
        pdf.set_font("body", "", 9)
        pdf.set_text_color(*INK)
        pdf.cell(40, 6, f"{item['label']} степень")
        pdf.set_font("body", "B", 9)
        pdf.cell(34, 6, f"{_ha(item['area_ha'])} га", align="R")
        pdf.set_font("body", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(20, 6, _pct(item["share"]), align="R")
        pdf.set_draw_color(*HAIR)
        pdf.line(MARGIN_X, y + 6, MARGIN_X + SEVERITY_ROW_W, y + 6)
        pdf.set_y(y + 6)
    index = report["burn"].get("severity_index")
    if index:
        _note(pdf, f"Индекс тяжести {_num(index, 2)} из 3: средняя степень, взвешенная по площади.")


def _largest(pdf: FPDF, report: dict[str, Any]) -> None:
    rows = report["burn"].get("largest") or []
    if not rows:
        return
    _ensure(pdf, 14 + 5.5 * len(rows))
    _heading(pdf, "Пять крупнейших гарей")
    _note(pdf, "Отмечены точками на карте. Координаты центра контура в WGS 84.")
    widths = (18.0, 34.0, 38.0, 42.0, 54.0)
    headers = ("№", "Площадь, га", "Дата снимка «после»", "Координаты", "Сцена")
    pdf.set_font("body", "", 7.5)
    pdf.set_text_color(*MUTED)
    for width, header in zip(widths, headers, strict=True):
        pdf.cell(width, 5, header)
    pdf.ln(5)
    pdf.set_draw_color(*HAIR)
    pdf.set_line_width(0.2)
    for number, row in enumerate(rows[:5], start=1):
        y = pdf.get_y()
        pdf.set_font("body", "", 8.5)
        pdf.set_text_color(*INK)
        pdf.cell(widths[0], 5.6, str(number))
        pdf.set_font("body", "B", 8.5)
        pdf.cell(widths[1], 5.6, _ha(row["area_ha"]))
        pdf.set_font("body", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(widths[2], 5.6, _day(row["date_post"]))
        pdf.cell(widths[3], 5.6, f"{_num(row['lat'], 3)}° с.ш., {_num(row['lon'], 3)}° в.д.")
        pdf.cell(widths[4], 5.6, str(row["scene_id"]))
        pdf.ln(5.6)
        pdf.line(MARGIN_X, y + 5.6, 210 - MARGIN_X, y + 5.6)


def _month_chart(
    pdf: FPDF, title: str, months: list[str], values: dict[str, float], color: Color, unit: str
) -> None:
    series = [values.get(month, 0.0) for month in months]
    peak = max(series, default=0.0)
    if peak <= 0:
        return
    height = 26.0
    _ensure(pdf, height + 22)
    _heading(pdf, title)
    peak_month = months[series.index(peak)]
    pdf.set_font("body", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        0,
        4.6,
        f"Всего {_ha(sum(series))} {unit}. Пик - {_month_full(peak_month)}: {_ha(peak)} {unit}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    left, top = MARGIN_X, pdf.get_y() + 3.5
    step = CONTENT_W / len(months)
    every = 1 if len(months) <= 14 else (2 if len(months) <= 26 else 3)
    for index, value in enumerate(series):
        if value <= 0:
            continue
        bar = max(0.7, height * value / peak)
        pdf.set_fill_color(*color)
        pdf.rect(left + index * step + step * 0.14, top + height - bar, step * 0.72, bar, style="F")
    pdf.set_draw_color(*HAIR)
    pdf.set_line_width(0.25)
    pdf.line(left, top + height, left + CONTENT_W, top + height)

    # Подпись значения только у пика: число на каждом столбце превращает график в таблицу.
    pdf.set_font("body", "B", 7)
    pdf.set_text_color(*INK)
    peak_index = series.index(peak)
    label = _ha(peak)
    pdf.text(
        left + peak_index * step + step / 2 - pdf.get_string_width(label) / 2,
        top + height - height * 1.0 - 1.2,
        label,
    )

    pdf.set_font("body", "", 6.8)
    pdf.set_text_color(*MUTED)
    year = None
    for index, month in enumerate(months):
        if index % every:
            continue
        text = _month_label(month)
        pdf.text(left + index * step + step / 2 - pdf.get_string_width(text) / 2, top + height + 3.4, text)
    for index, month in enumerate(months):
        if month[:4] == year:
            continue
        year = month[:4]
        pdf.set_font("body", "B", 6.8)
        pdf.set_text_color(*INK)
        pdf.text(left + index * step + step * 0.14, top + height + 7, year)
    pdf.set_y(top + height + 9)


def _fit(pdf: FPDF, text: str, width: float) -> str:
    """Подпись длиннее своей колонки наезжала на дорожку столбика."""
    if pdf.get_string_width(text) <= width:
        return text
    while text and pdf.get_string_width(text + "…") > width:
        text = text[:-1]
    return text.rstrip(" ,") + "…"


def _bar_list(
    pdf: FPDF,
    rows: list[tuple[str, float]],
    color: Color,
    unit: str,
    title: str = "",
    note: str | None = None,
) -> None:
    rows = sorted((row for row in rows if row[1] > 0), key=lambda row: -row[1])[:7]
    if not rows:
        return
    _ensure(pdf, 14 + 5.6 * len(rows))
    if title:
        _heading(pdf, title)
    else:
        pdf.ln(1)
    if note:
        _note(pdf, note)
    total, peak = sum(value for _, value in rows), rows[0][1]
    pdf.set_font("body", "", 8.5)
    # Колонка подписей тянется под самую длинную из них: у типов покрова это одно
    # слово, у работ по восстановлению - половина строки, и общая ширина всё резала.
    value_w = 38.0
    label_w = min(86.0, max(44.0, max(pdf.get_string_width(label) for label, _ in rows) + 4))
    track = CONTENT_W - label_w - value_w
    for label, value in rows:
        y = pdf.get_y()
        pdf.set_text_color(*INK)
        pdf.cell(label_w, 5.6, _fit(pdf, label, label_w - 3))
        pdf.set_fill_color(*TRACK)
        pdf.rect(MARGIN_X + label_w, y + 1.5, track, 2.6, style="F")
        pdf.set_fill_color(*color)
        pdf.rect(MARGIN_X + label_w, y + 1.5, track * value / peak, 2.6, style="F")
        pdf.set_x(MARGIN_X + label_w + track)
        pdf.set_text_color(*MUTED)
        share = _pct(value / total, 0) if total else ""
        pdf.cell(value_w, 5.6, f"{_ha(value)} {unit}   {share}", align="R", new_x="LMARGIN", new_y="NEXT")


def _facts(pdf: FPDF, pairs: list[tuple[str, str]], title: str = "") -> None:
    pairs = [pair for pair in pairs if pair[1]]
    if not pairs:
        return
    _ensure(pdf, 12 + 5.4 * ((len(pairs) + 1) // 2))
    if title:
        _heading(pdf, title)
    else:
        pdf.ln(1.5)
    column = CONTENT_W / 2
    pdf.set_draw_color(*HAIR)
    pdf.set_line_width(0.2)
    for index in range(0, len(pairs), 2):
        y = pdf.get_y()
        for offset, (label, value) in enumerate(pairs[index : index + 2]):
            x = MARGIN_X + offset * column
            pdf.set_xy(x, y)
            pdf.set_font("body", "", 8.5)
            pdf.set_text_color(*MUTED)
            pdf.cell(column * 0.6, 5.4, label)
            pdf.set_font("body", "B", 8.5)
            pdf.set_text_color(*INK)
            pdf.cell(column * 0.4 - 4, 5.4, value, align="R")
            pdf.line(x, y + 5.4, x + column - 4, y + 5.4)
        pdf.set_y(y + 5.4)


def _detections(pdf: FPDF, report: dict[str, Any]) -> None:
    hot = report["hotspots"]
    weather, power = hot.get("weather") or {}, hot.get("power") or {}
    _heading(pdf, "Термоточки: что отсеяно и в каких условиях горело")
    _facts(
        pdf,
        [
            ("Термоаномалий всего", f"{_int(hot['raw_total'])} шт"),
            ("Из них природные пожары", f"{_int(hot['fire'])} шт"),
            ("Техногенные источники", f"{_int(hot['technogenic'])} шт"),
            ("Блики на воде и облаках", f"{_int(hot['glint'])} шт"),
            ("Отсеяно от общего числа", _pct(hot["filtered_share"])),
            ("Ложных выездов предотвращено", f"{_int(hot['false_dispatches_prevented'])} шт"),
            ("Дней с активным горением", f"{_int(hot['active_days'])}" if hot.get("active_days") else ""),
            (
                "Суммарная мощность излучения",
                f"{_int(power['total_mw'])} МВт" if power.get("total_mw") else "",
            ),
            (
                "Температура воздуха, средняя",
                f"{_num(weather['t2m_mean_c'], 1)} °C" if weather.get("t2m_mean_c") is not None else "",
            ),
            (
                "Ветер, средний и максимум",
                f"{_num(weather['wind_mean_ms'], 1)} и {_num(weather['wind_max_ms'], 1)} м/с"
                if weather.get("wind_mean_ms") is not None
                else "",
            ),
        ],
    )


def _quality(pdf: FPDF, report: dict[str, Any]) -> None:
    quality = report.get("quality")
    if not quality:
        return
    _heading(pdf, "Качество моделей на этой территории")
    _note(
        pdf,
        "Метрика соревнования: 0,35·F1 активного горения + 0,35·IoU контура гари + 0,30·mIoU степеней. "
        "Считается по сценам с эталонной маской, попавшим в запрос.",
    )
    iou = quality.get("iou_severity") or []
    _facts(
        pdf,
        [
            ("Итоговый Score", _num(quality["score"], 3)),
            ("Сцен с эталоном", f"{_int(quality['af_scenes'])} AF / {_int(quality['bs_scenes'])} BS"),
            ("F1 активного горения", _num(quality["f1_af"], 3)),
            ("IoU контура гари", _num(quality["iou_burn"], 3)),
            ("mIoU степеней", _num(quality["miou_sev"], 3)),
            ("IoU по степеням", ", ".join(_num(value, 2) for value in iou) if iou else ""),
        ],
    )
    if quality.get("note"):
        _note(pdf, quality["note"], size=7.5)


def _emissions(pdf: FPDF, report: dict[str, Any]) -> None:
    block = report.get("emissions")
    if not block or not block.get("species") or not block.get("dry_matter_t"):
        return
    _heading(pdf, "Оценка выбросов в атмосферу")
    _note(pdf, block.get("method", ""))
    _facts(
        pdf,
        [
            ("Сгоревшая биомасса", f"{_int(block['dry_matter_t'])} т"),
            ("CO₂-эквивалент", f"{_int(block['co2e_t'])} т"),
            *((f"{s['label']} ({s['name']})", f"{_int(s['tonnes'])} т") for s in block["species"]),
        ],
    )


def _restoration(pdf: FPDF, report: dict[str, Any]) -> None:
    plan = report.get("restoration")
    if not plan or not plan.get("items"):
        return
    _ensure(pdf, 40)
    _heading(pdf, "Восстановление: оценка по условным ставкам")
    _note(pdf, plan["disclaimer"])
    _bar_list(pdf, [(item["label"], item["area_ha"]) for item in plan["items"]], BURN, "га")
    pdf.ln(1)
    _note(
        pdf,
        f"Суммарная условная стоимость работ {_int(plan['total_cost'])} {plan['currency']}. "
        "Это не оценка ущерба и не основание для расчётов: ставки демонстрационные.",
    )


def _method(pdf: FPDF, report: dict[str, Any]) -> None:
    _ensure(pdf, 40)
    _heading(pdf, "Методика расчёта")
    for body in report["method"].values():
        _note(pdf, body, size=8)
        pdf.ln(0.8)


def _reproduce(pdf: FPDF, report: dict[str, Any]) -> None:
    """Воспроизводимость чисел - отдельный критерий оценки, поэтому в справке
    лежит запрос, которым она получена, а не только её результат."""
    place, query = report["territory"], report["query"]
    _ensure(pdf, 46)
    _heading(pdf, "Как воспроизвести эти числа")
    _note(
        pdf,
        "Справка собрана сервисом «Кордон» по данным VIIRS (активное горение) и Sentinel-2 и Sentinel-1 "
        "(контуры гарей и степени поражения). Тот же результат возвращает REST API без интерфейса:",
    )
    # Полигон в команду не вписать: у нарисованной области сотни вершин. Прямоугольник
    # помещается целиком, поэтому его показываем параметрами, а полигон - ссылкой на
    # блок query в JSON того же отчёта. Подменять полигон его bbox нельзя: bbox шире,
    # и числа по нему не сойдутся с приведёнными в справке.
    if place["kind"] == "bbox":
        west, south, east, north = place["bbox"]
        command = (
            "curl 'http://<host>/api/v1/report?format=json"
            f"&bbox={west},{south},{east},{north}"
            f"&date_from={query['date_from']}&date_to={query['date_to']}'"
        )
        source = "Запрос задан ограничивающим прямоугольником и помещается в команду целиком."
    else:
        command = (
            "curl -X POST 'http://<host>/api/v1/report?format=json' \\\n"
            "  -H 'Content-Type: application/json' -d @query.json"
        )
        source = (
            "Запрос задан полигоном: его геометрия вместе с датами лежит в блоке query "
            "выгрузки JSON этого же отчёта, её и нужно положить в query.json."
        )
    pdf.set_font("body", "", 7.5)
    pdf.set_text_color(*INK)
    pdf.set_fill_color(*PAPER)
    pdf.multi_cell(CONTENT_W, 4.2, command, align="L", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    area = place["monitoring_area"]
    _note(
        pdf,
        f"{source} Площади считаются в {place['area_crs']}, координаты выгрузок в {place['crs']}. "
        f"Территория мониторинга покрыта данными за сезоны {area['seasons']}, месяцы {area['months']}.",
    )
    stamp = report["generated_at"]
    _note(pdf, f"Справка сформирована {_day(stamp[:10])} года, {stamp[11:16]} UTC.")


# ── сборка ────────────────────────────────────────────────────────────────────


def render(report: dict[str, Any]) -> bytes:
    regular, bold = _fonts()
    place = report["territory"]
    period = _period(report["query"]["date_from"], report["query"]["date_to"])
    pdf = Spravka(place["name"], period)
    pdf.add_font("body", "", regular)
    pdf.add_font("body", "B", bold)
    pdf.alias_nb_pages()
    pdf.add_page()

    burn, hot = report["burn"], report["hotspots"]
    months = _months_between(report["query"]["date_from"], report["query"]["date_to"])

    _cover(pdf, report)
    _headline(pdf, report)
    _severity(pdf, report)
    _largest(pdf, report)

    # Дальше блоки идут потоком: каждый сам просит новую страницу, когда не влезает.
    # Принудительные разрывы оставляли по трети листа пустыми.
    _month_chart(
        pdf,
        "Площадь гарей по месяцам",
        months,
        {m["month"]: m["area_ha"] for m in burn["by_month"]},
        BURN,
        "га",
    )
    _month_chart(
        pdf,
        "Термоточки природных пожаров по месяцам",
        months,
        {m["month"]: m["n"] for m in hot["by_month"]},
        FIRE,
        "точек",
    )
    _bar_list(
        pdf,
        [(row["label"], row["area_ha"]) for row in burn["by_landcover"]],
        BURN,
        "га",
        title="Что горело: площадь гарей по типу покрова",
    )
    _bar_list(
        pdf,
        list(hot["by_satellite"].items()),
        SATELLITE,
        "точек",
        title="Термоточки по спутникам",
        note="Приборы VIIRS на Suomi NPP и NOAA-20.",
    )
    _detections(pdf, report)
    _emissions(pdf, report)
    _quality(pdf, report)
    _restoration(pdf, report)
    _method(pdf, report)
    _reproduce(pdf, report)
    return bytes(pdf.output())
