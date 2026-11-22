"""FastAPI app: /api routes, and the built frontend at / when it exists."""
import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scripts.generate_data import generate

from . import config, db
from .ai.llm import LLMUnavailable, chat, ollama_ok
from .routers import agent, ask, catalog, dashboard, erp_mock, forecast, orders


def reset_data() -> None:
    """Rewrite all tables inside the existing DB file (never replace it: Windows locks open files)."""
    config.DATA_DIR.mkdir(exist_ok=True)
    with db.rw() as conn:
        inbox = generate(conn)
    (config.DATA_DIR / "inbox.json").write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
    forecast.clear_caches()
    forecast.warm_caches()


def warm_model() -> None:
    """Load the model into GPU memory at startup: a cold load from a hard disk can exceed the 40 s answer limit."""
    if ollama_ok():
        try:
            chat([{"role": "user", "content": "hi"}], json_mode=False, num_predict=1)
        except LLMUnavailable:
            pass  # Ask falls back to rules; nothing to do here


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not config.DB_PATH.exists():
        reset_data()
    else:
        forecast.warm_caches()
    threading.Thread(target=warm_model, daemon=True).start()
    yield


app = FastAPI(title="SMC AI Commerce Demo", lifespan=lifespan)
for r in (catalog, orders, dashboard, forecast, erp_mock, ask, agent):
    app.include_router(r.router)


@app.get("/api/health")
def health() -> dict:
    try:
        with db.ro() as conn:
            conn.execute("SELECT 1 FROM orders LIMIT 1")
        db_status = "ok"
    except Exception:
        db_status = "missing"
    return {"db": db_status, "ollama": "ok" if ollama_ok() else "unavailable", "model": config.OLLAMA_MODEL}


@app.post("/api/admin/reset")
def reset() -> dict:
    reset_data()
    return {"ok": True}


# Mounted last so /api routes win.
if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
