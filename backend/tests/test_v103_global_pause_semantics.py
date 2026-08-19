"""Regression contracts for mixed Pause All / selective Resume semantics."""
from __future__ import annotations

import inspect
from pathlib import Path

from services.global_pause_semantics import _paused_sibling_ids
from services.manager_v2 import manager


def test_paused_sibling_selection_excludes_only_selected_transfer():
    rows = [{"id": 9}, {"id": 3}, {"id": 7}, {"id": 3}]
    assert _paused_sibling_ids(rows, 7) == [3, 9]


def test_global_pause_release_is_ordered_before_selected_resume():
    source = inspect.getsource(manager.resume_torrent)
    persist = source.index("await _persist_transition(")
    release = source.index("_set_global_paused(False)")
    resume = source.index("await coordinator._resume_parent(torrent_id)")
    assert persist < release < resume
    assert "WHERE status='paused' AND id!=?" in source
    assert "target_paused=False" in source


def test_failed_selected_resume_restores_safe_pause_state():
    source = inspect.getsource(manager.resume_torrent)
    assert "target_paused=True" in source
    assert "await coordinator._pause_parent(" in source
    assert "_set_global_paused(True)" in source


def test_existing_resume_paused_topbar_contract_remains_available():
    app = (Path(__file__).resolve().parents[2] / "frontend/static/app.js").read_text()
    assert "!globallyPaused && selectivelyPaused > 0" in app
    assert "Resume Paused (${selectivelyPaused})" in app
    assert "pausedTransferCount =" in app
