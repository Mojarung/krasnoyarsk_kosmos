import pytest
from shapely.geometry import box, mapping

from firewatch.services import pdf_report, territory

def _font_available() -> bool:
    try:
        pdf_report._fonts()
    except pdf_report.PdfUnavailableError:
        return False
    return True


# Рендер требует шрифта с кириллицей: в образе это DejaVu, на машине разработчика
# Arial. Там, где нет ни того ни другого, PDF и не предлагается - остальные форматы
# закрывают требование машиночитаемой выгрузки.
pytestmark = pytest.mark.skipif(not _font_available(), reason="нет шрифта с кириллицей")


def _report(total_ha: float = 133_181.08) -> dict:
    geometry = mapping(box(41.0, 47.5, 43.5, 49.5))
    severity = [
        {"severity": 1, "label": "слабая", "area_ha": total_ha * 0.42, "share": 0.42},
        {"severity": 2, "label": "средняя", "area_ha": total_ha * 0.26, "share": 0.26},
        {"severity": 3, "label": "сильная", "area_ha": total_ha * 0.32, "share": 0.32},
    ]
    return {
        "generated_at": "2026-09-19T11:49:15+00:00",
        "territory": territory.describe(geometry),
        "query": {"geometry": geometry, "date_from": "2020-04-01", "date_to": "2020-10-31"},
        "burn": {
            "total_ha": total_ha,
            "scenes": 67,
            "contours": 3867 if total_ha else 0,
            "query_area_km2": 41_082.6,
            "burned_share": total_ha / 4_108_260 if total_ha else 0.0,
            "severity_index": 1.893 if total_ha else None,
            "by_month": [{"month": "2020-07", "area_ha": total_ha, "contours": 344}] if total_ha else [],
            "largest": (
                [
                    {
                        "contour_id": 11509,
                        "scene_id": "BS_tr_000026",
                        "date_post": "2020-07-26",
                        "area_ha": 7204.8,
                        "lon": 42.05648,
                        "lat": 45.87343,
                    }
                ]
                if total_ha
                else []
            ),
            "by_severity": severity if total_ha else [],
            "by_landcover": [{"landcover": "crop", "label": "пашня", "area_ha": total_ha}] if total_ha else [],
        },
        "hotspots": {
            "raw_total": 1173,
            "fire": 1081,
            "technogenic": 89,
            "glint": 3,
            "fire_clusters": 237,
            "false_dispatches_prevented": 16,
            "filtered_share": 0.0784,
            "active_days": 14,
            "by_satellite": {"SNPP": 898, "NOAA20": 183},
            "by_month": [{"month": "2020-09", "n": 486}],
            "weather": {"t2m_mean_c": 19.0, "wind_mean_ms": 6.5, "wind_max_ms": 11.3},
            "power": {"total_mw": 18452.0, "max_mw": 412.6, "saturated": 23},
        },
        "quality": {
            "af_scenes": 75,
            "bs_scenes": 71,
            "f1_af": 0.9975,
            "iou_burn": 0.3968,
            "iou_severity": [0.23, 0.22, 0.32],
            "miou_sev": 0.2594,
            "score": 0.5658,
            "note": "F1 завышен: модель обучена на этих же сценах.",
        },
        "restoration": {
            "currency": "RUB",
            "disclaimer": "Ставки условные и нужны для демонстрации расчёта.",
            "total_cost": 468_880_800,
            "damage_area_ha": 118.24,
            "items": [
                {"label": "Агротехнические работы, проверка на пал стерни", "area_ha": 81_313.0, "cost": 1}
            ],
        },
        "emissions": {
            "disclaimer": "Оценка по коэффициентам GFED.",
            "method": "Выбросы = площадь x нагрузка x полнота сгорания x коэффициент эмиссии.",
            "dry_matter_t": 612_400.0 if total_ha else 0.0,
            "co2e_t": 1_043_900.0,
            "species": [{"label": "CO2", "name": "углекислый газ", "tonnes": 981_200.0}],
        },
        "method": {"area": "Площадь считается в UTM зоне сцены.", "period": "Гарь попадает в период."},
    }


def test_report_is_a_valid_pdf() -> None:
    body = pdf_report.render(_report())

    assert body.startswith(b"%PDF-")
    assert body.rstrip().endswith(b"%%EOF")


def test_territory_name_is_written_into_the_document_title() -> None:
    """Название территории должно быть в метаданных файла: справку узнают
    по вкладке просмотрщика раньше, чем откроют первую страницу."""
    report = _report()

    body = pdf_report.render(report)

    # fpdf2 пишет /Title шестнадцатеричной строкой UTF-16BE, поэтому ищем её в этом виде.
    assert report["territory"]["name"].encode("utf-16-be").hex().encode() in body


def test_empty_result_still_produces_a_report() -> None:
    """Пустой ответ - тоже ответ: справка обязана назвать территорию и период,
    даже когда контуров не нашлось."""
    body = pdf_report.render(_report(total_ha=0.0))

    assert body.startswith(b"%PDF-")


def test_period_reads_as_a_date_not_as_iso() -> None:
    assert pdf_report._period("2020-04-01", "2020-10-31") == "с 1 апреля по 31 октября 2020 года"
    assert pdf_report._period("2019-04-01", "2024-11-02").startswith("с 1 апреля 2019 года по")


def test_thousands_are_split_by_a_non_breaking_space() -> None:
    """Обычный пробел позволял переносу разорвать число пополам."""
    assert pdf_report._int(133181) == "133 181"
    assert pdf_report._pct(0.0021, 2) == "0,21 %"
