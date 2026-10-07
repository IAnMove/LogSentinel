"""The shape of a log line once the parts that change are masked out.

Two lines that differ only in an address, a number, a hex identifier or a
timestamp are the same template. Counting templates per source says how routine
a line is: the ten-thousandth "session opened for user root" is noise, the first
"Out of memory" is news. The masking is linear and bounded on text a stranger
wrote; it is not the grouping key problems are fingerprinted with, which must
stay stable across versions.
"""

from __future__ import annotations

import regex

MAX_TEXT = 4096
MAX_KEY = 512

_MASKS = (
    (regex.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (regex.compile(r"\b[A-Z][a-z]{2} {1,2}\d{1,2} \d{2}:\d{2}:\d{2}\b"), "<ts>"),
    (regex.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (regex.compile(r"\b(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{1,4}\b", regex.I), "<ip6>"),
    (regex.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", regex.I), "<uuid>"),
    (regex.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{6,}\b", regex.I), "<hex>"),
    (regex.compile(r"\b0x[0-9a-f]+\b", regex.I), "<hex>"),
    (regex.compile(r"\d+(?:\.\d+)?"), "#"),
)


def template(service, message):
    """A bounded key for the line's shape: the service and the masked message."""
    text = (message or "")[:MAX_TEXT]
    try:
        for pattern, mask in _MASKS:
            text = pattern.sub(mask, text, timeout=0.02)
    except TimeoutError:
        text = text[:64]
    text = " ".join(text.split())
    return ((service or "")[:64], text[:MAX_KEY])
