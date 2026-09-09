"""Only flat application assets are public; local production material is not."""

from pathlib import PurePosixPath
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class PublicStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        item = PurePosixPath(path)
        if (
            len(item.parts) != 1
            or item.name.startswith(".")
            or item.suffix.lower()
            not in {
                ".js",
                ".css",
                ".html",
                ".png",
                ".svg",
                ".ico",
                ".woff",
                ".woff2",
            }
        ):
            raise HTTPException(404)
        return await super().get_response(path, scope)
