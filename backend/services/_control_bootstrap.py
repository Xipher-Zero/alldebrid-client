"""Post-import bootstrap for DebridPulse transfer-control hardening.

The package initializer installs this hook before ``services.manager_v2`` is
loaded. The normal module loader runs first; once the singleton manager exists
we attach the v1.0.3 transfer-control reliability layer and its parent-status
guard.
"""
from __future__ import annotations

import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
from types import ModuleType

_TARGET = "services.manager_v2"
_HOOK_MARKER = "_debridpulse_transfer_control_import_hook"


def _install_manager_control(manager) -> None:
    from services.transfer_control import install_transfer_control
    from services.pause_parent_status import install_parent_progress_guard

    install_transfer_control(manager)
    install_parent_progress_guard(manager)


class _PostLoadManagerLoader(Loader):
    def __init__(self, wrapped: Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):
        create = getattr(self._wrapped, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _install_manager_control(module.manager)


class _ManagerFinder(MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if fullname != _TARGET:
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        spec = PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _PostLoadManagerLoader(spec.loader)
        return spec


def install_import_hook() -> None:
    existing = sys.modules.get(_TARGET)
    if existing is not None and getattr(existing, "manager", None) is not None:
        _install_manager_control(existing.manager)
        return
    if getattr(sys, _HOOK_MARKER, False):
        return
    sys.meta_path.insert(0, _ManagerFinder())
    setattr(sys, _HOOK_MARKER, True)
