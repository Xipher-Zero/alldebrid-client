from pathlib import Path

manager_path = Path("backend/services/manager_v2.py")
manager = manager_path.read_text()
import_token = "                from api.routes import _sse_broadcast\n"
call_token = "_sse_broadcast("
if manager.count(import_token) != 6:
    raise RuntimeError(f"expected 6 remaining route imports, found {manager.count(import_token)}")
if manager.count(call_token) != 6:
    raise RuntimeError(f"expected 6 remaining SSE calls, found {manager.count(call_token)}")
manager = manager.replace(import_token, "")
manager = manager.replace(call_token, "publish(")
manager_path.write_text(manager)

scheduler_path = Path("backend/core/scheduler.py")
scheduler = scheduler_path.read_text()
old = '''    _last_notified: str = ""\n    while True:\n        try:\n            cfg = get_settings()\n'''
new = '''    _last_notified: str = ""\n    while True:\n        # Keep a valid backoff even if settings retrieval itself fails.\n        interval_h = 12\n        try:\n            cfg = get_settings()\n'''
if scheduler.count(old) != 1:
    raise RuntimeError("update-check loop shape changed unexpectedly")
scheduler_path.write_text(scheduler.replace(old, new))

test_path = Path("backend/tests/test_v106_audit_contracts.py")
tests = test_path.read_text().rstrip()
append = '''\n\ndef test_update_check_loop_has_failure_safe_backoff():\n    source = (Path(__file__).resolve().parents[1] / "core" / "scheduler.py").read_text()\n    loop = source.split("async def update_check_loop", 1)[1].split("async def events_ttl_loop", 1)[0]\n    assert "while True:\\n        # Keep a valid backoff even if settings retrieval itself fails.\\n        interval_h = 12\\n        try:" in loop\n    assert "await asyncio.sleep(max(3600, interval_h * 3600))" in loop\n'''
if "test_update_check_loop_has_failure_safe_backoff" in tests:
    raise RuntimeError("scheduler backoff test already exists")
test_path.write_text(tests + append.rstrip() + "\n")

print("v1.0.6 event boundary and scheduler cleanup applied")
