"""Reproducible synthetic history demo. No real logs or notifications.

Default: print computed evidence, no LLM/network.
--llm: additionally send only this synthetic incident to local Ollama.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

# Allow execution from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logsentinel.config import Config
from logsentinel.core.engine import SentinelEngine
from logsentinel.core.models import LogEntry


def entry(at):
    message = 'Accepted publickey for demo-user from 192.0.2.10 port 50000 ssh2'
    return LogEntry(timestamp=at, service='sshd', hostname='synthetic-server', message=message, raw=message, priority=6)


async def demo(use_llm):
    with tempfile.TemporaryDirectory(prefix='logsentinel-demo-') as data_dir:
        cfg = Config(behavior={'enabled': True}, app={'data_dir': data_dir}, llm={'max_tokens': 4096}, notifiers={'desktop': {'enabled': False}, 'file': {'enabled': False}})
        engine = SentinelEngine(cfg)
        captured = []
        async def capture(incident):
            captured.append(incident)
        engine.aggregator.on_incident_ready = capture
        start = datetime(2025, 1, 6, 9, tzinfo=timezone.utc)
        for i in range(26):
            at = start + timedelta(days=i)
            if at.weekday() < 5:
                await engine.ingest_log(entry(at))
        # Restart proves history survives object lifetimes.
        engine = SentinelEngine(cfg)
        engine.aggregator.on_incident_ready = capture
        await engine.ingest_log(entry(datetime(2025, 2, 1, 3, tzinfo=timezone.utc)))
        await engine.aggregator.flush_all()
        assert len(captured) == 1
        incident = captured[0]
        evidence = incident.entries[0].metadata['behavior']
        assert evidence['prior_events'] == 20
        assert set(evidence['anomalies']) == {'unseen_day_type', 'unusual_hour'}
        result = {'synthetic': True, 'evidence': evidence}
        if use_llm:
            verdict = await engine.llm_client.analyze(incident)
            result['llm_verdict'] = verdict.model_dump(mode='json')
            result['llm_fallback'] = bool(verdict.reasoning and ('Fallback' in verdict.reasoning or 'LLM call exception' in verdict.reasoning))
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llm', action='store_true', help='Use local Ollama with synthetic data only')
    args = parser.parse_args()
    asyncio.run(demo(args.llm))
