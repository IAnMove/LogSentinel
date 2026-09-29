"""The deterministic half of the evaluation corpus: what needs no model.

Each case may carry an "expect" object: the detector ids that must fire, which
lines must look like steering text, and strings that must never reach a model.
What the model itself finds is measured by scripts/evaluate_review.py.
"""

import json
from pathlib import Path

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.collect import normalize
from logsentinel.portal.compaction import compact
from logsentinel.portal.injection import looks_like_instruction
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.signal_scan import scan_originals
from logsentinel.portal.store import Store, dumps

CORPUS = json.loads((Path(__file__).parent / "fixtures/evaluation/cases.json").read_text())
CHECKED = [case for case in CORPUS if "expect" in case]


def test_the_corpus_covers_more_than_the_original_english_snippets():
    ids = {case["id"] for case in CORPUS}
    assert {"spanish-storage", "multiline-traceback", "secret-in-log", "openssh-98-burst"} <= ids
    assert all(set(case["issue_lines"]) <= set(range(len(case["lines"]))) for case in CORPUS)


@pytest.mark.parametrize("case", CHECKED, ids=[c["id"] for c in CHECKED])
def test_deterministic_expectations_hold(tmp_path, case):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name=case["id"]).model_dump())
    source = Source(name="fixture", machine_id=machine, kind="push").model_dump()
    source["id"] = store.put("source", source)
    store.ingest(source, [normalize(line, "synthetic", str(i)) for i, line in enumerate(case["lines"])])
    events = store.events(machine_id=machine)
    expect = case["expect"]

    scan_originals(Analyzer(store), machine, events)
    fired = {json.loads(p["data"]).get("detector") for p in store.rows("problems")} - {None, "prompt-injection"}
    assert fired == set(expect["signals"]), (fired, case["lines"])

    if "instruction_like" in expect:
        flagged = [i for i, line in enumerate(case["lines"]) if looks_like_instruction(line)]
        assert flagged == expect["instruction_like"]

    groups = compact(events, store.settings().input_budget)[0]
    shown = dumps(groups)
    for secret in expect.get("hidden", []):
        assert secret not in shown, secret
    if expect.get("hidden"):
        assert "[REDACTED" in shown  # hidden by redaction, not by dropping the line
