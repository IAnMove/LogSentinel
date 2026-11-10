"""A live view gets the last lines stored and then only what arrives after them."""

from helpers import machine_source


def lines(c, **params):
    answer = c.get("/api/live", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def feed(store, source, *messages, start=0):
    store.ingest(
        store.get("source", source),
        [dict(origin="o%d" % (start + n), service="app", message=m) for n, m in enumerate(messages)],
    )


def test_the_tail_starts_with_recent_lines_and_then_follows_arrivals(client):
    c, store = client
    machine, source = machine_source(c)
    feed(store, source, "one", "two", "three")
    first = lines(c, limit=2)
    assert [e["message"] for e in first["events"]] == ["two", "three"]
    assert lines(c, after=first["position"])["events"] == []
    feed(store, source, "four", "five", start=3)
    more = lines(c, after=first["position"])
    assert [e["message"] for e in more["events"]] == ["four", "five"]
    assert more["position"] > first["position"]
    assert lines(c, after=more["position"])["events"] == []


def test_a_full_page_resumes_right_after_its_last_line(client):
    c, store = client
    machine, source = machine_source(c)
    feed(store, source, *["line %d" % n for n in range(7)])
    seen, position = [], 0
    for _ in range(4):
        page = lines(c, after=position, limit=3)
        seen += [e["message"] for e in page["events"]]
        position = page["position"]
    assert seen == ["line %d" % n for n in range(7)]


def test_the_tail_is_scoped_to_a_machine_and_leaves_out_observer_records(client):
    c, store = client
    machine, source = machine_source(c)
    other, other_source = machine_source(c)
    feed(store, source, "mine")
    feed(store, other_source, "theirs")
    c.app.state.health.report(
        dict(key="storage", machine_id=machine, title="Observer storage is approaching capacity", detail={}, severity="HIGH"),
        notify=False,
    )
    assert [e["message"] for e in lines(c)["events"]] == ["mine", "theirs"]
    scoped = lines(c, machine_id=machine)
    assert [e["message"] for e in scoped["events"]] == ["mine"]
    assert [e["message"] for e in lines(c, source_id=other_source)["events"]] == ["theirs"]
    # Level with the newest row even when that row belongs to someone else.
    feed(store, other_source, "theirs again", start=1)
    assert lines(c, machine_id=machine, after=scoped["position"])["events"] == []


def test_the_tail_needs_a_session_and_sane_bounds(client):
    c, store = client
    assert c.get("/api/live", params={"limit": 0}).status_code == 400
    assert c.get("/api/live", params={"after": -1}).status_code == 400
    c.post("/api/logout", json={})
    assert c.get("/api/live").status_code == 401
