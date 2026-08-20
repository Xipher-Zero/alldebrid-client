"""Regression coverage for DebridPulse pause parent-state semantics."""
from __future__ import annotations

import inspect

from services.manager_v2 import manager
from services.pause_parent_status import (
    _RUNNABLE_FILE_STATES,
    derive_parent_status,
)


def test_terminal_error_sibling_does_not_make_selectively_paused_work_queued():
    # Three unfinished DB rows can include two runnable paused files plus one
    # terminal error. A real selective pause is derived from the two controllable
    # rows and durable pause intent, not from the terminal sibling.
    assert derive_parent_status(
        current_status="paused",
        unfinished_files=3,
        runnable_files=2,
        paused_files=2,
        live_active=False,
        live_waiting=False,
        selectively_paused=True,
        globally_paused=False,
    ) == "paused"


def test_global_pause_keeps_physically_paused_work_visibly_paused():
    assert derive_parent_status(
        current_status="paused",
        unfinished_files=2,
        runnable_files=2,
        paused_files=2,
        live_active=False,
        live_waiting=False,
        selectively_paused=False,
        globally_paused=True,
    ) == "paused"


def test_resumed_transfer_waiting_for_slot_is_queued_not_paused():
    # Resume clears selective intent immediately. If no delivery slot is free,
    # aria2 intentionally remains physically paused until the coordinator can
    # unpause it. The operator-visible state is queued/eligible, not paused.
    assert derive_parent_status(
        current_status="queued",
        unfinished_files=1,
        runnable_files=1,
        paused_files=1,
        live_active=False,
        live_waiting=False,
        selectively_paused=False,
        globally_paused=False,
    ) == "queued"


def test_selective_pause_intent_covers_no_gid_materialization_gap():
    # A pending no-GID child may briefly remain in the DB while the durable
    # pause intent is already authoritative. If aria2 has no active/waiting
    # child, the parent must stay visibly paused instead of bouncing queued.
    assert derive_parent_status(
        current_status="paused",
        unfinished_files=3,
        runnable_files=2,
        paused_files=1,
        live_active=False,
        live_waiting=False,
        selectively_paused=True,
        globally_paused=False,
    ) == "paused"


def test_observed_aria2_state_wins_until_pause_is_physically_confirmed():
    assert derive_parent_status(
        current_status="queued",
        unfinished_files=2,
        runnable_files=2,
        paused_files=1,
        live_active=False,
        live_waiting=True,
        selectively_paused=True,
        globally_paused=False,
    ) == "queued"
    assert derive_parent_status(
        current_status="downloading",
        unfinished_files=2,
        runnable_files=2,
        paused_files=1,
        live_active=True,
        live_waiting=False,
        selectively_paused=True,
        globally_paused=False,
    ) == "downloading"


def test_parent_progress_guard_initializes_intent_before_deriving_state():
    coordinator = manager._dp_transfer_control
    assert coordinator._parent_progress_guard_installed is True
    source = inspect.getsource(coordinator._orig_parent_progress)
    assert "await coordinator.ensure_initialized()" in source
    assert "_RUNNABLE_FILE_STATES" in source
    assert "selectively_paused=int(torrent_id) in coordinator._pause_intents" in source
    assert "globally_paused=globally_paused" in source
    assert _RUNNABLE_FILE_STATES == {"pending", "queued", "downloading", "paused"}
