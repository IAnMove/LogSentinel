"""Destinations, deliveries, backups and the notification templates."""

from __future__ import annotations

import asyncio
import os
import time

from fastapi import HTTPException

from ..store import BACKUPS_KEPT, uid


def register_admin(app, ctx):
    store, outbox = ctx.store, ctx.outbox

    @app.post("/api/destinations/{id}/test")
    async def test_destination(id: str):
        dest = store.get("destination", id)
        if not dest:
            raise HTTPException(404)
        return await outbox.test(dest)

    @app.post("/api/deliveries/{id}/retry")
    def retry_delivery(id: str):
        with store.connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE id=?", (id,)).fetchone()
            if not row:
                raise HTTPException(404)
            dest = store.get("destination", row["destination_id"])
            if not dest or not dest["enabled"]:
                raise HTTPException(400, "Destination disabled")
            if row["status"] == "delivered":
                # Retrying resets the row to pending whatever it was, and this
                # one already reached its destination: a second copy of the
                # alert, not a retry.
                raise HTTPException(409, "This notification was already delivered")
            db.execute(
                "UPDATE deliveries SET status='pending',next_try=? WHERE id=?",
                (time.time(), id),
            )
        store.audit("manual_delivery_retry", id)
        return {"ok": True}

    @app.post("/api/backup")
    async def backup():
        folder = store.directory / "backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        try:
            path = await asyncio.to_thread(
                store.backup, folder / ("backup-" + uid() + ".db")
            )
        except ValueError as exc:
            raise HTTPException(507, str(exc)) from None
        removed = await asyncio.to_thread(store.rotate_backups, folder)
        store.audit("backup", path.name)
        return {
            "filename": path.name,
            "message": "Backup contains original logs, the access key and configuration secrets. Stored locally with owner-only permissions. Rotate credentials after restore. Only the "
            + str(BACKUPS_KEPT)
            + " newest backups are kept.",
            "removed": removed,
        }

    @app.get("/api/templates/{kind}")
    def template(kind: str):
        if kind == "hermes":
            return {
                "platforms": {
                    "webhook": {
                        "enabled": True,
                        "extra": {
                            "routes": {
                                "logsentinel": {
                                    "secret": "REPLACE_IN_HERMES",
                                    "deliver_only": True,
                                    "deliver": "telegram",
                                    "prompt": "[{severity}] {machine}: {title} — {summary}",
                                    "deliver_extra": {"chat_id": "REPLACE_CHAT"},
                                }
                            }
                        },
                    }
                }
            }
        if kind == "n8n":
            return {
                "name": "LogSentinel notifications",
                "active": False,
                "nodes": [
                    {
                        "id": "receive",
                        "name": "Receive LogSentinel",
                        "type": "n8n-nodes-base.webhook",
                        "typeVersion": 2,
                        "position": [0, 0],
                        "parameters": {
                            "httpMethod": "POST",
                            "path": "logsentinel",
                            "authentication": "headerAuth",
                            "responseMode": "onReceived",
                        },
                    },
                    {
                        "id": "message",
                        "name": "Configure destination",
                        "type": "n8n-nodes-base.noOp",
                        "typeVersion": 1,
                        "position": [250, 0],
                        "parameters": {},
                    },
                ],
                "connections": {
                    "Receive LogSentinel": {
                        "main": [
                            [
                                {
                                    "node": "Configure destination",
                                    "type": "main",
                                    "index": 0,
                                }
                            ]
                        ]
                    }
                },
                "settings": {"executionOrder": "v1"},
            }
        raise HTTPException(404)
