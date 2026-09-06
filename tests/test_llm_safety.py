"""Offline fail-safe response contract: malformed responses never suppress."""

import json
import math

import pytest

from logsentinel.core.models import Category, Incident
from logsentinel.llm.parser import ResponseParser


VALID = {
    "alert_needed": False,
    "severity": "LOW",
    "category": "ANOMALY",
    "title": "Synthetic routine event",
    "summary": "Evidence supports expected maintenance.",
    "recommended_action": "Check the maintenance schedule.",
    "confidence": 0.8,
    "suggested_ignore_pattern": None,
    "matched_memory_rule": None,
    "reasoning": "Routine maintenance is plausible; verify the schedule.",
}


def sample(category=Category.ANOMALY):
    return Incident(service="synthetic", signature="synthetic", category_hint=category)


def assert_safe(raw, category=Category.ANOMALY):
    verdict = ResponseParser.parse(raw, sample(category))
    assert verdict.alert_needed is True
    assert math.isfinite(verdict.confidence) and 0 <= verdict.confidence <= 1
    assert verdict.matched_memory_rule is None
    assert verdict.suggested_ignore_pattern is None
    assert "Fallback" in verdict.reasoning


@pytest.mark.parametrize("field,value", [
    ("alert_needed", "false"), ("alert_needed", 0), ("alert_needed", None),
    ("confidence", "0.8"), ("confidence", True), ("confidence", -0.1),
    ("confidence", 1.1), ("confidence", float("nan")), ("confidence", float("inf")),
    ("severity", "bogus"), ("category", "bogus"), ("title", []), ("summary", ""),
    ("recommended_action", []), ("matched_memory_rule", 123),
])
def test_invalid_field_invalidates_entire_verdict(field, value):
    assert_safe(json.dumps({**VALID, field: value}))


@pytest.mark.parametrize("missing", list(VALID))
def test_every_schema_field_is_required(missing):
    assert_safe(json.dumps({key: value for key, value in VALID.items() if key != missing}))


@pytest.mark.parametrize("raw", [
    '{"alert_needed":false', '{"alert_needed":false,}',
    json.dumps(VALID)[:-1], json.dumps(VALID) + ' trailing prose',
    '[' + json.dumps(VALID) + ']', '{"nested":' + json.dumps(VALID),
    json.dumps(VALID) + json.dumps(VALID),
    json.dumps(VALID)[:-1] + ',"alert_needed":false}',
    'explanation ' + json.dumps(VALID), '', 'not JSON',
])
def test_malformed_or_ambiguous_document_never_suppresses(raw):
    assert_safe(raw)


@pytest.mark.parametrize("category", list(Category))
def test_fallback_never_suppresses_any_category(category):
    assert_safe("unparseable", category)


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "<think>brief thought</think>\n{}"])
def test_complete_valid_document_can_suppress(wrapper):
    verdict = ResponseParser.parse(wrapper.format(json.dumps(VALID)), sample())
    assert verdict.alert_needed is False
    assert verdict.category == Category.ANOMALY
    assert verdict.confidence == 0.8


def test_every_truncated_prefix_of_valid_suppression_is_safe():
    raw = json.dumps(VALID)
    for end in range(len(raw)):
        assert_safe(raw[:end])


@pytest.mark.parametrize("raw", [None, [], {}, 1, '<think>unfinished ' + json.dumps(VALID), '```json\n' + json.dumps(VALID)])
def test_nontext_or_incomplete_wrapper_is_safe(raw):
    assert_safe(raw)


@pytest.mark.parametrize("confidence", [0, 1, 0.5])
def test_valid_confidence_boundaries(confidence):
    verdict = ResponseParser.parse(json.dumps({**VALID, "confidence": confidence}), sample())
    assert verdict.alert_needed is False
    assert verdict.confidence == confidence


def test_reasoning_markup_inside_json_string_is_preserved_as_data():
    summary = 'Literal <think>untrusted</think> and braces { } with "quotes"'
    verdict = ResponseParser.parse(json.dumps({**VALID, "summary": summary}), sample())
    assert verdict.summary == summary
