"""Read-only throughput diagnostics using retained events, without an LLM call."""

import time


def capacity_report(store, machine_id=""):
    now = time.time()
    where = "received>=? AND status!='measured'"
    args = [now - 3600]
    if machine_id:
        where += " AND machine_id=?"
        args.append(machine_id)
    with store.connect() as db:
        totals = dict(
            db.execute(
                "SELECT count(*) events,min(received) oldest,sum(status='capacity') capacity,sum(status IN ('compact','reviewed')) reviewed,sum(status='sampled') policy FROM events WHERE "
                + where,
                args,
            ).fetchone()
        )
        services = [
            dict(r)
            for r in db.execute(
                "SELECT machine_id,source_id,service,count(*) events,sum(status='capacity') capacity,sum(status IN ('compact','reviewed')) reviewed,sum(status='sampled') policy FROM events WHERE "
                + where
                + " GROUP BY machine_id,source_id,service ORDER BY events DESC LIMIT 20",
                args,
            )
        ]
        usage_where = "created>=? AND kind='analysis'"
        if machine_id:
            usage_where += " AND machine_id=?"
        usage = dict(
            db.execute(
                "SELECT count(*) calls,avg(duration) average_seconds,sum(status='error') errors FROM usage WHERE "
                + usage_where,
                args,
            ).fetchone()
        )
    seconds = min(3600, max(60, now - (totals.pop("oldest") or now)))
    totals = {key: value or 0 for key, value in totals.items()}
    return dict(
        generated=now,
        window_seconds=seconds,
        **totals,
        incoming_per_minute=totals["events"] * 60 / seconds,
        covered_per_minute=totals["reviewed"] * 60 / seconds,
        services=services,
        analysis=usage,
    )
