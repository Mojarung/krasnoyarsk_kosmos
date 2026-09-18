from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font

VECTOR_FORMATS = {
    "geojson": ("application/geo+json", "geojson"),
    "shp": ("application/zip", "zip"),
    "gpkg": ("application/geopackage+sqlite3", "gpkg"),
    "kml": ("application/vnd.google-earth.kml+xml", "kml"),
}
REPORT_FORMATS = {
    "json": ("application/json", "json"),
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}
SHAPEFILE_FIELDS = {"fire_event_id": "event_id", "severity_label": "sev_label", "polygon_id": "poly_id"}
FONT_CANDIDATES = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
)


class ExportUnavailableError(RuntimeError):
    pass


def export_vector(collection: dict[str, Any], fmt: str, layer: str) -> bytes:
    if fmt == "geojson":
        crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}
        return json.dumps({**collection, "name": layer, "crs": crs}, ensure_ascii=False).encode()
    if not collection["features"]:
        raise ExportUnavailableError("В запросе нет контуров: нечего выгружать в этот формат")
    frame = gpd.GeoDataFrame.from_features(collection["features"], crs="EPSG:4326")
    with tempfile.TemporaryDirectory(prefix="fw_export_") as tmp:
        folder = Path(tmp)
        if fmt == "shp":
            frame.rename(columns=SHAPEFILE_FIELDS).to_file(
                folder / f"{layer}.shp", driver="ESRI Shapefile", encoding="UTF-8"
            )
            return _zip_folder(folder)
        driver = {"gpkg": "GPKG", "kml": "KML"}[fmt]
        target = folder / f"{layer}.{fmt}"
        frame.to_file(target, driver=driver, layer=layer)
        return target.read_bytes()


def _zip_folder(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.iterdir()):
            archive.write(path, path.name)
    return buffer.getvalue()


def _report_rows(report: dict[str, Any]) -> list[tuple[str, str, Any, str]]:
    burn, hot, plan = report["burn"], report["hotspots"], report["restoration"]
    rows: list[tuple[str, str, Any, str]] = [
        ("Запрос", "Период с", report["query"]["date_from"], ""),
        ("Запрос", "Период по", report["query"]["date_to"], ""),
        ("Гари", "Площадь всего", burn["total_ha"], "га"),
        ("Гари", "Сцен в расчёте", burn["scenes"], "шт"),
    ]
    rows += [("Гари по степеням", f"{s['label']} степень", s["area_ha"], "га") for s in burn["by_severity"]]
    rows += [
        ("Гари по степеням", f"{s['label']} степень, доля", round(s["share"] * 100, 1), "%")
        for s in burn["by_severity"]
    ]
    rows += [("Гари по покрову", c["label"], c["area_ha"], "га") for c in burn["by_landcover"]]
    rows += [
        ("Термоточки", "Термоаномалий всего", hot["raw_total"], "шт"),
        ("Термоточки", "Природные пожары", hot["fire"], "шт"),
        ("Термоточки", "Очагов природных пожаров", hot["fire_clusters"], "шт"),
        ("Термоточки", "Техногенные источники", hot["technogenic"], "шт"),
        ("Термоточки", "Блики", hot["glint"], "шт"),
        ("Термоточки", "Ложных выездов предотвращено", hot["false_dispatches_prevented"], "шт"),
    ]
    rows += [("Восстановление", i["label"], i["area_ha"], "га") for i in plan["items"]]
    rows += [
        ("Восстановление", f"{i['label']}, затраты", i["cost"], plan["currency"])
        for i in plan["items"]
        if i["cost"]
    ]
    rows.append(("Восстановление", "Площадь в расчёте ущерба", plan["damage_area_ha"], "га"))
    return rows


def export_report(report: dict[str, Any], fmt: str) -> bytes:
    if fmt == "json":
        return json.dumps(report, ensure_ascii=False, indent=2).encode()
    rows = _report_rows(report)
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(("section", "metric", "value", "unit"))
        writer.writerows(rows)
        return ("\ufeff" + buffer.getvalue()).encode()
    if fmt == "xlsx":
        return _xlsx(report, rows)
    return _pdf(report, rows)


def _xlsx(report: dict[str, Any], rows: list[tuple[str, str, Any, str]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Справка"
    sheet.append(("Раздел", "Показатель", "Значение", "Ед."))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 58
    sheet.column_dimensions["C"].width = 16

    days = book.create_sheet("Термоточки по дням")
    days.append(("Дата", "Природные", "Техногенные", "Блики"))
    for day in report["hotspots"]["by_day"]:
        days.append((day["day"], day["fire"], day["technogenic"], day["glint"]))

    method = book.create_sheet("Методика")
    for title, body in report["method"].items():
        method.append((title, body))
    method.append(("geometry", json.dumps(report["query"]["geometry"])[:32000]))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _fonts() -> tuple[str, str]:
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            return regular, bold
    raise ExportUnavailableError(
        "Для PDF нужен шрифт с кириллицей (DejaVu Sans или Arial). Доступны JSON, CSV и XLSX."
    )


def _pdf(report: dict[str, Any], rows: list[tuple[str, str, Any, str]]) -> bytes:
    regular, bold = _fonts()
    pdf = FPDF(format="A4")
    pdf.add_font("body", "", regular)
    pdf.add_font("body", "B", bold)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_font("body", "B", 16)
    pdf.cell(0, 10, "Аналитическая справка по природным пожарам", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("body", "", 9)
    pdf.set_text_color(90)
    pdf.cell(0, 6, f"Сформировано {report['generated_at']} UTC", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(2)

    section = None
    for name, metric, value, unit in rows:
        if name != section:
            section = name
            pdf.ln(2)
            pdf.set_font("body", "B", 11)
            pdf.cell(0, 8, name, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("body", "", 10)
        pdf.cell(125, 6.5, metric, border="B")
        formatted = f"{value:,.2f}".replace(",", " ") if isinstance(value, float) else str(value)
        pdf.cell(0, 6.5, f"{formatted} {unit}".strip(), border="B", align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("body", "B", 11)
    pdf.cell(0, 8, "Методика", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("body", "", 9)
    for body in (*report["method"].values(), report["restoration"]["disclaimer"]):
        pdf.multi_cell(0, 5, body, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    return bytes(pdf.output())
