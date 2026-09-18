from __future__ import annotations

SEVERITY_LABELS = {1: "слабая", 2: "средняя", 3: "сильная"}
SEVERITY_COLORS = {1: (255, 209, 102), 2: (247, 127, 0), 3: (157, 2, 8)}

LC_GROUP_BY_CODE = {
    10: "forest",
    20: "shrub",
    30: "grass",
    40: "crop",
    50: "built",
    60: "bare",
    80: "water",
    90: "wetland",
}
LC_GROUP_LABELS = {
    "forest": "лес",
    "shrub": "кустарник",
    "grass": "степь и луга",
    "crop": "пашня",
    "built": "застройка",
    "bare": "открытый грунт",
    "water": "вода",
    "wetland": "пойма и плавни",
    "other": "прочее",
}

HOTSPOT_KIND_LABELS = {"fire": "природный пожар", "technogenic": "техногенный источник", "glint": "блик"}


def lc_group(code: int) -> str:
    return LC_GROUP_BY_CODE.get(int(code), "other")
