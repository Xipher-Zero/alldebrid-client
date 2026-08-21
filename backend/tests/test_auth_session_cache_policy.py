from fastapi import Request

from api import auth_routes
from auth.models import Principal


def _request():
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/auth/session",
            "raw_path": b"/api/auth/session",
            "query_string": b"",
            "headers": [(b"host", b"pulse.example")],
            "client": ("127.0.0.1", 12345),
            "server": ("pulse.example", 443),
        }
    )
    request.state.principal = Principal.password_session("operator")
    return request


def test_session_status_response_is_never_cacheable():
    response = auth_routes.auth_session_status(_request())
    assert response.headers["Cache-Control"] == "no-store"
