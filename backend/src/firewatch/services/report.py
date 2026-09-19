from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.domain.catalog import LC_GROUP_LABELS, SEVERITY_LABELS
from firewatch.services import emissions, metrics, territory
from firewatch.services import query as q
from firewatch.services.restoration import build_plan

METHOD = {
    "area": (
        "Площадь считается по векторным контурам в метрической проекции UTM зоны сцены (EPSG:32637 или EPSG:32638). "
        "Контур целиком внутри запроса даёт площадь, равную числу пикселей маски, умноженному на 0,04 га. "
        "Контур на границе запроса обрезается, площадь пересечения пересчитывается в той же проекции."
    ),
    "period": "Гарь попадает в период, если интервал между снимками «до» и «после» пересекается с интервалом запроса.",
    "hotspots": (
        "Термоточка - центр пикселя VIIRS 375 м. Очаг - группа точек одного дня ближе {eps:.0f} м друг к другу. "
        "Техногенные источники и блики исключены из числа природных пожаров и показаны отдельно."
    ),
}


def _severity_block(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    by_severity = defaultdict(float)
    for row in rows:
        by_severity[row["severity"]] += row["area_ha"]
    total = sum(by_severity.values())
    block = [
        {
            "severity": k,
            "label": SEVERITY_LABELS[k],
            "area_ha": round(by_severity[k], 2),
            "share": round(by_severity[k] / total, 4) if total else 0.0,
        }
        for k in (1, 2, 3)
    ]
    return block, total


def _landcover_in_query(
    rows: list[dict[str, Any]], crosstab: list[dict[str, Any]], totals: list[dict[str, Any]]
) -> dict[tuple[int, str], float]:
    """Таблица «степень x покров» хранится на сцену целиком. Для сцен на границе запроса
    она масштабируется долей площади степени, попавшей в запрос."""
    full = {(t["scene_id"], t["severity"]): t["area_ha"] for t in totals}
    share = {
        (r["scene_id"], r["severity"]): (r["area_ha"] / full[(r["scene_id"], r["severity"])])
        for r in rows
        if full.get((r["scene_id"], r["severity"]))
    }
    result: dict[tuple[int, str], float] = defaultdict(float)
    for cell in crosstab:
        factor = share.get((cell["scene_id"], cell["severity"]), 0.0)
        result[(cell["severity"], cell["lc_group"])] += cell["area_ha"] * factor
    return result


def _hotspot_block(summary: list[dict[str, Any]], satellites: dict[str, int]) -> dict[str, Any]:
    counts = defaultdict(int)
    clusters = defaultdict(int)
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"fire": 0, "technogenic": 0, "glint": 0})
    for row in summary:
        counts[row["kind"]] += row["n"]
        clusters[row["kind"]] += row["clusters"]
        by_day[row["day"].isoformat()][row["kind"]] += row["n"]
    raw_total = sum(counts.values())
    return {
        "raw_total": raw_total,
        "fire": counts["fire"],
        "technogenic": counts["technogenic"],
        "glint": counts["glint"],
        "fire_clusters": clusters["fire"],
        "false_dispatches_prevented": clusters["technogenic"] + clusters["glint"],
        "filtered_share": round((raw_total - counts["fire"]) / raw_total, 4) if raw_total else 0.0,
        "by_satellite": satellites,
        "by_day": [{"day": day, **values} for day, values in sorted(by_day.items())],
    }


async def build_report(session: AsyncSession, query: q.SpatioTemporalQuery) -> dict[str, Any]:
    severity_rows = await q.fetch_severity_by_scene(session, query)
    scene_ids = sorted({r["scene_id"] for r in severity_rows})
    crosstab, totals = await q.fetch_landcover(session, scene_ids)
    summary = await q.fetch_hotspot_summary(session, query)
    satellites = await q.fetch_satellites(session, query)

    severity_block, total_ha = _severity_block(severity_rows)
    landcover = _landcover_in_query(severity_rows, crosstab, totals)
    by_landcover = defaultdict(float)
    for (_, group), area_ha in landcover.items():
        by_landcover[group] += area_ha
    severity_ha = [s["area_ha"] for s in severity_block]
    burn_metrics = await metrics.fetch_burn_metrics(session, query, total_ha, severity_ha)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "territory": territory.describe(query.geometry),
        "query": {
            "geometry": query.geometry,
            "date_from": query.date_from.isoformat(),
            "date_to": query.date_to.isoformat(),
        },
        "burn": {
            "total_ha": round(total_ha, 2),
            "scenes": len(scene_ids),
            **burn_metrics,
            "by_severity": severity_block,
            "by_landcover": [
                {"landcover": g, "label": LC_GROUP_LABELS[g], "area_ha": round(a, 2)}
                for g, a in sorted(by_landcover.items(), key=lambda kv: -kv[1])
                if a > 0
            ],
        },
        "hotspots": _hotspot_block(summary, satellites) | await metrics.fetch_hotspot_metrics(session, query),
        "quality": await metrics.fetch_quality(session, query),
        "restoration": build_plan(landcover),
        "emissions": emissions.build_estimate(landcover),
        "method": METHOD | {"hotspots": METHOD["hotspots"].format(eps=get_settings().dispatch_cluster_m)},
    }
