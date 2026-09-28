"""A model's cosmetic slips must not throw away a whole batch."""

import pytest
from pydantic import ValidationError

from logsentinel.portal.models import Verdict


def finding(**changes):
    base = dict(title="Disk write failed", summary="A write failed.", severity="HIGH",
                category="storage", evidence_ids=["g0"])
    base.update(changes)
    return base


def parse(*findings, **top):
    return Verdict.model_validate(dict(findings=list(findings), **top))


@pytest.mark.parametrize("severity", ["high", "High", " HIGH ", "hIgH"])
def test_severity_is_accepted_in_any_case(severity):
    assert parse(finding(severity=severity)).findings[0].severity == "HIGH"


def test_unknown_extra_keys_are_ignored_at_both_levels():
    verdict = parse(finding(confidence=0.9, tags=["x"]), notes="all good", model="m")
    assert verdict.findings[0].title == "Disk write failed"
    assert not hasattr(verdict, "notes")


def test_overlong_prose_is_clipped_and_a_missing_category_defaults():
    long_title = "T" * 500
    only = finding(title=long_title, summary="S" * 9000, reasoning="R" * 9000)
    del only["category"]
    result = parse(only).findings[0]
    assert len(result.title) == 200 and len(result.summary) == 4000 and len(result.reasoning) == 5000
    assert result.category == "other"


def test_a_list_of_next_steps_becomes_bulleted_text_within_the_bound():
    result = parse(finding(next_steps=["check df -h", "check dmesg"])).findings[0]
    assert result.next_steps == "- check df -h\n- check dmesg"
    assert len(parse(finding(next_steps=["x" * 9000])).findings[0].next_steps) == 4000


@pytest.mark.parametrize(
    "changes",
    [
        dict(severity="SEVERE"),
        dict(severity="INFO"),
        dict(severity=3),
        dict(evidence_ids=[]),
        dict(evidence_ids="g0"),
        dict(title=""),
        dict(title="   "),
        dict(summary=None),
    ],
)
def test_meaning_stays_strict(changes):
    with pytest.raises(ValidationError):
        parse(finding(**changes))


def test_findings_must_still_be_a_list_within_the_limit():
    with pytest.raises(ValidationError):
        Verdict.model_validate({"findings": "none"})
    with pytest.raises(ValidationError):
        parse(*[finding() for _ in range(31)])
