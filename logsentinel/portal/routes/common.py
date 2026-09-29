"""Pieces the route modules share."""

from __future__ import annotations

from ..models import Destination, Machine, Rule, Source

MODELS = {
    "machine": Machine,
    "source": Source,
    "destination": Destination,
    "rule": Rule,
}


def public(kind, obj):
    result = dict(obj)
    if kind == "destination":
        result["configured_fields"] = [
            k for k in ("url", "token", "secret", "headers") if result.get(k)
        ]
        for k in ("url", "token", "secret"):
            result[k] = ""
        result["headers"] = {}
    return result
