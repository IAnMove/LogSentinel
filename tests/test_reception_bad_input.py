"""A stranger who can reach the reception port gets a plain refusal, never a crash and a traceback."""

import logging

import pytest
from fastapi.testclient import TestClient

from tests.test_portal_ingest import pair  # noqa: F401


@pytest.mark.parametrize("body", [b"{{", b"", b"\xff\xfe\x00", b'{"events": [', b"nul\x00l"])
def test_malformed_json_is_a_400_without_a_server_error_in_the_log(pair, body, caplog):  # noqa: F811
    panel, reception, source, token, machine = pair
    client = TestClient(reception.app, base_url="https://sentinel.invalid", raise_server_exceptions=False)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    with caplog.at_level(logging.ERROR):
        refused = [
            client.post("/enroll", content=body, headers={"Content-Type": "application/json"}),
            client.post("/ingest/" + source, content=body, headers=headers),
            client.post("/heartbeat/" + source, content=body, headers=headers),
        ]
    assert [r.status_code for r in refused] == [400, 400, 400], [r.text for r in refused]
    assert all("Traceback" not in r.text for r in refused)
    assert not [r for r in caplog.records if r.exc_info], "a malformed body must not log a stack trace"


def test_a_bad_token_is_still_refused_before_the_body_is_looked_at(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    client = TestClient(reception.app, base_url="https://sentinel.invalid", raise_server_exceptions=False)
    refused = client.post("/ingest/" + source, content=b"{{", headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"})
    assert refused.status_code == 401
