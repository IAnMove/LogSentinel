"""Which findings are still news when the model or a detector reaches them late."""

import time
from datetime import datetime

from .store import dumps

LIVE_FLOOR_SECONDS = 300
# A backlog or a model outage delays review; a severe problem that happened
# within this window must still alert even though its batch is no longer live.
SEVERE_WINDOW_SECONDS = 6 * 3600
SEVERE = ("HIGH", "CRITICAL")


def live_cutoff(interval_seconds, now=None):
    """Events received after this instant are reviewed as they arrive."""
    return (time.time() if now is None else now) - max(
        LIVE_FLOOR_SECONDS, interval_seconds * 2
    )


def event_instant(event):
    try:
        value = datetime.fromisoformat(str(event.get("timestamp") or "").replace("Z", "+00:00"))
        if value.tzinfo is not None:
            return value.timestamp()
    except (ValueError, OverflowError):
        pass
    return event["received"]


def happened_recently(instant, now=None):
    return instant >= (time.time() if now is None else now) - SEVERE_WINDOW_SECONDS


def newest_instant(store, event_ids):
    """Newest event time among the originals, falling back to reception time."""
    if not event_ids:
        return 0.0
    with store.connect() as db:
        row = db.execute(
            "SELECT max(coalesce((julianday(event_time)-2440587.5)*86400,received)) "
            "FROM events WHERE id IN (SELECT value FROM json_each(?))",
            (dumps(list(event_ids)),),
        ).fetchone()
    return float(row[0] or 0.0)
