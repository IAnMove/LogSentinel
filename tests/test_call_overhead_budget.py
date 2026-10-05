"""The byte ceiling for a batch must leave room for everything the model call adds around it."""

import json

import pytest

from logsentinel.portal import analysis
from logsentinel.portal.analysis import TRIAGE_SYSTEM, call_overhead_bytes, UNTRUSTED_DATA_CONTRACT
from logsentinel.portal.batch_budget import input_ceiling
from logsentinel.portal.context_budget import input_bytes
from logsentinel.portal.models import Settings
from logsentinel.portal.store import Store, dumps


def test_the_overhead_is_exactly_what_the_call_adds_to_a_payload():
    payload = {"machine": {"name": "m"}, "sensitivity": "balanced", "groups": []}
    added = len(dumps(dict(payload, untrusted_data_contract=UNTRUSTED_DATA_CONTRACT)).encode()) - len(dumps(payload).encode())
    sentences = {len(f" Write findings in {name}.".encode()) for name in ("Spanish", "English")}
    assert call_overhead_bytes() == added + max(sentences)


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("context_tokens", [8192, 16384, 32768, 131072])
def test_a_batch_packed_to_the_ceiling_still_fits_once_the_call_has_added_its_text(tmp_path, language, context_tokens):
    store = Store(tmp_path)
    cfg = Settings(language=language, context_tokens=context_tokens, input_budget=500_000)
    machine = {"name": "Test host", "os": "", "timezone": "UTC", "notes": ""}
    ceiling = input_ceiling(cfg, machine, store)
    assert ceiling > 0
    envelope = dict(machine=machine, sensitivity=cfg.sensitivity, groups=[])
    # The largest groups the ceiling allows: pad one message until the payload hits it.
    room = ceiling
    groups = [dict(id="g0", message="")]
    while len(dumps(groups).encode()) + 2 < room:
        groups[0]["message"] += "x" * max(1, (room - len(dumps(groups).encode())) // 2)
    payload = dict(envelope, groups=groups)
    sentence = " Write findings in " + ("Spanish." if language == "es" else "English.")
    total = len((TRIAGE_SYSTEM + sentence + dumps(dict(payload, untrusted_data_contract=UNTRUSTED_DATA_CONTRACT))).encode())
    assert total <= input_bytes(store, cfg), (total, input_bytes(store, cfg))
