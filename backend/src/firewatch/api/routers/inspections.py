import secrets
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.models import Inspection
from firewatch.db.session import get_session
from firewatch.services import events

router = APIRouter(prefix="/api/v1/inspections", tags=["Осмотры"])
Session = Annotated[AsyncSession, Depends(get_session)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-85, le=85, allow_inf_nan=False)]
Coordinates = tuple[Longitude, Latitude]


class InspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    event_id: str = Field(min_length=1, max_length=80)
    purpose: Literal["damage", "recovery", "boundary"]
    note: str = Field(default="", max_length=1000)
    site: Coordinates
    access: Coordinates | None = None

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        return value.strip()


def serialize(row: Inspection) -> dict:
    return {
        "id": str(row.id),
        "share_token": row.share_token,
        "event_id": row.event_id,
        "purpose": row.purpose,
        "note": row.note,
        "site": row.site,
        "access": row.access,
        "snapshot": row.snapshot,
        "created_at": row.created_at.isoformat(),
    }


def same_request(row: Inspection, body: InspectionCreate) -> bool:
    return all(
        getattr(row, key) == value for key, value in body.model_dump(mode="json").items() if key != "id"
    )


@router.post("", status_code=201, summary="Сохранить задание; повтор с тем же id не создаёт дубль")
async def create(body: InspectionCreate, session: Session, response: Response):
    response.headers["Cache-Control"] = "no-store"
    existing = await session.get(Inspection, body.id)
    if existing:
        if not same_request(existing, body):
            raise HTTPException(409, "Это задание уже сохранено с другими данными. Создайте новое.")
        return serialize(existing)
    data = await events.index(session)
    event = next((e for e in data["events"] if e["id"] == body.event_id), None)
    if event is None:
        raise HTTPException(404, "Паспорт не найден. Откройте актуальный паспорт и повторите.")
    if not event["scene_ids"]:
        raise HTTPException(422, "Для выбора участка нужен контур гари Sentinel.")
    # Exact stored burn geometry, not the simplified display polygon; 30m allows for display rounding.
    valid = (
        await session.execute(
            text("""
        SELECT EXISTS (SELECT 1 FROM burn_areas WHERE scene_id=ANY(:ids)
            AND ST_DWithin(geom::geography,
                ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,30))
    """),
            {"ids": event["scene_ids"], "lon": body.site[0], "lat": body.site[1]},
        )
    ).scalar_one()
    if not valid:
        raise HTTPException(
            422, "Место осмотра должно быть внутри гари или у её границы. Выберите окрашенный участок."
        )
    if body.access:
        distance = (
            await session.execute(
                text("""
            SELECT ST_Distance(ST_SetSRID(ST_MakePoint(:x,:y),4326)::geography,
                ST_SetSRID(ST_MakePoint(:a,:b),4326)::geography)
        """),
                {"x": body.site[0], "y": body.site[1], "a": body.access[0], "b": body.access[1]},
            )
        ).scalar_one()
        if distance > 50000:
            raise HTTPException(422, "Место остановки дальше 50 км от осмотра. Проверьте координаты.")
    detail = await events.detail(session, event, data["method"])
    snapshot = {key: detail[key] for key in ("date_from", "date_to", "burn", "bbox")}
    values = body.model_dump() | {"share_token": secrets.token_urlsafe(32), "snapshot": snapshot}
    await session.execute(
        insert(Inspection).values(**values).on_conflict_do_nothing(index_elements=[Inspection.id])
    )
    await session.commit()
    row = await session.get(Inspection, body.id)
    if not same_request(row, body):
        raise HTTPException(409, "Это задание уже сохранено с другими данными. Создайте новое.")
    return serialize(row)


@router.get("", summary="Последние задания для паспорта")
async def for_event(event_id: str, session: Session, response: Response):
    response.headers["Cache-Control"] = "no-store"
    rows = (
        await session.execute(
            select(Inspection)
            .where(Inspection.event_id == event_id)
            .order_by(Inspection.created_at.desc())
            .limit(30)
        )
    ).scalars()
    return {"items": [serialize(row) for row in rows]}


@router.get("/shared/{token}", summary="Карточка по секретной ссылке, только чтение")
async def shared(token: str, session: Session, response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    row = (
        await session.execute(select(Inspection).where(Inspection.share_token == token))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Карточка не найдена. Проверьте, полностью ли скопирована ссылка.")
    return serialize(row)
