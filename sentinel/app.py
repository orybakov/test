import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .classifier import default_spoken_text, rule_priority
from .config import Settings
from .engine import Engine
from .store import Store

HERE = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO)


class EventIn(BaseModel):
    source: str = Field(min_length=1, max_length=48, pattern=r"^[\w.\-]+$")
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(default="", max_length=1500)
    level: str = Field(default="auto", pattern=r"^(auto|critical|important|normal|silent)$")
    event_id: str | None = Field(default=None, max_length=128)


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    store.recover()
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    engine = Engine(settings, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(engine.loop()) if start_worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Voice Sentinel", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.engine = engine

    def authorized(key: str | None):
        if not key or not hmac.compare_digest(key.encode(), settings.api_key.encode()):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @app.get("/health")
    def health():
        return {"status": "ok", "tts_provider": settings.tts_provider}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "static" / "index.html").read_text(encoding="utf-8")

    @app.get("/static/{name}")
    def static(name: str):
        if name not in {"style.css", "app.js"}:
            raise HTTPException(status_code=404)
        return FileResponse(HERE / "static" / name)

    @app.post("/api/events", status_code=201)
    def ingest(event: EventIn, x_api_key: str | None = Header(default=None)):
        authorized(x_api_key)
        priority = rule_priority(event.title, event.message, event.level)
        speech = default_spoken_text(event.source, event.title, event.message)
        stored, created = store.insert(event.source, event.event_id, event.title,
                                       event.message, event.level, priority, speech)
        return {"id": stored["id"], "created": created, "priority": stored["priority"],
                "status": stored["status"]}

    @app.get("/api/events")
    def events(x_api_key: str | None = Header(default=None)):
        authorized(x_api_key)
        return {"events": store.list(), "stats": store.stats(),
                "tts_provider": settings.tts_provider,
                "telegram_enabled": bool(settings.telegram_token and settings.telegram_chat_id),
                "llm_enabled": bool(settings.llm_base_url and settings.llm_model)}

    @app.get("/api/events/{event_id}/audio")
    def audio(event_id: int, x_api_key: str | None = Header(default=None)):
        authorized(x_api_key)
        event = store.get(event_id)
        if not event or not event["audio_file"]:
            raise HTTPException(status_code=404)
        # Never use an externally supplied path; only a server-generated numeric basename.
        path = settings.audio_dir / f"{event_id}.wav"
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="audio/wav")

    @app.post("/api/digest")
    async def digest(x_api_key: str | None = Header(default=None)):
        authorized(x_api_key)
        async with engine._lock:
            return {"digested": await engine.flush_digest()}

    @app.post("/api/demo")
    def demo(x_api_key: str | None = Header(default=None)):
        authorized(x_api_key)
        stored, _ = store.insert("DEMO", None, "Проверка голосового ассистента",
                   "Система запущена, уведомления работают. Это тестовое событие.",
                   "important", "important",
                   "Система запущена. Голосовые уведомления работают. Это тестовое событие.")
        return {"id": stored["id"], "status": stored["status"]}

    return app


app = create_app()
