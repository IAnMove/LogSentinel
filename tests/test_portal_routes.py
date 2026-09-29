"""Structural contracts of the route table, independent of how it is organised."""

import re

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, background=False)


def api_routes(app):
    for route in app.routes:
        for method in sorted(getattr(route, "methods", None) or ()):
            if route.path.startswith("/api/") and method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                yield method, route.path


def test_every_api_route_refuses_a_visitor_without_a_session(app):
    checked = 0
    with TestClient(app, base_url="http://localhost") as visitor:
        visitor.headers["X-LogSentinel"] = "portal"
        for method, path in api_routes(app):
            concrete = re.sub(r"\{[^}]+\}", "x", path)
            response = visitor.request(method, concrete, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked > 50  # a refactor that loses routes would loosen this silently


def test_only_login_enrollment_and_token_authenticated_reception_accept_a_post_without_a_session(app):
    """A new open POST route must be added here on purpose, not by accident."""
    open_posts = {
        route.path
        for route in app.routes
        if "POST" in (getattr(route, "methods", None) or ()) and not route.path.startswith("/api/")
    }
    assert open_posts == {
        "/login",          # the access key is the credential
        "/enroll",         # a single-use code is the credential
        "/heartbeat/{id}", # a per-source token is the credential
        "/ingest/{id}",
        "/ingest-metrics/{id}",
    }


def test_the_panel_serves_the_page_and_static_files_without_a_session(app):
    with TestClient(app, base_url="http://localhost") as visitor:
        assert visitor.get("/").status_code == 200
        assert visitor.get("/static/app.js").status_code == 200
        assert visitor.get("/healthz").status_code in (200, 503)


def test_static_files_are_cached_sensibly_and_everything_else_is_not(app):
    with TestClient(app, base_url="http://localhost") as visitor:
        script = visitor.get("/static/app.js")
        assert script.status_code == 200 and script.headers["cache-control"] == "no-cache"
        again = visitor.get("/static/app.js", headers={"If-None-Match": script.headers["etag"]})
        assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
        image = visitor.get("/static/tentri-icon-mono-v1.png")
        assert image.status_code == 200 and image.headers["cache-control"] == "public, max-age=86400"
        assert visitor.get("/").headers["cache-control"] == "no-store"
        assert visitor.get("/api/state").headers["cache-control"] == "no-store"
        assert visitor.get("/static/missing.js").headers["cache-control"] == "no-store"
        # The protective headers are unchanged on every kind of response.
        for path in ("/static/app.js", "/", "/api/state"):
            headers = visitor.get(path).headers
            assert headers["x-content-type-options"] == "nosniff"
            assert "default-src 'self'" in headers["content-security-policy"]


def test_refusals_carry_the_protective_headers_too(app):
    with TestClient(app, base_url="http://localhost") as visitor:
        cases = [
            visitor.get("/api/state"),                                        # 401: no session
            visitor.post("/login", json={"token": "x"}),                      # 403: no CSRF header
            visitor.get("/", headers={"host": "evil.example"}),               # 400: untrusted host
        ]
        for response in cases:
            assert response.status_code in (400, 401, 403), response.status_code
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-frame-options"] == "DENY"
            assert "default-src 'self'" in response.headers["content-security-policy"]
