import pytest
from scripts.evaluate_review import cases, pipeline, pipeline_scores, score
from logsentinel.portal.analysis import ReviewClient
from logsentinel.portal.models import Settings


def test_detector_does_not_mask_missed_model_issue_or_inflate_duplicate_score():
    case = next(c for c in cases() if c["name"] == "disk_and_memory_same_service")
    disk = dict(evidence_ids=["g0"], severity="HIGH", category="storage")
    memory = dict(evidence_ids=["g1"], severity="HIGH", category="memory")
    detector = dict(evidence_ids=["g1"], severity="HIGH", category="resource", detector="oom")
    result = dict(findings=[disk, memory, detector], model_findings=[disk, memory], detector_findings=[detector])
    assert all(s["passed"] for s in pipeline_scores(case, result).values())
    result["model_findings"] = [disk]
    result["findings"] = [disk, detector]
    scores = pipeline_scores(case, result)
    assert scores["combined"]["passed"]
    assert not scores["model"]["passed"]
    assert not score(case, {"findings": [disk, memory, memory]}, combined=True)["passed"]


@pytest.mark.asyncio
async def test_pipeline_separates_model_detector_and_coverage(tmp_path, monkeypatch):
    case = next(c for c in cases() if c["name"] == "disk_and_memory_same_service")
    async def fake(self, payload, **kw):
        if "candidates" in payload:
            return {"assessments": [dict(candidate_id=c["candidate_id"], status="confirmed", evidence_ids=c["evidence_ids"], reason="Observed failure") for c in payload["candidates"]]}
        return {"findings": [dict(title=g["message"][:50], summary=g["message"], severity="HIGH", category="memory" if "Out of memory" in g["message"] else "storage", evidence_ids=[g["id"]]) for g in payload["groups"]]}
    monkeypatch.setattr(ReviewClient, "call", fake)
    store, result, info = await pipeline(case, Settings(), tmp_path)
    assert len(result["model_findings"]) == 2
    assert len(result["detector_findings"]) == 1
    assert info["coverage"] == dict(total=2, covered=2)
    assert all(s["passed"] for s in pipeline_scores(case, result).values())


def test_related_findings_preserve_independent_origin_and_decisions(tmp_path):
    from logsentinel.portal.analysis import Analyzer
    from logsentinel.portal.models import Machine
    from logsentinel.portal.store import Store
    from logsentinel.portal.signals import apply_signals
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="host").model_dump())
    store.ingest(dict(id="s", machine_id=machine), [dict(origin="oom", message="Out of memory")])
    analyzer = Analyzer(store)
    apply_signals(analyzer)
    detector_id = store.rows("problems")[0]["id"]
    model_id = analyzer.save_finding(machine, dict(title="Memory failure", summary="Out of memory", severity="HIGH", category="memory", evidence_ids=[]), [store.events()[0]["id"]])
    assert model_id != detector_id
    assert store.problem(model_id)["related"][0]["id"] == detector_id
    assert store.problem(detector_id)["related"][0]["id"] == model_id
    assert store.problem(model_id)["notification_decisions"][0]["reason"] == "no_destinations"
