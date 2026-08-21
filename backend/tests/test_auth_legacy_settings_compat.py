from api.routes import SettingsUpdate, _merge_secret_settings
from core.config import AppSettings


def _previous():
    cfg = AppSettings(
        auth_password_enabled=True,
        auth_username="operator",
    )
    cfg.auth_password_hash = "stored-argon2-hash"
    return cfg


def test_legacy_settings_blank_password_preserves_stored_hash():
    previous = _previous()
    update = SettingsUpdate(
        auth_password_enabled=True,
        auth_username="operator",
        auth_password="",
    )

    merged = _merge_secret_settings(update, previous)
    candidate = AppSettings(**merged)

    assert candidate.auth_password_hash_clear is False


def test_legacy_settings_explicit_password_clear_carries_destructive_intent():
    previous = _previous()
    update = SettingsUpdate(
        auth_password_enabled=False,
        auth_username="operator",
        auth_password="",
        clear_secrets=["auth_password"],
    )

    merged = _merge_secret_settings(update, previous)
    candidate = AppSettings(**merged)

    assert merged["auth_password"] == ""
    assert merged["auth_password_hash_clear"] is True
    assert candidate.auth_password_hash_clear is True
