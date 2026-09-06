"""Strict validation of complete LLM verdicts; invalid output never suppresses."""

from __future__ import annotations

import json
import math
import re
from typing import Optional

from logsentinel.core.models import Category, Incident, LLMVerdict, Severity


class ResponseParser:
    """Accept complete JSON documents, not repaired or regex-recovered fields."""

    REQUIRED_FIELDS = frozenset({
        "alert_needed", "severity", "category", "title", "summary",
        "recommended_action", "confidence", "suggested_ignore_pattern",
        "matched_memory_rule", "reasoning",
    })

    @staticmethod
    def strip_thinking_tokens(text: str) -> str:
        """Allow one complete leading reasoning block, never rewrite JSON strings."""
        cleaned = text.strip()
        if cleaned.startswith("<think>"):
            end = cleaned.find("</think>")
            if end != -1:
                return cleaned[end + len("</think>"):].strip()
        return cleaned

    @staticmethod
    def extract_json_str(text: str) -> Optional[str]:
        """Unwrap only a complete fence enclosing the entire document."""
        candidate = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL)
        if fenced:
            candidate = fenced.group(1).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
        return None

    @staticmethod
    def _unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"Non-JSON constant: {value}")

    @classmethod
    def parse(cls, raw_text: str, incident: Incident) -> LLMVerdict:
        """Reject missing fields, coercions, invalid enums, NaN and truncation."""
        try:
            if not isinstance(raw_text, str):
                raise ValueError("Response is not text")
            candidate = cls.extract_json_str(cls.strip_thinking_tokens(raw_text))
            if candidate is None:
                raise ValueError("No complete JSON object")
            data = json.loads(candidate, object_pairs_hook=cls._unique_object, parse_constant=cls._reject_constant)
            if not isinstance(data, dict) or set(data) != cls.REQUIRED_FIELDS:
                raise ValueError("Incomplete or unexpected verdict fields")
            if type(data["alert_needed"]) is not bool:
                raise ValueError("alert_needed must be a JSON boolean")
            confidence = data["confidence"]
            if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("confidence must be a finite number in [0, 1]")
            for field in ("title", "summary"):
                if not isinstance(data[field], str) or not data[field].strip():
                    raise ValueError(f"{field} must be nonempty text")
            for field in ("recommended_action", "suggested_ignore_pattern", "matched_memory_rule", "reasoning"):
                if data[field] is not None and not isinstance(data[field], str):
                    raise ValueError(f"{field} must be text or null")
            data["severity"] = Severity(data["severity"])
            data["category"] = Category(data["category"])
            return LLMVerdict(**data)
        except (ValueError, TypeError, OverflowError, RecursionError):
            pass

        urgent = incident.category_hint in (Category.SECURITY, Category.SYSTEM_ERROR)
        return LLMVerdict(
            alert_needed=True,
            severity=Severity.HIGH if urgent else Severity.MEDIUM,
            category=incident.category_hint,
            title=f"Incident in {incident.service}",
            summary=f"Detected {incident.count} events for {incident.service}; model verdict could not be validated.",
            recommended_action="Review the original service logs and corroborate the incident manually.",
            confidence=0.0,
            reasoning="Fallback parser activated: invalid or incomplete model verdict; no suppression authorized.",
        )
