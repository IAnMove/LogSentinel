"""The model connection, its setup and the analysis controls."""

from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from ..analysis import ReviewClient, safe_error
from ..collect import discovery
from ..models import Settings
from ..network import CheckedAsyncTransport
from ..store import dumps, uid


def model_fingerprint(cfg):
    return hashlib.sha256(
        dumps(
            {
                "llm": cfg.llm.model_dump(),
                "context": cfg.context_tokens,
                "remote": cfg.remote_allowed,
            }
        ).encode()
    ).hexdigest()


def setup_state(store):
    test = json.loads(store.meta("model_test") or "{}")
    return {
        "completed": bool(store.meta("setup_completed")),
        "model_tested": bool(
            test.get("ok")
            and test.get("fingerprint") == model_fingerprint(store.settings())
        ),
        "tested_at": test.get("checked"),
    }


def register_model(app, ctx):
    store, analyzer, monitor, build = ctx.store, ctx.analyzer, ctx.monitor, ctx.build

    async def requested_settings(request):
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict) or not isinstance(body.get("llm", {}), dict):
            raise HTTPException(422, "Settings and llm must be objects")
        clear = body.pop("clear_api_key", False)
        old = store.settings().model_dump()
        merged = dict(old, **body)
        patch = body.get("llm", {})
        merged["llm"] = dict(old["llm"], **patch)
        merged["llm"].pop("api_key_set", None)
        same_endpoint = (
            merged["llm"].get("base_url") == old["llm"]["base_url"]
            and merged["llm"].get("provider") == old["llm"]["provider"]
        )
        # Credentials belong to their endpoint; a blank form must never copy an
        # existing key to a different server, including during discovery/tests.
        merged["llm"]["api_key"] = (
            None
            if clear
            else (
                patch.get("api_key")
                or (old["llm"]["api_key"] if same_endpoint else None)
            )
        )
        if not same_endpoint and "enable_thinking" not in patch:
            merged["llm"]["enable_thinking"] = None
        return Settings(**merged)

    @app.post("/api/settings")
    async def settings(request: Request):
        validated = await requested_settings(request)
        if analyzer.lock.locked() and (
            validated.llm != store.settings().llm
            or validated.context_tokens != store.settings().context_tokens
        ):
            raise HTTPException(
                409, "Wait for the current model request before changing model settings"
            )
        store.set_meta("settings", dumps(validated.model_dump()))
        monitor.reschedule()
        store.audit("settings")
        return {"ok": True}

    @app.get("/api/discovery")
    def detect():
        return discovery()

    @app.post("/api/model/info")
    async def model_info(request: Request, models_only: bool = False):
        cfg = await requested_settings(request)
        llm = cfg.llm
        if (
            urlsplit(llm.base_url).hostname not in ("localhost", "127.0.0.1", "::1")
            and not cfg.remote_allowed
        ):
            raise HTTPException(
                400, "Remote model transmission is disabled in settings"
            )
        base = llm.base_url.rstrip("/")
        maximum = None
        running = None
        models = []
        try:
            async with httpx.AsyncClient(
                transport=CheckedAsyncTransport(),
                timeout=10,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                headers = (
                    {"Authorization": "Bearer " + llm.api_key} if llm.api_key else {}
                )
                if llm.provider == "ollama":
                    response = await client.get(base + "/api/tags", headers=headers)
                    response.raise_for_status()
                    models = [
                        m.get("name", "")
                        for m in response.json().get("models", [])
                        if isinstance(m, dict)
                    ]
                    if models_only:
                        return {
                            "models": sorted(
                                {m for m in models if isinstance(m, str) and m.strip()}
                            ),
                            "provider": llm.provider,
                            "base_url": llm.base_url,
                        }
                    response = await client.post(
                        base + "/api/show", headers=headers, json={"model": llm.model}
                    )
                    if response.status_code != 404:
                        response.raise_for_status()
                    lengths = [
                        v
                        for k, v in (
                            response.json().get("model_info", {})
                            if response.is_success
                            else {}
                        ).items()
                        if k.endswith(".context_length") and type(v) is int and v > 0
                    ]
                    maximum = min(lengths) if lengths else None
                    response = await client.get(base + "/api/ps", headers=headers)
                    if response.is_success:
                        for model in response.json().get("models", []):
                            if model.get("name") in (llm.model, llm.model + ":latest"):
                                running = model.get("context_length")
                else:
                    base = base if base.endswith("/v1") else base + "/v1"
                    response = await client.get(base + "/models", headers=headers)
                    response.raise_for_status()
                    models = [
                        m.get("id", "")
                        for m in response.json().get("data", [])
                        if isinstance(m, dict)
                    ]
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(
                502,
                "No se pudieron consultar los metadatos del modelo configurado; revisa servicio, nombre y credenciales",
            ) from None
        effective = min(
            [cfg.context_tokens]
            + [n for n in (maximum, running) if type(n) is int and n > 0]
        )
        return {
            "models": sorted({m for m in models if isinstance(m, str) and m.strip()}),
            "model": llm.model,
            "provider": llm.provider,
            "base_url": llm.base_url,
            "reported_maximum": maximum,
            "running_context": running,
            "suggested_context": effective,
            "suggested_input_budget": max(
                0, min(cfg.input_budget, effective - llm.max_tokens - 2048)
            ),
            "note": "La sugerencia reserva instrucciones y salida; no mide rendimiento ni garantiza capacidad de RAM. Una API compatible puede no publicar el contexto.",
        }

    @app.post("/api/model/test")
    async def model_test(request: Request):
        if analyzer.lock.locked():
            raise HTTPException(
                409, "Analysis already running; try the model test shortly"
            )
        cfg = await requested_settings(request)
        saved_config = model_fingerprint(cfg) == model_fingerprint(store.settings())
        started = time.monotonic()
        diagnostic_id = uid()
        async with analyzer.lock:
            try:
                result = await ReviewClient(store).call(
                    {
                        "events": [],
                        "purpose": "Synthetic connectivity test, return empty findings",
                    },
                    kind="diagnostic",
                    job=diagnostic_id,
                    **({"config": cfg} if not saved_config else {}),
                )
                from ..models import Verdict

                verdict = Verdict.model_validate(result)
                analyzer.validate_refs(verdict, set())
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
                AttributeError,
            ) as exc:
                if saved_config:
                    store.set_meta(
                        "model_test", dumps({"ok": False, "checked": time.time()})
                    )
                raise HTTPException(
                    502, "Model test failed: " + safe_error(exc, (cfg.llm.api_key,))
                ) from None
        usage = {}
        with store.connect() as db:
            row = db.execute(
                "SELECT input_tokens,output_tokens,duration FROM usage "
                "WHERE kind='diagnostic' AND job_id=? ORDER BY created DESC LIMIT 1",
                (diagnostic_id,),
            ).fetchone()
            if row:
                usage = {
                    "input_tokens": row[0],
                    "output_tokens": row[1],
                    "seconds": row[2],
                }
        if saved_config:
            store.set_meta(
                "model_test",
                dumps(
                    {
                        "ok": True,
                        "checked": time.time(),
                        "fingerprint": model_fingerprint(cfg),
                    }
                ),
            )
            monitor.reset_backoff()
        return {
            "ok": True,
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "base_url": cfg.llm.base_url,
            "saved_config": saved_config,
            "seconds": usage.get("seconds", time.monotonic() - started),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "message": "Conexión correcta: el modelo devolvió JSON válido. Esta prueba no mide la calidad de detección.",
        }

    @app.post("/api/scan")
    async def scan():
        if analyzer.lock.locked():
            raise HTTPException(409, "Analysis already running")
        result = await analyzer.cycle()
        if result.get("calls") and not result.get("errors"):
            monitor.reset_backoff()
        return result

    @app.get("/api/monitor")
    def monitor_state():
        return dict(monitor.state(), build=build)

    @app.post("/api/setup/complete")
    def finish_setup():
        if not setup_state(store)["model_tested"]:
            raise HTTPException(400, "Test the saved model configuration first")
        if not any(
            s["enabled"]
            and s["kind"] not in ("health", "metrics")
            and store.monitoring_active(s["machine_id"])
            for s in store.objects("source")
        ):
            raise HTTPException(400, "Enable at least one log source first")
        cfg = store.settings()
        cfg.enabled = True
        store.set_meta("settings", cfg.model_dump_json())
        store.set_meta("setup_completed", str(time.time()))
        monitor.reschedule()
        store.audit("setup_completed")
        return {"ok": True}

    @app.post("/api/jobs/{id}/retry")
    def retry_job(id: str):
        if analyzer.lock.locked():
            raise HTTPException(409, "Analysis already running")
        with store.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (id,)).fetchone()
            if not row or row["status"] != "failed":
                raise HTTPException(400, "Select a failed analysis")
            if not store.events(ids=json.loads(row["event_ids"])):
                raise HTTPException(409, "Original evidence has expired")
            db.execute(
                "UPDATE jobs SET status='retry',attempts=0,updated=? WHERE id=?",
                (time.time(), id),
            )
            db.execute(
                "UPDATE review_batches SET data=json_remove(data,'$.retry_at') WHERE job_id=?",
                (id,),
            )
        store.audit("retry_analysis", id)
        return {"ok": True}
