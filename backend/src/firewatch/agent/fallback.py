"""Разбор запроса без LLM: регион по названию, период по годам, месяцам и сезонам."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from firewatch.agent.regions import AOI_ID, Region, all_regions, find_region

MONTH_STEMS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "май": 5, "мае": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
SEASONS = {"весн": (3, 5), "лет(?:о|ом|а|н)": (6, 8), "осен": (9, 11), "сезон": (4, 10)}
YEAR_PATTERN = re.compile(r"\b(20[12]\d)\b")
FIRE_SEASON = (4, 10)
# Слова предметной области. Вопрос без региона, периода, намерения и этих основ считается посторонним.
DOMAIN_PATTERN = re.compile(
    r"пожар|гар[ьией]|гор[ие]|горел|огн|огон|пал[ыа]?|выгор|термоточ|очаг|дым|техноген|факел|блик|степен|площад|гектар|га"
    r"|лес|степ[ьи]|пашн|покров|спутник|снимк|сцен|viirs|sentinel|справк|отч[её]т|выгруз|контур|сводк|статист|мониторинг"
)
INTENT_PATTERNS = {
    "largest": re.compile(r"крупнейш|наибольш|максимальн|сам\w+\s+(?:крупн|больш|массив|сильн|мощн|обширн)"),
    "technogenic": re.compile(r"техноген|факел|ложн|отфильтр|отсея|промышл|блик"),
    "restoration": re.compile(r"восстан|лесовосст|посадк|ущерб|затрат"),
}


@dataclass(frozen=True)
class ParsedRequest:
    region: Region
    date_from: date
    date_to: date
    region_recognized: bool
    period_recognized: bool
    intent: str = "overview"
    on_topic: bool = True


def _named_months(text: str) -> tuple[int, int] | None:
    found = sorted({number for stem, number in MONTH_STEMS.items() if re.search(rf"\b{stem}", text)})
    return (found[0], found[-1]) if found else None


def _season(text: str) -> tuple[int, int] | None:
    return next((span for stem, span in SEASONS.items() if re.search(rf"\b{stem}", text)), None)


def parse_request(message: str, data_range: tuple[date, date]) -> ParsedRequest:
    text = message.lower()
    region = find_region(text)
    years = sorted({int(y) for y in YEAR_PATTERN.findall(text)})
    named_months = _named_months(text)
    months = named_months or _season(text)

    if years:
        first_month, last_month = months or FIRE_SEASON
        date_from = date(years[0], first_month, 1)
        date_to = date(years[-1], last_month, calendar.monthrange(years[-1], last_month)[1])
    elif months:
        year = data_range[1].year
        date_from = date(year, months[0], 1)
        date_to = date(year, months[1], calendar.monthrange(year, months[1])[1])
    else:
        date_from, date_to = data_range

    return ParsedRequest(
        region=region or next(r for r in all_regions() if r.id == AOI_ID),
        date_from=date_from,
        date_to=date_to,
        region_recognized=region is not None,
        period_recognized=bool(years or months),
        intent=(
            intent := next(
                (name for name, pattern in INTENT_PATTERNS.items() if pattern.search(text)), "overview"
            )
        ),
        # Сезон без года, региона и предметных слов темой не считается: «стих про осень» не про пожары.
        on_topic=bool(region or years or named_months or intent != "overview" or DOMAIN_PATTERN.search(text)),
    )
