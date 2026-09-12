"""Synthetic sustained-load benchmark; never transmits retained production logs.

Examples:
  python scripts/benchmark_review.py --settings-db PATH --output results.json
  python scripts/benchmark_review.py --settings-db PATH --output simulation.json --synthetic-model-delay 2

Uses separate temporary stores for each interval, leaves saved settings unchanged,
and creates no notification destinations. Real runs share the configured model
server with its other clients; reserve that server before comparing throughput.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.build_info import running_build
from logsentinel.portal.models import Machine, Settings, Source
from logsentinel.portal.monitor import Monitor
from logsentinel.portal.store import Store


def entries(wave, count):
    timestamp = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        # Four fifths repeat proven routine templates; preserve unique resources
        # in the remaining fifth so the test cannot assume infinite compaction.
        resource = f"item/{wave}-{i}" if i % 5 == 0 else f"health/{i % 4}"
        yield dict(
            origin=f"{wave}-{i}", timestamp=timestamp, service="python", priority=6,
            source_type="JOURNALD", metadata=dict(systemd_unit="synthetic-worker.service"),
            message=f'{timestamp} INFO httpx: HTTP Request: GET https://example.invalid/{resource} "HTTP/1.1 200 OK"',
        )


async def scenario(args, cfg, interval, directory):
    store = Store(directory)
    config = cfg.model_copy(deep=True)
    config.interval_seconds = interval
    config.enabled = True
    if args.model:
        config.llm.model = args.model
    if args.input_bytes:
        config.input_budget = args.input_bytes
    store.set_meta("settings", config.model_dump_json())
    machine = store.put("machine", Machine(name="Synthetic benchmark host").model_dump())
    sid = store.put("source", Source(name="Synthetic logs", machine_id=machine, kind="push", enabled=True).model_dump())
    analyzer = Analyzer(store)
    if args.synthetic_model_delay is not None:
        async def synthetic(payload, **kwargs):
            from logsentinel.portal.batch_budget import profile_key
            started_call = time.monotonic()
            await asyncio.sleep(args.synthetic_model_delay)
            store.record_usage(kwargs.get("job", ""), kwargs.get("machine", ""), kwargs.get("sources", []), kwargs.get("kind", "analysis"), started_call, None, None, "ok", dict(synthetic=True, review_profile=profile_key(config), represented_events=sum(g.get("count", 1) for g in payload.get("groups", []))))
            return {"findings": []}
        analyzer.client.call = synthetic
    monitor = Monitor(store, analyzer, True)
    started = time.monotonic()
    snapshots, waves = [], 0
    stop = asyncio.Event()

    async def produce():
        nonlocal waves
        for wave in range(args.waves):
            wait = started + wave * interval - time.monotonic()
            if wait > 0:
                try:
                    await asyncio.wait_for(stop.wait(), wait)
                    return
                except TimeoutError:
                    pass
            if stop.is_set():
                return
            await asyncio.to_thread(store.ingest, store.get("source", sid), list(entries(wave, args.events)))
            waves += 1
            print(f"INGEST interval={interval} wave={waves} events={args.events}", flush=True)

    producer = asyncio.create_task(produce())
    try:
        while time.monotonic() - started < args.max_runtime:
            before = analyzer.finished
            remaining = args.max_runtime - (time.monotonic() - started)
            try:
                await asyncio.wait_for(monitor.tick(), max(.01, remaining))
            except TimeoutError:
                break
            if before != analyzer.finished:
                state = monitor.state()
                with store.connect() as db:
                    call_count = db.execute("SELECT count(*) FROM usage WHERE kind IN ('analysis','investigation')").fetchone()[0]
                snapshots.append(dict(
                    seconds=round(time.monotonic() - started, 3), waves=waves,
                    coverage=state["coverage"], waiting_jobs=state["waiting_jobs"],
                    next_analysis=state["next_analysis"], calls=call_count,
                    tuning=state["batch_tuning"], outcome=analyzer.outcome,
                ))
                print("CYCLE", interval, json.dumps(snapshots[-1]), flush=True)
                if producer.done() and state["coverage"]["unreviewed"] == 0 and state["waiting_jobs"] == 0:
                    break
            await asyncio.sleep(.1)
    finally:
        stop.set()
        await producer
    state = monitor.state()
    elapsed = time.monotonic() - started
    with store.connect() as db:
        usages = [dict(r) for r in db.execute("SELECT created,duration,status,input_tokens,output_tokens,detail FROM usage ORDER BY created")]
        findings = db.execute("SELECT count(*) FROM problems WHERE status='open'").fetchone()[0]
    durations = sorted(u["duration"] for u in usages)
    for usage in usages:
        usage["detail"] = json.loads(usage["detail"])
    return dict(
        interval_seconds=interval, mode="simulated" if args.synthetic_model_delay is not None else "real_model",
        model=config.llm.model, context_tokens=config.context_tokens, input_limit_bytes=config.input_budget,
        seconds=elapsed, waves=waves, originals=waves * args.events,
        coverage=state["coverage"], waiting_jobs=state["waiting_jobs"],
        covered_originals_per_second=state["coverage"]["covered"] / max(elapsed, .001),
        unexpected_open_findings=findings,
        median_call_seconds=statistics.median(durations) if durations else None,
        p95_call_seconds=durations[max(0, int(len(durations) * .95 + .999) - 1)] if durations else None,
        calls=usages, snapshots=snapshots,
    )


async def run(args):
    with sqlite3.connect(Path(args.settings_db).resolve().as_uri() + "?mode=ro", uri=True) as db:
        cfg = Settings.model_validate_json(db.execute("SELECT value FROM meta WHERE key='settings'").fetchone()[0])
    result = dict(build=running_build(), synthetic_only=True, hardware_verified=False, results=[])
    with tempfile.TemporaryDirectory(prefix="sentinel-load-benchmark-") as directory:
        for interval in [int(i) for i in args.intervals.split(",")]:
            if not 5 <= interval <= 86400:
                raise ValueError("Intervals must be between 5 and 86400 seconds")
            result["results"].append(await scenario(args, cfg, interval, Path(directory) / str(interval)))
            Path(args.output).write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings-db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model")
    parser.add_argument("--intervals", default="30,60")
    parser.add_argument("--waves", type=int, default=3)
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--input-bytes", type=int)
    parser.add_argument("--max-runtime", type=float, default=360)
    parser.add_argument("--synthetic-model-delay", type=float)
    args = parser.parse_args()
    if not 1 <= args.waves <= 100 or not 1 <= args.events <= 5000 or args.max_runtime <= 0 or (args.synthetic_model_delay is not None and args.synthetic_model_delay < 0):
        parser.error("Use 1–100 waves, 1–5000 events, and positive runtime/nonnegative delay")
    asyncio.run(run(args))
