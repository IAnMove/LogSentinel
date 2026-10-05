"""A file destination is a name inside notifications/, and a bad one is refused when it is saved."""

import pytest


@pytest.mark.parametrize("path", ["../../evil.jsonl", "sub/dir.jsonl", "/etc/cron.d/x", "..", ".", "a/../b.jsonl", "..\\evil.jsonl"])
def test_a_path_that_is_not_a_plain_filename_is_refused_on_save(client, path):
    c, store = client
    refused = c.post("/api/objects/destination", json={"name": "Log", "kind": "file", "enabled": True, "path": path})
    assert refused.status_code == 422, refused.text
    assert "filename" in refused.text
    assert not store.objects("destination")


@pytest.mark.parametrize("path", ["", "alerts.jsonl", "my alerts.log", "ñandú.jsonl"])
def test_an_ordinary_filename_or_none_is_accepted(client, path):
    c, store = client
    saved = c.post("/api/objects/destination", json={"name": "Log", "kind": "file", "enabled": True, "path": path})
    assert saved.status_code == 200, saved.text


def test_the_path_of_a_non_file_destination_is_not_judged(client):
    c, store = client
    saved = c.post("/api/objects/destination", json={"name": "Hook", "kind": "webhook", "enabled": True, "url": "https://example.com/hook", "path": "../x"})
    assert saved.status_code == 200, saved.text
