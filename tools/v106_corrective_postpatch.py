from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "backend/tests/test_v106_corrective_regressions.py"
text = path.read_text(encoding="utf-8")
old = '''    preserve = SettingsUpdate(**previous.model_dump(), alldebrid_api_key="", auth_password="")
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    replace = SettingsUpdate(**previous.model_dump(), auth_username="new-user", auth_password="new-pass")
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    clear = SettingsUpdate(**previous.model_dump(), auth_password="", clear_secrets=["auth_password"])
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    with pytest.raises(Exception):
        bad = SettingsUpdate(**previous.model_dump(), clear_secrets=["not_a_secret"])
        _merge_secret_settings(bad, previous)
'''
new = '''    payload = previous.model_dump()
    payload.update(alldebrid_api_key="", auth_password="")
    preserve = SettingsUpdate(**payload)
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    payload = previous.model_dump()
    payload.update(auth_username="new-user", auth_password="new-pass")
    replace = SettingsUpdate(**payload)
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    payload = previous.model_dump()
    payload.update(auth_password="", clear_secrets=["auth_password"])
    clear = SettingsUpdate(**payload)
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    payload = previous.model_dump()
    payload.update(clear_secrets=["not_a_secret"])
    with pytest.raises(Exception):
        _merge_secret_settings(SettingsUpdate(**payload), previous)
'''
if old not in text:
    raise RuntimeError("corrective settings regression block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("corrective regression harness adjusted")
