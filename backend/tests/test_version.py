from core.version import normalize_version_tag


def test_normalize_version_tag_accepts_fork_and_legacy_tags():
    assert normalize_version_tag("internal-v2.3.4") == "2.3.4"
    assert normalize_version_tag("v1.9.9") == "1.9.9"
    assert normalize_version_tag("2.3.4") == "2.3.4"
