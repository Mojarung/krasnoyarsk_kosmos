"""Выбросы пожара в атмосферу по площади гари.

Схема принята в GFED и Copernicus GFAS, по ней считает выбросы GWIS:

    сгоревшая биомасса = площадь × запас горючего материала × полнота сгорания
    выброс вещества     = сгоревшая биомасса × эмиссионный фактор

Запас берётся по типу покрова ESA WorldCover, полнота сгорания - по степени поражения:
слабая гарь сжигает подстилку, сильная уносит полог целиком. Обе таблицы и эмиссионные
факторы лежат в firewatch/assets/emission_factors.json, их можно заменить региональными.
"""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from importlib import resources
from typing import Any

from firewatch.domain.catalog import LC_GROUP_LABELS, SEVERITY_LABELS

G_PER_KG_TO_T_PER_T = 1e-3


@lru_cache
def load_factors() -> dict[str, Any]:
    return json.loads(
        resources.files("firewatch.assets").joinpath("emission_factors.json").read_text("utf-8")
    )


def build_estimate(landcover_ha: dict[tuple[int, str], float]) -> dict[str, Any]:
    """landcover_ha: (степень поражения, группа покрова) -> гектары внутри запроса."""
    spec = load_factors()
    fuel, factors = spec["fuel"], spec["factors"]
    completeness = spec["combustion_completeness"]

    totals: dict[str, float] = defaultdict(float)
    by_group_dm: dict[str, float] = defaultdict(float)
    by_group_area: dict[str, float] = defaultdict(float)
    by_severity_dm: dict[int, float] = defaultdict(float)
    dry_matter_t = 0.0

    for (severity, group), area_ha in landcover_ha.items():
        if area_ha <= 0:
            continue
        rule = fuel.get(group, fuel["other"])
        burned_t = area_ha * rule["load_t_ha"] * completeness[str(severity)]
        dry_matter_t += burned_t
        by_group_dm[group] += burned_t
        by_group_area[group] += area_ha
        by_severity_dm[severity] += burned_t
        for key, factor in factors[rule["factors"]].items():
            totals[key] += burned_t * factor * G_PER_KG_TO_T_PER_T

    species = [
        {
            "key": s["key"],
            "label": s["label"],
            "name": s["name"],
            "about": s["about"],
            "tonnes": round(totals[s["key"]], 1),
        }
        for s in spec["species"]
    ]
    co2e_t = sum(totals[s["key"]] * s["gwp100"] for s in spec["species"])

    return {
        "disclaimer": spec["disclaimer"],
        "method": spec["method"],
        "sources": spec["sources"],
        "dry_matter_t": round(dry_matter_t, 1),
        "co2e_t": round(co2e_t, 1),
        "species": species,
        "by_landcover": [
            {
                "landcover": group,
                "label": LC_GROUP_LABELS[group],
                "area_ha": round(by_group_area[group], 2),
                "dry_matter_t": round(burned_t, 1),
                "share": round(burned_t / dry_matter_t, 4) if dry_matter_t else 0.0,
                "load_t_ha": fuel.get(group, fuel["other"])["load_t_ha"],
            }
            for group, burned_t in sorted(by_group_dm.items(), key=lambda kv: -kv[1])
        ],
        "by_severity": [
            {
                "severity": severity,
                "label": SEVERITY_LABELS[severity],
                "dry_matter_t": round(by_severity_dm[severity], 1),
                "completeness": completeness[str(severity)],
            }
            for severity in (1, 2, 3)
        ],
    }
