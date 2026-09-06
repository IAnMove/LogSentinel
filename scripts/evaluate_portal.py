"""Reproducible synthetic corpus check; --live measures the configured real model.
The small corpus is a regression aid, not a production detection benchmark.
"""

import argparse
import asyncio
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logsentinel.portal.store import Store, dumps
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.collect import normalize
from logsentinel.portal.analysis import Analyzer, compact


async def evaluate(args):
    corpus = json.loads(
        (
            Path(__file__).parent.parent / "tests/fixtures/evaluation/cases.json"
        ).read_text()
    )
    report = {
        "mode": "live" if args.live else "pipeline-only",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model": args.model if args.live else None,
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="sentinel-eval-") as directory:
        store = Store(directory)
        cfg = store.settings()
        cfg.llm.model = args.model
        cfg.llm.base_url = args.base_url
        cfg.llm.provider = args.provider
        cfg.remote_allowed = args.remote_allowed
        store.set_meta("settings", dumps(cfg.model_dump()))
        analyzer = Analyzer(store)
        for case in corpus:
            machine = store.put("machine", Machine(name=case["id"]).model_dump())
            source = Source(
                name="fixture", machine_id=machine, kind="push"
            ).model_dump()
            source["id"] = store.put("source", source)
            entries = [
                normalize(line, "synthetic", str(i))
                for i, line in enumerate(case["lines"])
            ]
            start = time.monotonic()
            store.ingest(source, entries)
            events = store.events(machine_id=machine)
            groups, selected, omitted = compact(events, cfg.input_budget)
            row = {
                "id": case["id"],
                "events": len(events),
                "groups": len(groups),
                "omitted": len(omitted),
                "logical_bytes": sum(len(line.encode()) for line in case["lines"]),
                "seconds": time.monotonic() - start,
            }
            if args.live:
                await analyzer.cycle()
                problems = [
                    p for p in store.rows("problems") if p["machine_id"] == machine
                ]
                refs = {
                    e["origin"]
                    for p in problems
                    for e in store.problem(p["id"])["evidence"]
                }
                row.update(
                    findings=len(problems),
                    expected_issue_lines=case["issue_lines"],
                    cited_issue_lines=[
                        i for i in case["issue_lines"] if str(i) in refs
                    ],
                    unexpected_finding_on_benign=not case["issue_lines"]
                    and bool(problems),
                    jobs=[
                        j["status"]
                        for j in store.rows("jobs")
                        if j["machine_id"] == machine
                    ],
                )
                row["measured"] = bool(row["jobs"]) and all(
                    status == "done" for status in row["jobs"]
                )
                if not row["measured"]:
                    row["cited_issue_lines"] = None
                    row["unexpected_finding_on_benign"] = None
            report["cases"].append(row)
        report["stats"] = store.stats()
        if args.live:
            report["note"] = (
                "Evidence overlap is not semantic correctness. Human review of each finding is required."
            )
        else:
            report["note"] = (
                "No model called. This run measures ingestion and compaction only; it cannot establish detection quality."
            )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n")
    else:
        print(rendered)
    return (
        1
        if args.live
        and any(
            any(s != "done" for s in c["jobs"]) or not c["jobs"]
            for c in report["cases"]
        )
        else 0
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--model", default="qwen2.5:7b")
    p.add_argument("--base-url", default="http://localhost:11434")
    p.add_argument("--provider", choices=["ollama", "openai"], default="ollama")
    p.add_argument("--remote-allowed", action="store_true")
    p.add_argument("--output")
    sys.exit(asyncio.run(evaluate(p.parse_args())))
