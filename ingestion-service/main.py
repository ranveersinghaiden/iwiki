import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings
from app.db.database import engine
from app.pipeline.ingestion_pipeline import IngestionPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _run_incremental_sync() -> None:
    """APScheduler job — incremental sync on cron."""
    logger.info("[main] scheduled incremental sync triggered")
    pipeline = IngestionPipeline.build()
    await pipeline.run(full_sync=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("[main] ingestion-service starting")
    # Schedule incremental sync via cron (default: every hour — see SYNC_CRON)
    scheduler.add_job(
        _run_incremental_sync,
        trigger="cron",
        **_parse_cron(settings.sync_cron),
        id="incremental_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[main] scheduler started with cron=%s", settings.sync_cron)
    yield
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("[main] ingestion-service stopped")


def _parse_cron(cron_expr: str) -> dict:
    """Convert '0 * * * *' → APScheduler cron kwargs."""
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"[main] invalid SYNC_CRON: {cron_expr!r} — must be 5-part cron expression")
    keys = ("minute", "hour", "day", "month", "day_of_week")
    return dict(zip(keys, parts))


app = FastAPI(
    title="iWiki Ingestion Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):
    logger.error("[main] unhandled exception: %s", exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

