"""Every event gets a rank when it arrives: severity first, then how rarely its shape is seen."""

from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import TEMPLATES_PER_SOURCE, Store


def fixture(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump()))
    return store, source


def ranks(store):
    with store.connect() as db:
        return dict(db.execute("SELECT origin, rank FROM events").fetchall())


def test_the_first_sighting_ranks_highest_and_repeats_fall_to_zero(tmp_path):
    store, source = fixture(tmp_path)
    store.ingest(source, [dict(origin=f"r{n}", message=f"Started Session {n} of user ina.", service="systemd") for n in range(200)])
    r = ranks(store)
    assert r["r0"] == 4 and r["r1"] == 3 and r["r3"] == 2 and r["r10"] == 1 and r["r150"] == 0
    store.ingest(source, [dict(origin="new", message="disk write failed on block 7", service="app")])
    assert ranks(store)["new"] == 4


def test_severity_outranks_rarity(tmp_path):
    store, source = fixture(tmp_path)
    store.ingest(source, [dict(origin=f"r{n}", message="Out of memory: Killed process 1 (java)", service="kernel", priority=2) for n in range(200)])
    store.ingest(source, [dict(origin="rare", message="never seen this shape before", service="app")])
    r = ranks(store)
    assert r["r199"] == 10 > r["rare"] == 4, "a routine critical line still beats a rare informational one"
    assert r["r0"] == 14


def test_templates_are_counted_per_source(tmp_path):
    store, a = fixture(tmp_path)
    b = store.get("source", store.put("source", Source(name="other", machine_id=a["machine_id"], kind="push", enabled=True).model_dump()))
    store.ingest(a, [dict(origin=f"a{n}", message="routine thing", service="app") for n in range(50)])
    store.ingest(b, [dict(origin="b0", message="routine thing", service="app")])
    assert ranks(store)["b0"] == 4


def test_the_template_table_is_capped_per_source(tmp_path):
    store, source = fixture(tmp_path)
    store.ingest(source, [dict(origin=f"u{n}", message=f"unique shape {'x' * (n % 7)} word{n % 977} {n}", service="app") for n in range(TEMPLATES_PER_SOURCE + 300)])
    with store.connect() as db:
        count = db.execute("SELECT count(*) FROM templates WHERE source_id=?", (source["id"],)).fetchone()[0]
    assert count <= TEMPLATES_PER_SOURCE
