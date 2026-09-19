from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.session import get_session
from firewatch.services import work_map

router = APIRouter(prefix="/api/v1/events", tags=["Участки работ"])
Session = Annotated[AsyncSession, Depends(get_session)]


async def handle(event_id, session, start):
    try:
        return await work_map.request(session, event_id, start)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{event_id}/work-map", status_code=202)
async def create(event_id: str, session: Session):
    return await handle(event_id, session, True)


@router.get("/{event_id}/work-map")
async def status(event_id: str, session: Session):
    return await handle(event_id, session, False)
