"""The page itself, its static files and the error shapes of the API."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError

from ..omarchy_detect import host_javascript
from ..rules import (
    redact,
)

STATIC = Path(__file__).resolve().parent.parent / "static"


def register_web(app, ctx):
    @app.exception_handler(ValidationError)
    async def invalid(request, exc):
        # Pydantic errors may contain submitted secrets in input/context.
        return JSONResponse(
            {
                "detail": "; ".join(
                    ".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors()
                )
            },
            status_code=422,
        )

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": redact(str(exc))[:500]}, status_code=400)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/omarchy-host.js")
    def omarchy_host():
        return PlainTextResponse(host_javascript(), media_type="application/javascript")

    from ..public_static import PublicStaticFiles

    app.mount("/static", PublicStaticFiles(directory=STATIC), name="static")
