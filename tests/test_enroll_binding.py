"""Claiming a package must not rebind a spool that already delivers for another source."""

import json
import time

import pytest

from logsentinel.portal.enrollment_client import claim
from logsentinel.portal.store import Store, dumps


def package(source_id="src-b", receiver="http://127.0.0.1:8767"):
    return dict(logsentinel_enrollment=1, receiver=receiver, source_id=source_id, code="synthetic", expires=int(time.time() + 3600))


class Client:
    def __init__(self):
        self.posts = 0

    def post(self, *args, **kwargs):
        self.posts += 1

        class Response:
            status_code = 200

            def json(self):
                return {"token": "new-token"}

        return Response()

    def close(self):
        pass


def bound_spool(tmp_path, source_id="src-a", receiver="http://127.0.0.1:8767"):
    spool = tmp_path / "spool"
    store = Store(spool)
    store.set_meta("sender_binding", dumps(["logs", receiver, source_id, "/var/log/app.log"]))
    (spool / "push-token").write_text("old-token\n")
    return spool


def test_a_package_for_another_source_is_refused_and_the_old_token_kept(tmp_path):
    spool = bound_spool(tmp_path)
    client = Client()
    with pytest.raises(ValueError, match="already delivers for source src-a"):
        claim(package("src-b"), spool, client=client)
    assert client.posts == 0, "nothing is redeemed"
    assert (spool / "push-token").read_text() == "old-token\n"


def test_a_package_for_another_receiver_is_refused_too(tmp_path):
    spool = bound_spool(tmp_path, source_id="src-a")
    with pytest.raises(ValueError, match="already delivers"):
        claim(package("src-a", receiver="http://localhost:8767"), spool, client=Client())


def test_the_same_source_can_be_re_enrolled_to_rotate_its_token(tmp_path):
    spool = bound_spool(tmp_path)
    result = claim(package("src-a"), spool, client=Client())
    assert result["source_id"] == "src-a"
    assert (spool / "push-token").read_text().strip() == "new-token"


def test_a_fresh_spool_is_free(tmp_path):
    result = claim(package("src-z"), tmp_path / "fresh", client=Client())
    assert result["source_id"] == "src-z"
