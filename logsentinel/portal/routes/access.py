"""Who may call the API: host guard, CSRF, sessions and the login form."""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..limits import BodyLimit


def cache_policy(path, status):
    """Everything is private and fresh except the public static files.

    Those carry no data: scripts and styles are revalidated (the server answers
    a conditional request with a tiny 304), and the artwork, whose file names
    carry a version, may be reused for a day. Before this, every page load
    downloaded about 400 KB of scripts and the theme's images again.
    """
    if path.startswith("/static/") and status in (200, 304):
        return "public, max-age=86400" if path.endswith(".png") else "no-cache"
    return "no-store"


def register_access(app, ctx):
    auth = ctx.auth
    # Failed logins in the last minute, per client address.
    attempts = {}

    app.add_middleware(BodyLimit)

    async def admit(request, call_next):
        """Refuse what may not pass; otherwise hand the request on."""
        host = request.url.hostname
        if host not in ("localhost", "127.0.0.1", "::1"):
            return JSONResponse(
                {"detail": "Untrusted host; use a loopback SSH tunnel"}, status_code=400
            )
        path = request.url.path
        now = time.time()
        await asyncio.to_thread(auth.prune)
        for ip, stamps in list(attempts.items()):
            recent = [x for x in stamps if x > now - 60]
            if recent:
                attempts[ip] = recent
            else:
                attempts.pop(ip, None)
        login_post = path == "/login" and request.method == "POST"
        if login_post or path.startswith("/api/"):
            if path.startswith("/api/"):
                token = request.cookies.get("sentinel_session", "")
                if not await asyncio.to_thread(auth.valid, token):
                    return JSONResponse({"detail": "Login required"}, status_code=401)
            if request.method not in ("GET", "HEAD"):
                origin = request.headers.get("origin")
                if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                    return JSONResponse({"detail": "Origin mismatch"}, status_code=403)
                if request.headers.get("X-LogSentinel") != "portal":
                    return JSONResponse(
                        {"detail": "CSRF header required"}, status_code=403
                    )
        return await call_next(request)

    @app.middleware("http")
    async def guard(request, call_next):
        # Every response gets the protective headers, refusals included: the
        # early 400/401/403 answers used to leave here without them.
        response = await admit(request, call_next)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = cache_policy(
            request.url.path, response.status_code
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.post("/login")
    async def login(request: Request):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Origin mismatch")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Send an access key object")
        # Some servers and test clients give no peer address.
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        old = attempts.get(ip, [])
        old = [x for x in old if x > now - 60]
        if len(old) >= 10:
            raise HTTPException(429, "Try again later")
        token = body.get("token", "")
        session = await asyncio.to_thread(auth.login, token)
        if session is None:
            # Only failures spend the budget, so signing in never locks the
            # operator out; reaching the panel through a tunnel makes every
            # client share one address, hence the low ceiling on failures.
            attempts[ip] = old + [now]
            raise HTTPException(401, "Invalid access key")
        result = JSONResponse({"ok": True})
        result.set_cookie(
            "sentinel_session",
            session,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=86400,
        )
        return result

    @app.post("/api/logout")
    def logout(request: Request):
        auth.logout(request.cookies.get("sentinel_session", ""))
        result = JSONResponse({"ok": True})
        result.delete_cookie("sentinel_session")
        return result

    @app.post("/api/access-key/rotate")
    def rotate_access_key():
        token = auth.rotate()
        return {
            "token": token,
            "message": "Shown once. Previous access key is now invalid and open sessions were signed out.",
        }
