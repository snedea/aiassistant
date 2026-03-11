from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from app.config import get_settings
from app.database import init_db, get_engine
from app.services.vectorstore import init_vectorstore
from app.services.http_client import init_ollama_client, close_ollama_client, init_slack_client, close_slack_client
from app.services.scanner import start_scanner, stop_scanner
from app.services.slack_bot import start_slack_bot, stop_slack_bot
from app.services.rules_engine import ensure_default_rules
from app.services.quiet_hours import ensure_quiet_hours_config
from app.services.llm_rate_limiter import get_budget_config
from app.routers.chat import router as chat_router
from app.routers.memory import router as memory_router
from app.routers.sources import router as sources_router
from app.routers.notifications import router as notifications_router
from app.routers.admin import router as admin_router
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path("data").mkdir(parents=True, exist_ok=True)
    init_db()
    init_vectorstore()
    init_ollama_client(settings.ollama_base_url)
    init_slack_client()
    with Session(get_engine()) as session:
        ensure_default_rules(session)
        ensure_quiet_hours_config(session)
        get_budget_config(session)
    scanner_tasks = await start_scanner()
    slack_handler = await start_slack_bot()
    yield
    await close_ollama_client()
    await close_slack_client()
    await stop_slack_bot()
    await stop_scanner(scanner_tasks)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Assistant", version="0.1.0", lifespan=lifespan)

    settings = get_settings()
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/vectorstore")
    async def health_vectorstore() -> dict[str, str | int]:
        from app.services.vectorstore import collection_count
        count = collection_count()
        return {"status": "ok", "document_count": count}

    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(sources_router)
    app.include_router(notifications_router)
    app.include_router(admin_router)
    return app


app = create_app()
