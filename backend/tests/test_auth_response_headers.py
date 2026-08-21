from pathlib import Path


def test_request_id_and_security_headers_wrap_authentication_boundaries():
    """Auth/security short-circuit responses must retain baseline response headers."""
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()

    auth_at = source.index("async def authentication_boundary_middleware")
    browser_security_at = source.index("async def general_web_security_middleware")
    response_headers_at = source.index("async def request_id_middleware")

    # FastAPI/Starlette decorator middleware registered later wraps middleware
    # registered earlier, so request-id/security-header middleware must remain
    # last among these boundaries.
    assert auth_at < browser_security_at < response_headers_at
    assert 'response.headers["X-Request-ID"] = req_id' in source
    assert 'response.headers.setdefault("X-Content-Type-Options", "nosniff")' in source
    assert 'response.headers.setdefault("Referrer-Policy", "no-referrer")' in source
    assert 'response.headers.setdefault("X-Frame-Options", "DENY")' in source
