import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from firewatch.api.routers import (
    acquisitions,
    agent,
    analysis,
    events,
    inspections,
    meta,
    ogc,
    realtime,
    scenes,
    vegetation,
    work_map,
    zones,
)
from firewatch.config import get_settings
from firewatch.infra import s3
from firewatch.infra.broker import broker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

DESCRIPTION = """
Сервис отвечает на пространственно-временной запрос: полигон или bbox плюс интервал дат.

- `POST /api/v1/query` - термоточки, контуры гарей и справка одним вызовом
- `GET /api/v1/burns?format=shp` - выгрузка контуров в GeoJSON, Shapefile, GeoPackage, KML
- `GET /api/v1/report?format=xlsx` - справка с площадями в гектарах по степеням поражения
- `GET /api/v1/response-plan` - план реагирования по свежим очагам: приоритет, прогноз фронта, способ тушения
- `POST /api/v1/acquisitions` - анализ произвольной области по свежим снимкам Sentinel-2
- `/ogc` - OGC API Features для подключения слоёв в QGIS и ArcGIS
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(s3.ensure_bucket)
    await broker.start()
    yield
    await broker.stop()


app = FastAPI(
    title="Мониторинг природных пожаров", version="0.1.0", description=DESCRIPTION, lifespan=lifespan
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"]
)

for module in (
    analysis,
    scenes,
    acquisitions,
    realtime,
    zones,
    agent,
    ogc,
    meta,
    events,
    inspections,
    vegetation,
    work_map,
):
    app.include_router(module.router)
