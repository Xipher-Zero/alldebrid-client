from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v103_staging_candidate_preserves_external_aria2_global_policy():
    assert (REPO_ROOT / "VERSION").read_text().strip() == "1.0.3"

    control = (REPO_ROOT / "backend/services/transfer_control.py").read_text()
    bootstrap = (REPO_ROOT / "backend/services/__init__.py").read_text()

    assert "install_import_hook" in bootstrap
    assert "max-overall-download-limit" not in control
    assert "change_global_options" not in control
    assert "_aria2_owned_gids" in control
    assert "Blocked attempt to remove foreign aria2 GID" not in control
