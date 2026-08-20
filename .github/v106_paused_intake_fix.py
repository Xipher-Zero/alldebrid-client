from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1))


# The main migration initially placed the deferred-provider drain before the
# aria2 state lock. Preserve the established pause/reconciliation race contract:
# Pause All is sampled only after the state lock is acquired. A paused cycle
# returns from inside the try block (after finally), so code after finally runs
# only for an unpaused reconciliation cycle and is outside the aria2 lock.
replace_once(
    "backend/services/reconciliation_service.py",
    '''    async def reconcile(self):
        if self.engine.download_client_name() != "aria2":
            return
        if not bool(get_settings().paused):
            async with async_timer("reconcile.deferred_provider"):
                await self.engine.resume_deferred_provider_submissions()
        await self.control.ensure_initialized()
''',
    '''    async def reconcile(self):
        if self.engine.download_client_name() != "aria2":
            return
        await self.control.ensure_initialized()
''',
)

replace_once(
    "backend/services/reconciliation_service.py",
    '''        finally:
            _cycle_active.reset(active_token)

        if is_builtin_mode():
''',
    '''        finally:
            _cycle_active.reset(active_token)

        async with async_timer("reconcile.deferred_provider"):
            await self.engine.resume_deferred_provider_submissions()

        if is_builtin_mode():
''',
)

# v12 is intentional: paused-intake feedback changed app.js and must bypass
# browsers that cached the staging v11 script.
replace_once(
    "backend/tests/test_v1_scope.py",
    "    assert '/app.js?v=11' in index\n",
    "    assert '/app.js?v=12' in index\n",
)

# Guard the ordering contract directly.
source = (ROOT / "backend/services/reconciliation_service.py").read_text()
lock_at = source.index("async with self.engine._aria2_state_lock:")
pause_at = source.index("globally_paused = bool(get_settings().paused)")
drain_at = source.index('async_timer("reconcile.deferred_provider")')
finally_at = source.index("_cycle_active.reset(active_token)")
assert lock_at < pause_at < finally_at < drain_at

Path(__file__).unlink(missing_ok=True)
