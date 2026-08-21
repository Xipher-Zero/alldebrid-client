from core.config import AppSettings
from core.config_validator import validate_and_sanitise


def test_oidc_client_secret_is_excluded_from_model_serialization():
    cfg = AppSettings(oidc_client_secret="super-secret")
    dumped = cfg.model_dump()
    assert "oidc_client_secret" not in dumped
    assert "super-secret" not in repr(dumped)


def test_oidc_client_secret_survives_validation_without_becoming_serializable():
    cfg = AppSettings(
        auth_oidc_enabled=True,
        oidc_issuer_url="https://id.example/application/o/debridpulse",
        oidc_client_id="client",
        oidc_client_secret="super-secret",
        public_base_url="https://pulse.example",
    )
    validated = validate_and_sanitise(cfg)
    assert validated.oidc_client_secret == "super-secret"
    assert "oidc_client_secret" not in validated.model_dump()
