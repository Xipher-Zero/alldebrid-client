from pathlib import Path


def test_obsolete_runtime_database_card_is_not_presented():
    root = Path(__file__).resolve().parents[2]
    index_html = (root / "frontend/static/index.html").read_text()
    app_js = (root / "frontend/static/app.js").read_text()

    assert "#tab-database > .scard:first-child { display: none; }" in index_html
    assert "Runtime Database" in app_js
    assert "Database Maintenance" in app_js
