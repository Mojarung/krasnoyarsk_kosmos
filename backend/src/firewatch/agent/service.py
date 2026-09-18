from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import text

from firewatch.agent.fallback import parse_request
from firewatch.agent.regions import Region, all_regions, find_region
from firewatch.config import get_settings
from firewatch.db.session import SessionFactory
from firewatch.services.query import SpatioTemporalQuery
from firewatch.services.report import build_report

log = logging.getLogger(__name__)

Event = dict[str, Any]
DEFAULT_RANGE = (date(2019, 4, 1), date(2024, 11, 30))

SYSTEM_PROMPT = """Ты аналитик регионального центра мониторинга природных пожаров (Нижнее Поволжье и Подонье).
Отвечай по-русски, коротко и по делу, только по данным инструментов. Не выдумывай числа.
Всегда вызывай analyze_territory, когда вопрос касается территории или периода: он же наводит карту пользователя.
Даты передавай в формате ГГГГ-ММ-ДД. Если период не назван, бери весь охват данных: {date_min} - {date_max}.
Доступные территории: {regions}.
В ответе назови площадь гари в гектарах, распределение по степеням, число природных очагов и сколько
техногенных срабатываний отфильтровано. Если данных нет, так и скажи."""


async def data_range() -> tuple[date, date]:
    async with SessionFactory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT least(min(acquired_at)::date, min(date_pre)), greatest(max(acquired_at)::date, max(date_post)) "
                    "FROM scenes WHERE status = 'ready'"
                )
            )
        ).one()
    return (row[0], row[1]) if row[0] and row[1] else DEFAULT_RANGE


async def _report(region: Region, date_from: date, date_to: date) -> dict[str, Any]:
    query = SpatioTemporalQuery.build(
        geometry=region.geometry, bbox=None, date_from=date_from, date_to=date_to
    )
    async with SessionFactory() as session:
        return await build_report(session, query)


def _action(region: Region, date_from: date, date_to: date) -> Event:
    return {
        "event": "action",
        "data": {
            "type": "set_query",
            "region_id": region.id,
            "region_name": region.name,
            "geometry": region.geometry,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    }


def _digest(report: dict[str, Any]) -> dict[str, Any]:
    burn, hot = report["burn"], report["hotspots"]
    return {
        "burn_total_ha": burn["total_ha"],
        "burn_by_severity_ha": {s["label"]: s["area_ha"] for s in burn["by_severity"]},
        "burn_contours": burn["contours"],
        "largest_burns": burn["largest"][:3],
        "burned_share_of_territory": burn["burned_share"],
        "natural_fire_hotspots": hot["fire"],
        "natural_fire_clusters": hot["fire_clusters"],
        "technogenic_filtered": hot["technogenic"],
        "glint_filtered": hot["glint"],
        "false_dispatches_prevented": hot["false_dispatches_prevented"],
        "peak_month": hot["peak_month"],
        "restoration_planting_ha": report["restoration"]["damage_area_ha"],
        "restoration_natural_ha": report["restoration"]["natural_area_ha"],
    }


def summarize(region: Region, date_from: date, date_to: date, report: dict[str, Any]) -> str:
    burn, hot, plan = report["burn"], report["hotspots"], report["restoration"]
    period = f"{date_from:%d.%m.%Y} - {date_to:%d.%m.%Y}"
    if not burn["total_ha"] and not hot["raw_total"]:
        return f"{region.name}, {period}: в загруженных сценах нет ни гарей, ни термоточек. Попробуйте расширить период."
    severity = ", ".join(
        f"{s['label']} {s['area_ha']:,.0f} га ({s['share']:.0%})".replace(",", " ")
        for s in burn["by_severity"]
    )
    lines = [
        f"{region.name}, {period}.",
        f"Гари: {burn['total_ha']:,.0f} га в {burn['contours']} контурах. По степеням: {severity}.".replace(
            ",", " ", 1
        ),
        f"Термоточки: {hot['fire']} природных в {hot['fire_clusters']} очагах. Отфильтровано {hot['technogenic']} техногенных "
        f"и {hot['glint']} бликов, это {hot['false_dispatches_prevented']} ложных выездов.",
    ]
    if burn["largest"]:
        top = burn["largest"][0]
        lines.append(
            f"Крупнейшая гарь: {top['area_ha']:,.0f} га, снимок от {top['date_post']}.".replace(",", " ")
        )
    if plan["damage_area_ha"]:
        lines.append(
            f"Под искусственное лесовосстановление попадает {plan['damage_area_ha']:,.0f} га.".replace(
                ",", " "
            )
        )
    return " ".join(lines)


async def _rules(message: str, note: str | None = None) -> AsyncIterator[Event]:
    parsed = parse_request(message, await data_range())
    yield _action(parsed.region, parsed.date_from, parsed.date_to)
    report = await _report(parsed.region, parsed.date_from, parsed.date_to)
    hints = []
    if not parsed.region_recognized:
        hints.append("Регион не распознан, показываю всю территорию мониторинга.")
    if not parsed.period_recognized:
        hints.append("Период не назван, беру весь охват данных.")
    body = " ".join(
        filter(None, [note, *hints, summarize(parsed.region, parsed.date_from, parsed.date_to, report)])
    )
    for word in body.split(" "):
        yield {"event": "token", "data": {"text": word + " "}}
    yield {"event": "done", "data": {"mode": "rules"}}


async def _llm(message: str) -> AsyncIterator[Event]:
    settings = get_settings()
    date_min, date_max = await data_range()
    actions: list[Event] = []

    @tool
    async def analyze_territory(region: str, date_from: str, date_to: str) -> dict[str, Any]:
        """Считает гари и термоточки по территории и периоду и наводит карту пользователя.

        region: название региона или «вся территория». date_from, date_to: ГГГГ-ММ-ДД.
        """
        found = find_region(region) or all_regions()[0]
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        actions.append(_action(found, start, end))
        return {"region": found.name} | _digest(await _report(found, start, end))

    model = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "not-needed",
        temperature=0,
        timeout=60,
    )
    prompt = SYSTEM_PROMPT.format(
        date_min=date_min.isoformat(),
        date_max=date_max.isoformat(),
        regions=", ".join(r.name for r in all_regions()),
    )
    agent = create_agent(model=model, tools=[analyze_territory], system_prompt=prompt)

    sent = 0
    async for chunk, _ in agent.astream(
        {"messages": [{"role": "user", "content": message}]}, stream_mode="messages"
    ):
        for action in actions[sent:]:
            yield action
        sent = len(actions)
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content:
            yield {"event": "token", "data": {"text": chunk.content}}
    for action in actions[sent:]:
        yield action
    yield {"event": "done", "data": {"mode": "llm", "model": settings.llm_model}}


async def chat(message: str) -> AsyncIterator[Event]:
    if not get_settings().llm_enabled:
        async for event in _rules(message):
            yield event
        return
    try:
        async for event in _llm(message):
            yield event
    except Exception:
        log.exception("LLM недоступна, отвечаем по правилам")
        async for event in _rules(message, note="Языковая модель недоступна, отвечаю по правилам."):
            yield event
