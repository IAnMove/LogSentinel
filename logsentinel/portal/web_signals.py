"""Deterministic findings about web traffic, answered without the model.

A spec has the shape of the ones in signals.py, with a `match` function over the
parsed request instead of a pattern over the text, and a `digest` that sums up
the requests behind a finding. Everything a finding prints about a request was
chosen by the visitor, so it is bounded and limited to printable ASCII first.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import unquote

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


@lru_cache(maxsize=4096)
def decoded(text):
    """What a server makes of a path or query: URL-decoded twice, slashes and case folded.

    Twice because double encoding is the usual way past a filter. Matching runs on
    this, never on the raw text, so %2e%65nv and .ENV are the same request.
    """
    for _ in range(2):
        text = unquote(text)
    return text.replace("\\", "/").lower()


# Files that must never be served: secrets, repositories, keys, dumps and backups.
SECRET_PATH = re.compile(
    r"(?:^|/)\.env(?:\.[a-z0-9_-]{1,32})?$"
    r"|/\.(?:git|svn|hg|aws|ssh|docker)(?:/|$)"
    r"|(?:^|/)\.(?:htpasswd|git-credentials|npmrc|netrc|pgpass)$"
    r"|(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)$"
    r"|(?:^|/)(?:wp-config|config|configuration|settings|database|secrets|credentials)\.[a-z0-9]{2,5}\.(?:bak|old|orig|save|swp|txt)$"
    r"|\.(?:sql|sqlite3?|db|bak|old|orig|swp)(?:\.(?:gz|zip|tar|7z|bz2|xz))?$"
    r"|(?:^|/)(?:backup|dump|db|database|site|www|web)\.(?:zip|tar|tgz|tar\.gz|7z|rar)$",
    re.ASCII,
)
# Panels and exploit endpoints that are only ever asked for by someone looking
# for them. WordPress login paths are left out: on a WordPress site they are
# ordinary traffic, and the login detector watches them.
SCANNER_PATH = re.compile(
    r"/(?:phpmyadmin|pma|adminer(?:\.php)?|phpinfo\.php|server-status|server-info|boaform|hnap1"
    r"|jmx-console|_ignition|telescope)(?:/|$)"
    r"|/actuator(?:/|$)|/vendor/phpunit/|/cgi-bin/|/manager/html|/solr/admin|/eval-stdin\.php",
    re.ASCII,
)


def path_text(event):
    return decoded(path_of(request(event).get("target", "")))


def sensitive_probe(event):
    path = path_text(event)
    return bool(SECRET_PATH.search(path) or SCANNER_PATH.search(path))


def secret_served(event):
    seen = request(event)
    return (
        seen.get("method") == "GET"
        and seen.get("status") in (200, 206)
        and bool(SECRET_PATH.search(path_text(event)))
    )


LOGIN_PATH = re.compile(
    r"(?:^|/)(?:wp-login\.php|xmlrpc\.php|login|signin|sign-in|log-in|user/login|users/sign_in"
    r"|accounts?/login|admin/login|administrator/index\.php|api/(?:v\d+/)?login)(?:/|$)",
    re.ASCII,
)


def login_attempt(event):
    return request(event).get("method") == "POST" and bool(LOGIN_PATH.search(path_text(event)))


def one_client_sends(minimum):
    """A window qualifies only when a single client alone made at least `minimum` of its requests.

    The same total spread over many visitors is a busy site, not an attack.
    """

    def confirm(hits):
        return Counter(request(e).get("ip") for e in hits).most_common(1)[0][1] >= minimum

    return confirm


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
    {
        "id": "web_login_attempts",
        "min": 20,
        "window_seconds": 300,
        "severity": "HIGH",
        "category": "authentication",
        "service": is_web,
        "match": login_attempt,
        "confirm": one_client_sends(15),
        "digest": web_digest,
        "title": ("Intentos repetidos de inicio de sesión web", "Repeated web login attempts"),
        "summary": (
            "Un mismo cliente envió muchas peticiones POST a páginas de inicio de sesión en cinco minutos. "
            "Puede ser fuerza bruta o relleno de credenciales; no prueba que ningún intento haya acertado.",
            "One client sent many POST requests to login pages within five minutes. "
            "It may be brute force or credential stuffing; it does not show that any attempt succeeded.",
        ),
    },
    {
        "id": "web_sensitive_probes",
        "min": 10,
        "window_seconds": 600,
        "severity": "LOW",
        "category": "security",
        "service": is_web,
        "match": sensitive_probe,
        "digest": web_digest,
        "title": ("Sondeo de rutas sensibles", "Probing for sensitive paths"),
        "summary": (
            "Varias peticiones buscan archivos de configuración, repositorios, copias de seguridad o paneles "
            "de administración. Es ruido habitual en internet, pero muestra qué se está buscando.",
            "Several requests look for configuration files, repositories, backups or admin panels. "
            "It is routine background noise on the internet, but it shows what is being looked for.",
        ),
    },
    {
        "id": "web_secret_served",
        "min": 1,
        # A day: one rolling problem per source instead of one per request.
        "window_seconds": 86400,
        "severity": "MEDIUM",
        "category": "security",
        "service": is_web,
        "match": secret_served,
        "digest": web_digest,
        "title": ("Ruta sensible servida por el servidor web", "Sensitive path served by the web server"),
        "summary": (
            "Una petición a un archivo que no debería publicarse (configuración, repositorio, copia de seguridad "
            "o claves) recibió una respuesta correcta. Puede ser el archivo real o una página genérica que el "
            "servidor devuelve para cualquier ruta: comprueba el contenido.",
            "A request for a file that should never be public (configuration, repository, backup or keys) was "
            "answered successfully. It may be the real file or a catch-all page the server returns for any path: "
            "check the content.",
        ),
    },
)
