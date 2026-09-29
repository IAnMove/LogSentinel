"""Request size limit that reads nothing ahead of authentication.

The limit is enforced as the handler consumes the body, so a route that
rejects a bad token before reading never buffers what the client is sending.
"""

from fastapi import HTTPException
from fastapi.responses import JSONResponse

MAX_REQUEST_BYTES = 4_000_000


class BodyLimit:
    def __init__(self, app, limit=MAX_REQUEST_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            response = JSONResponse({"detail": "Request exceeds 4 MB"}, status_code=413)
            return await response(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise HTTPException(413, "Request exceeds 4 MB")
            return message

        await self.app(scope, limited, send)
