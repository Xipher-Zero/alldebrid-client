from pathlib import Path

ROOT = Path(__file__).resolve().parent
manager_path = ROOT / "backend/services/manager_v2.py"
test_path = ROOT / "backend/tests/test_ui_responsiveness.py"

manager = manager_path.read_text(encoding="utf-8")

old = '''        provider_state_changed = (\n            provider_status != (row["provider_status"] or "")\n            or status_code != int(row["provider_status_code"] or -1)\n        )'''
new = '''        current_provider_code = row.get("provider_status_code")\n        provider_state_changed = (\n            provider_status != (row["provider_status"] or "")\n            or status_code != int(\n                current_provider_code\n                if current_provider_code is not None\n                else -1\n            )\n        )'''
if manager.count(old) != 1:
    raise SystemExit(f"provider-state guard occurrence mismatch: {manager.count(old)}")
manager = manager.replace(old, new, 1)

old = '''        elif provider_status == "ready" and current_status not in (TorrentStatus.DOWNLOADING, TorrentStatus.QUEUED, TorrentStatus.COMPLETED, TorrentStatus.DELETED):'''
new = '''        elif provider_status == "ready" and current_status not in (\n            TorrentStatus.DOWNLOADING,\n            TorrentStatus.QUEUED,\n            TorrentStatus.PAUSED,\n            TorrentStatus.COMPLETED,\n            TorrentStatus.DELETED,\n        ):'''
if manager.count(old) != 1:
    raise SystemExit(f"ready-state exclusion occurrence mismatch: {manager.count(old)}")
manager = manager.replace(old, new, 1)
manager_path.write_text(manager, encoding="utf-8")

tests = test_path.read_text(encoding="utf-8").rstrip()
addition = r'''


def test_pass3_provider_noop_handles_zero_status_code_and_paused_delivery():
    manager = (REPO_ROOT / "backend/services/manager_v2.py").read_text()
    provider = manager.split(
        "async def _apply_provider_update", 1
    )[1].split(
        "async def _increment_poll_failure", 1
    )[0]

    assert 'current_provider_code = row.get("provider_status_code")' in provider
    assert "if current_provider_code is not None" in provider
    assert "TorrentStatus.PAUSED" in provider
'''
if "test_pass3_provider_noop_handles_zero_status_code_and_paused_delivery" in tests:
    raise SystemExit("follow-up test already present")
test_path.write_text(tests + addition + "\n", encoding="utf-8")

print("PASS3 FOLLOW-UP CONTRACT: PASS")
