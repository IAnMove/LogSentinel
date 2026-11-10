"""Server-side logging: redacted, with tracebacks, and quiet about repeats.

Workers used to keep only a short message in the database when something
failed. That is right for the interface but leaves nothing to debug with. The
logger writes the traceback to stderr (the journal, under systemd) with the
same redaction the rest of the portal applies, and repeats of one failure are
suppressed for a while: a loop that fails every second must not fill the disk,
or feed the journal the portal itself may be reading.
"""

from __future__ import annotations

import logging
import sys
import time

from logsentinel.redact import redact

LOG = logging.getLogger("logsentinel.portal")
REPEAT_SECONDS = 300
_last: dict = {}


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def configure(level=logging.INFO, stream=None):
    """Attach one redacting handler to the portal's loggers; safe to call twice."""
    root = logging.getLogger("logsentinel")
    if not any(getattr(h, "_logsentinel", False) for h in root.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler._logsentinel = True
        handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)
    return root


class FailedRequestsOnly(logging.Filter):
    """Keep uvicorn's access lines for refused or failed requests only.

    Every sender request used to leave a "200 OK" line on stdout. Under systemd
    that is the journal the portal itself reads, so each delivery produced new
    log lines to store, review and pay the model for: on one deployment three
    fifths of the local journal was the portal describing its own traffic. A
    401 on reception or a 5xx is still evidence and still written."""

    def filter(self, record):
        args = record.args
        try:
            return int(args[4]) >= 400  # type: ignore[index]
        except (TypeError, ValueError, IndexError, KeyError):
            return True


def uvicorn_log_config():
    """uvicorn's default logging with successful access lines left out."""
    import copy
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["failed_requests_only"] = {
        "()": "logsentinel.portal.logs.FailedRequestsOnly"
    }
    config["handlers"]["access"]["filters"] = ["failed_requests_only"]
    return config


def once_per(key, seconds=REPEAT_SECONDS):
    """True the first time a condition is seen and then once per interval."""
    now = time.monotonic()
    if now - _last.get(key, float("-inf")) < seconds:
        return False
    _last[key] = now
    if len(_last) > 500:  # conditions are few; a runaway set of keys must not grow
        _last.clear()
        _last[key] = now
    return True


def report(area, exc, logger=LOG, trace=True):
    """Log a failure with its traceback, once per kind of failure per interval.

    trace=False records only the exception type, for errors whose text can carry
    a destination's URL and so a credential the redaction has no way to know."""
    if once_per((area, type(exc).__name__, str(exc)[:80])):
        logger.error(
            "%s failed: %s", area, type(exc).__name__, exc_info=exc if trace else None
        )
