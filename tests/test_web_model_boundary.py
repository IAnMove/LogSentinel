"""Visitors' addresses, paths and agents stay out of the model's input unless a person asks about a web problem."""

import json
import time

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.collect import normalize
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.problem_context import chat_system, context_for
from logsentinel.portal.research import SearchPlan, related_events
from logsentinel.portal.store import Store
from tests.test_web_access_policy import web_line
from tests.test_web_signals import line

MARKERS = ("192.0.2.", "curl/8.0", "/.env")


@pytest.fixture
def site(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Web host").model_dump())
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="push", enabled=True).model_dump())
    return store, machine, store.get("source", sid)


def ingest_around_an_error(store, source):
    lines = [web_line(n) for n in range(4)] + ["disk write failed on block 7"] + [web_line(n) for n in range(4, 8)]
    store.ingest(source, [normalize(text, "remote", f"o{i}") for i, text in enumerate(lines)])


def leaks(text):
    return [m for m in MARKERS if m in text]


@pytest.mark.asyncio
async def test_the_verifier_is_not_shown_requests_that_sit_beside_an_error(site):
    store, machine, source = site
    ingest_around_an_error(store, source)
    sent = []

    async def model(payload, **kwargs):
        sent.append(json.dumps(payload))
        if "groups" in payload:
            return {"findings": [dict(title="Write failed", summary="A write failed.", severity="HIGH", category="storage", evidence_ids=[g["id"] for g in payload["groups"]])]}
        return {"assessments": [dict(candidate_id=c["candidate_id"], status="confirmed", severity="HIGH", reason="ok", evidence_ids=c["evidence_ids"]) for c in payload["candidates"]]}

    analyzer = Analyzer(store)
    analyzer.client.call = model
    await analyzer.cycle()
    assert len(sent) == 2, "the triage and the verification must both have run"
    assert not [leak for text in sent for leak in leaks(text)]


def test_the_assistant_sample_for_a_machine_leaves_requests_out(site):
    store, machine, source = site
    ingest_around_an_error(store, source)
    payload, report = context_for(store, machine, "", "What is happening?", chat_system("en"))
    assert [e["message"] for e in payload["events"]] == ["disk write failed on block 7"]
    assert not leaks(json.dumps(payload))


def test_the_investigation_search_does_not_widen_into_requests(site):
    store, machine, source = site
    now = time.time()
    # Requests written in the same minute as the error, mentioning the search terms.
    store.ingest(source, [normalize(line(target="/.env", when=now - 10 + n), "remote", f"w{n}") for n in range(6)])
    store.ingest(source, [dict(origin="err", message="disk write failed on block 7", service="kernel")])
    finding = dict(title="Write failed", summary="s", severity="HIGH", category="storage",
                   evidence_ids=[e["id"] for e in store.events(limit=100) if "disk" in e["message"]])
    pid = Analyzer(store).save_finding(machine, finding, finding["evidence_ids"])
    related, _ = related_events(store, store.problem(pid), SearchPlan(terms=["env", "curl", "write"]), 5)
    assert not [e for e in related if e["service"] == "web-access"]


def test_a_person_asking_about_a_web_problem_still_gets_its_own_requests(site):
    store, machine, source = site
    store.ingest(source, [normalize(web_line(n), "remote", f"w{n}") for n in range(12)])
    ids = [e["id"] for e in store.events(limit=100)]
    finding = dict(title="Probing", summary="s", severity="LOW", category="security", evidence_ids=ids)
    pid = Analyzer(store).save_finding(machine, finding, ids)
    payload, _ = context_for(store, machine, source["id"], "What was requested?", chat_system("en"), store.problem(pid))
    assert payload["events"], "explaining a web problem needs the requests behind it"
