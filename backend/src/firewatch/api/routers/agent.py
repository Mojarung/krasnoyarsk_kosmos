from __future__ import annotations

from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from firewatch.agent.service import chat
from firewatch.api.schemas import ChatRequest

router = APIRouter(prefix="/api/v1", tags=["Агент"])


@router.post(
    "/agent/chat",
    response_class=EventSourceResponse,
    summary="Запрос текстом: агент сам выбирает территорию и период, наводит карту и пишет справку",
)
async def agent_chat(body: ChatRequest) -> AsyncIterable[ServerSentEvent]:
    async for event in chat(body.message):
        yield ServerSentEvent(data=event["data"], event=event["event"])
