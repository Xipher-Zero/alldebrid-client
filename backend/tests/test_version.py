from core.version import normalize_version_tag


def test_normalize_version_tag_accepts_fork_and_legacy_tags():
    assert normalize_version_tag("internal-v0.9.1") == "0.9.1"
    assert normalize_version_tag("v1.9.9") == "1.9.9"
    assert normalize_version_tag("0.9.1") == "0.9.1"
