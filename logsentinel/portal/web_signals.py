"""Deterministic findings about web traffic, answered without the model.

A spec has the shape of the ones in signals.py, with a `match` function over the
parsed request instead of a pattern over the text, and a `digest` that sums up
the requests behind a finding. Everything a finding prints about a request was
chosen by the visitor, so it is bounded and limited to printable ASCII first.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .freshness import event_instant
from .web_access import WEB_SERVICE

TOP = 5


def is_web(service):
    return service == WEB_SERVICE


def request(event):
    return (event.get("metadata") or {}).get("web") or {}


def path_of(target):
    """The path alone: a query string is where tokens and addresses end up."""
    return str(target).split("?", 1)[0].split("#", 1)[0]


def shown(text, limit=64):
    """Visitor-chosen text made safe to print: bounded, printable ASCII only."""
    text = str(text)
    return "".join(c if "!" <= c <= "~" else "?" for c in text[:limit]) + ("..." if len(text) > limit else "")


def ranked(counter, spanish):
    top = counter.most_common(TOP)
    text = ", ".join(f"{shown(key)} ({count})" for key, count in top)
    rest = len(counter) - len(top)
    return text + (f" +{rest} " + ("más" if spanish else "more") if rest > 0 else "")


def stamp(instant):
    return datetime.fromtimestamp(instant, timezone.utc).strftime("%Y-%m-%d %H:%M")


def web_digest(hits, spanish):
    """What the requests behind a finding were, without opening each original."""
    seen = [request(e) for e in hits]
    clients = Counter(r.get("ip", "?") for r in seen)
    paths = Counter(path_of(r.get("target", "")) for r in seen)
    statuses = Counter(str(r.get("status", "?")) for r in seen)
    moments = [event_instant(e) for e in hits]
    span = f"{stamp(min(moments))} - {stamp(max(moments))} UTC"
    if spanish:
        return (
            f"{len(seen)} peticiones de {len(clients)} clientes entre {span}. "
            f"Códigos: {ranked(statuses, True)}. Rutas: {ranked(paths, True)}. "
            f"Clientes: {ranked(clients, True)}."
        )
    return (
        f"{len(seen)} requests from {len(clients)} clients between {span}. "
        f"Status codes: {ranked(statuses, False)}. Paths: {ranked(paths, False)}. "
        f"Clients: {ranked(clients, False)}."
    )


def server_error(event):
    return 500 <= request(event).get("status", 0) <= 599


WEB_SIGNALS = (
    {
        "id": "web_server_errors",
        "min": 10,
        "window_seconds": 300,
        "severity": "HIGH",
        "category": "reliability",
        "service": is_web,
        "match": server_error,
        "digest": web_digest,
        "title": ("Ráfaga de errores del servidor web", "Burst of web server errors"),
        "summary": (
            "El servidor web respondió con errores 5xx de forma repetida en cinco minutos. "
            "Puede ser un fallo de la aplicación o un ataque que lo provoca.",
            "The web server repeatedly answered with 5xx errors within five minutes. "
            "It may be an application failure or an attack that causes one.",
        ),
    },
)
