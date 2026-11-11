"""Accurate read-only gateway entrypoint."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.accurate_client import AccurateClient
from app.config import get_settings
from app.routes import router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="3.2.0",
    description="Independent read-only Accurate Online gateway for Eternal Production V3",
)


@app.get("/health")
async def health() -> dict[str, Any]:
    mode = (settings.gateway_mode or "fixture").strip().lower()
    if mode != "live":
        mode = "fixture"
    live_ready = AccurateClient(settings).configured() if mode == "live" else False
    return {
        "status": "ok",
        "service": "accurate-read-gateway",
        "mode": mode,
        "live_credentials_present": live_ready,
        "live_verified": False,
        "read_only": True,
    }


app.include_router(router)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.listen_host,
        port=settings.listen_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
