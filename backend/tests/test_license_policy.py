import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _locked_runtime_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for raw_line in (REPO_ROOT / "backend/requirements.txt").read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        name, version = line.split("==", 1)
        packages[_normalized_name(name)] = version.split(";", 1)[0].strip()
    return packages


def test_runtime_license_inventory_matches_lock_exactly():
    manifest = json.loads(
        (REPO_ROOT / "licenses/python-runtime.json").read_text()
    )
    inventoried = {
        _normalized_name(item["name"]): item["version"]
        for item in manifest["packages"]
    }
    assert inventoried == _locked_runtime_packages()


def test_runtime_inventory_has_no_unknown_or_unreviewed_copyleft_license():
    manifest = json.loads(
        (REPO_ROOT / "licenses/python-runtime.json").read_text()
    )
    for item in manifest["packages"]:
        license_id = item["license"].upper()
        assert "UNKNOWN" not in license_id
        assert "AGPL" not in license_id
        assert "GPL" not in license_id


def test_v1_license_and_upstream_notice_are_present():
    license_text = (REPO_ROOT / "LICENSE").read_text()
    notice = (REPO_ROOT / "NOTICE").read_text()
    upstream_mit = (REPO_ROOT / "LICENSES/MIT.txt").read_text()

    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 2, June 1991" in license_text
    assert "Copyright (C) 2026 Chris Moore" in notice
    assert "c0f7a5bfeba4f259fb2acc62ac6eed27e8ac4d5c" in notice
    assert "Copyright (c) 2026 kroeberd" in upstream_mit


def test_current_project_surfaces_state_the_debridpulse_gpl_identity():
    readme = (REPO_ROOT / "README.md").read_text()
    landing_page = (REPO_ROOT / "index.html").read_text()
    notice = (REPO_ROOT / "NOTICE").read_text()
    source_offer = (REPO_ROOT / "SOURCE_OFFER.md").read_text()

    assert "DebridPulse" in readme
    assert "GPL-2.0-or-later" in readme
    assert "DebridPulse · GPL-2.0-or-later" in landing_page
    assert "MIT License" not in landing_page
    assert notice.startswith("DebridPulse — Multi-provider Debrid Download Manager")
    assert "https://github.com/Xipher-Zero/debridpulse/issues" in source_offer
