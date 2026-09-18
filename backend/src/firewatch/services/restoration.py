from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from importlib import resources
from typing import Any

from firewatch.domain.catalog import LC_GROUP_LABELS, SEVERITY_LABELS


@lru_cache
def load_rules() -> dict[str, Any]:
    return json.loads(
        resources.files("firewatch.assets").joinpath("restoration_rules.json").read_text("utf-8")
    )


def build_plan(landcover_ha: dict[tuple[int, str], float]) -> dict[str, Any]:
    """landcover_ha: (степень, группа покрова) -> гектары внутри запроса."""
    rules = load_rules()
    by_action: dict[str, dict[str, Any]] = defaultdict(lambda: {"area_ha": 0.0, "breakdown": []})
    for (severity, group), area_ha in sorted(landcover_ha.items()):
        if area_ha <= 0:
            continue
        action = rules["rules"].get(group, rules["rules"]["other"])[str(severity)]
        by_action[action]["area_ha"] += area_ha
        by_action[action]["breakdown"].append(
            {
                "landcover": group,
                "landcover_label": LC_GROUP_LABELS[group],
                "severity": severity,
                "severity_label": SEVERITY_LABELS[severity],
                "area_ha": round(area_ha, 2),
            }
        )

    items = []
    for action, data in by_action.items():
        spec = rules["actions"][action]
        items.append(
            {
                "action": action,
                "label": spec["label"],
                "area_ha": round(data["area_ha"], 2),
                "rate_per_ha": spec["rate_per_ha"],
                "cost": round(data["area_ha"] * spec["rate_per_ha"]),
                "counts_as_damage": spec["damage"],
                "breakdown": sorted(data["breakdown"], key=lambda b: -b["area_ha"]),
            }
        )
    items.sort(key=lambda item: (-item["cost"], -item["area_ha"]))
    return {
        "currency": rules["currency"],
        "disclaimer": rules["disclaimer"],
        "total_cost": sum(i["cost"] for i in items),
        "damage_area_ha": round(sum(i["area_ha"] for i in items if i["counts_as_damage"]), 2),
        "natural_area_ha": round(sum(i["area_ha"] for i in items if i["action"] == "natural"), 2),
        "items": items,
    }
