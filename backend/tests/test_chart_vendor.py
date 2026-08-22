from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_chartjs_is_local_and_current():
    vendor = (ROOT / "frontend/static/vendor/chart.umd.min.js").read_text()
    index = (ROOT / "frontend/static/index.html").read_text()
    docs = (ROOT / "docs/DEPENDENCY_LICENSES.md").read_text()
    license_text = (ROOT / "licenses/Chart.js-MIT.txt").read_text()

    assert "Chart.js v4.5.1" in vendor
    assert "vendor/chart.umd.min.js" in index
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js" not in index
    assert "Chart.js | 4.5.1" in docs
    assert "MIT License" in license_text
