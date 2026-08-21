from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected >= {minimum} matches, found {count}: {old!r}")
    target.write_text(text.replace(old, new))


# Cancellation safety must mark restart responsibility before the interruptible
# stop itself, but only after every pre-stop wipe guard/recheck has passed.
replace_once(
    "backend/api/routes.py",
    '''        scheduler_was_running = scheduler_runtime.scheduler_running()\n        # Mark intent before the interruptible stop: stop_scheduler clears/cancels\n        # its task list before awaiting task completion.\n        scheduler_stopped = scheduler_was_running\n        quiesced = False\n''',
    '''        scheduler_was_running = scheduler_runtime.scheduler_running()\n        scheduler_stopped = False\n        quiesced = False\n''',
)
replace_once(
    "backend/api/routes.py",
    '''                if scheduler_stopped:\n                    await scheduler_runtime.stop_scheduler()\n''',
    '''                if scheduler_was_running:\n                    # Claim restart responsibility before the interruptible stop.\n                    scheduler_stopped = True\n                    await scheduler_runtime.stop_scheduler()\n''',
)

# Existing release-contract tests must follow the corrected current-V1 metadata.
for test_path in (
    "backend/tests/test_license_policy.py",
    "backend/tests/test_v1_scope.py",
):
    replace_all(
        test_path,
        "DebridPulse — Multi-provider Debrid Download Manager",
        "DebridPulse — AllDebrid + aria2 Download Manager",
    )

print("Applied v1.0.6 corrective fixup")
