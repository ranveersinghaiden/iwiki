import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.cache import aclose_redis
from app.db.database import engine
from app.llm import aclose_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("[main] query-service starting")
    yield
    await aclose_client()
    await aclose_redis()
    await engine.dispose()
    logger.info("[main] query-service stopped")


app = FastAPI(
    title="iWiki Query Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):
    logger.error("[main] unhandled exception: %s", exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

