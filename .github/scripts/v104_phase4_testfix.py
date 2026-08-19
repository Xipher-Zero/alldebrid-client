from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
test_file = ROOT / "backend/tests/test_manager_v2.py"
helper = ROOT / ".github/scripts/v104_phase4_testfix.py"

text = test_file.read_text()
old = '''        # unlock_link should have been called only ONCE (duplicate skipped)\n        self.assertEqual(fake_ad.unlock_link.await_count, 1)\n        self.assertEqual(mgr._log_file.await_count, 1)\n'''
new = '''        # Manifest preparation no longer unlocks provider links eagerly. The\n        # duplicate is collapsed before the one-row manifest batch is persisted;\n        # URL generation happens later when the dispatcher has a free slot.\n        self.assertEqual(fake_ad.unlock_link.await_count, 0)\n        self.assertEqual(mgr._log_file.await_count, 0)\n        fake_db.executemany.assert_awaited_once()\n        manifest_rows = fake_db.executemany.await_args.args[1]\n        self.assertEqual(len(manifest_rows), 1)\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one duplicate-entry test block, found {count}")
test_file.write_text(text.replace(old, new, 1))
helper.unlink()
print("v1.0.4 slot-aware unlock test contract updated")
