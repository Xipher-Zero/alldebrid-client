from api.auth_config_routes import AuthenticationConfigUpdate, _prospective_password_ready
from auth.passwords import hash_password
from core.config import AppSettings


def test_route_clear_password_intent_wins_over_simultaneous_plaintext():
    candidate = AppSettings(
        auth_password_enabled=True,
        auth_username="operator",
    )
    candidate.auth_password_hash = hash_password("old-secret")
    update = AuthenticationConfigUpdate(
        auth_password_enabled=True,
        auth_password="new-but-discarded",
        clear_password=True,
    )

    assert _prospective_password_ready(candidate, update) is False
