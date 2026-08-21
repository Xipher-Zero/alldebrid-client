import json
from types import SimpleNamespace

from auth.passwords import BasicVerificationCache, hash_password, verify_password
from auth.throttle import FailureThrottle


def test_argon2id_password_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert "correct horse battery staple" not in encoded
    assert verify_password(encoded, "correct horse battery staple") is True
    assert verify_password(encoded, "wrong") is False
    assert verify_password("", "anything") is False
    assert verify_password("not-an-argon2-hash", "anything") is False


def test_basic_verification_cache_is_bounded_and_verifier_specific():
    cache = BasicVerificationCache(max_entries=2, ttl_seconds=30)
    first_hash = hash_password("first")
    second_hash = hash_password("second")

    cache.remember("operator", "first", first_hash)
    assert cache.contains("operator", "first", first_hash) is True
    assert cache.contains("operator", "first", second_hash) is False
    assert cache.contains("operator", "wrong", first_hash) is False

    cache.remember("operator", "second", second_hash)
    cache.remember("other", "third", second_hash)
    assert cache.size == 2
    assert cache.contains("operator", "first", first_hash) is False

    cache.clear()
    assert cache.size == 0


def test_failure_throttle_increases_caps_and_recovers_on_success():
    throttle = FailureThrottle(
        max_entries=2,
        reset_after_seconds=300,
        free_failures=1,
        base_delay_seconds=0.25,
        max_delay_seconds=0.5,
    )
    key = "127.0.0.1"
    assert throttle.delay_for(key) == 0

    throttle.record_failure(key)
    assert throttle.delay_for(key) == 0
    throttle.record_failure(key)
    assert throttle.delay_for(key) == 0.25
    throttle.record_failure(key)
    assert throttle.delay_for(key) == 0.5
    throttle.record_failure(key)
    assert throttle.delay_for(key) == 0.5

    throttle.record_success(key)
    assert throttle.delay_for(key) == 0

    throttle.record_failure("a")
    throttle.record_failure("b")
    throttle.record_failure("c")
    assert throttle.size == 2


def test_legacy_plaintext_password_migrates_and_is_removed(monkeypatch, tmp_path):
    import core.config as config

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "auth_username": "operator",
        "auth_password": "legacy-secret",
    }))
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_settings", config.AppSettings())

    migrated = config.load_settings()
    persisted = json.loads(config_path.read_text())

    assert migrated.auth_password_enabled is True
    assert migrated.auth_username == "operator"
    assert migrated.auth_password == ""
    assert migrated.auth_password_hash.startswith("$argon2id$")
    assert verify_password(migrated.auth_password_hash, "legacy-secret") is True
    assert "auth_password" not in persisted
    assert persisted["auth_password_hash"] == migrated.auth_password_hash
    assert persisted["auth_password_enabled"] is True


def test_incomplete_legacy_auth_stays_open(monkeypatch, tmp_path):
    import core.config as config

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"auth_username": "operator", "auth_password": ""}))
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_settings", config.AppSettings())

    migrated = config.load_settings()
    persisted = json.loads(config_path.read_text())

    assert migrated.auth_password_enabled is False
    assert migrated.auth_password_hash == ""
    assert "auth_password" not in persisted
    assert persisted["auth_password_enabled"] is False


def test_missing_config_does_not_get_created_for_auth_defaults(monkeypatch, tmp_path):
    import core.config as config

    config_path = tmp_path / "missing.json"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_settings", config.AppSettings())

    loaded = config.load_settings()
    assert loaded.auth_password_enabled is False
    assert config_path.exists() is False


def test_unrelated_settings_save_preserves_hidden_password_hash(monkeypatch, tmp_path):
    import core.config as config

    config_path = tmp_path / "config.json"
    password_hash = hash_password("secret")
    previous = config.AppSettings(
        auth_password_enabled=True,
        auth_username="operator",
        auth_password_hash=password_hash,
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_settings", previous)

    replacement = config.AppSettings(
        auth_password_enabled=True,
        auth_username="operator",
        max_concurrent_downloads=7,
    )
    config.save_settings(replacement)
    persisted = json.loads(config_path.read_text())

    assert replacement.auth_password_hash == password_hash
    assert persisted["auth_password_hash"] == password_hash
    assert "auth_password" not in persisted


def test_new_plaintext_settings_input_is_hashed_before_persistence(monkeypatch, tmp_path):
    import core.config as config

    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_settings", config.AppSettings())

    settings = config.AppSettings(
        auth_password_enabled=True,
        auth_username="operator",
        auth_password="new-secret",
    )
    config.save_settings(settings)
    persisted = json.loads(config_path.read_text())

    assert settings.auth_password == ""
    assert settings.auth_password_hash.startswith("$argon2id$")
    assert verify_password(settings.auth_password_hash, "new-secret") is True
    assert "auth_password" not in persisted
    assert persisted["auth_password_hash"] == settings.auth_password_hash


def test_password_hash_is_excluded_from_normal_model_dump():
    settings = SimpleNamespace()
    from core.config import AppSettings

    settings = AppSettings(auth_password_hash=hash_password("secret"))
    assert "auth_password_hash" not in settings.model_dump()
