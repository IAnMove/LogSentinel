"""A sender's hourly allowance throttles it; it must never refuse a sender for good."""

from logsentinel.portal.store import QUOTA_WINDOW, Store

MIB = 1024 * 1024
T = 1_700_000_000.0  # a realistic clock: the empty window starts at 0


def store_with_quota(tmp_path, megabytes=1, events=100):
    store = Store(tmp_path)
    settings = store.settings()
    settings.sender_mb_per_hour = megabytes
    settings.sender_events_per_hour = events
    store.set_meta("settings", settings.model_dump_json())
    return store, store.settings()


def test_a_request_bigger_than_the_whole_allowance_is_accepted_into_an_empty_window(tmp_path):
    store, settings = store_with_quota(tmp_path, megabytes=1)
    assert store.charge_sender_quota("s", 3 * MIB, 10, settings, now=T + 1000.0) == 0


def test_the_request_after_it_waits_for_the_window_to_end(tmp_path):
    store, settings = store_with_quota(tmp_path, megabytes=1)
    store.charge_sender_quota("s", 3 * MIB, 10, settings, now=T + 1000.0)
    wait = store.charge_sender_quota("s", 1, 1, settings, now=T + 1060.0)
    assert wait == int(1000 + QUOTA_WINDOW - 1060)
    assert store.charge_sender_quota("s", 1, 1, settings, now=T + 1000.0 + QUOTA_WINDOW) == 0


def test_too_many_events_in_one_request_do_not_lock_a_sender_out_either(tmp_path):
    store, settings = store_with_quota(tmp_path, events=100)
    assert store.charge_sender_quota("s", 1000, 500, settings, now=T + 5.0) == 0
    assert store.charge_sender_quota("s", 1000, 1, settings, now=T + 6.0) > 0


def test_a_request_that_fits_is_billed_as_before(tmp_path):
    store, settings = store_with_quota(tmp_path, megabytes=1)
    assert store.charge_sender_quota("s", MIB // 2, 5, settings, now=T + 1.0) == 0
    assert store.charge_sender_quota("s", MIB // 2, 5, settings, now=T + 2.0) == 0
    assert store.charge_sender_quota("s", 1, 1, settings, now=T + 3.0) > 0


def test_one_sender_spending_its_allowance_does_not_touch_another(tmp_path):
    store, settings = store_with_quota(tmp_path, megabytes=1)
    store.charge_sender_quota("a", MIB, 5, settings, now=T + 1.0)
    assert store.charge_sender_quota("a", 1, 1, settings, now=T + 2.0) > 0
    assert store.charge_sender_quota("b", MIB, 5, settings, now=T + 2.0) == 0
