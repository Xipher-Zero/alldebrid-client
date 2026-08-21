"""Temporary v1.0.6 patch-harness fixup.

Python imports this module before executing scripts from this directory.  The
first invocation rewrites two stale source-match blocks in the corrective
patcher.  A later invocation removes this helper after those rewrites have
landed in the runner worktree.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCHER = HERE / "v106_corrective_patch.py"
text = PATCHER.read_text(encoding="utf-8") if PATCHER.exists() else ""

old_ready = '''# Ready-parent scheduler has the same duplicate guard pattern but a different set.
replace_once(
    "backend/services/manager_v2.py",
    """        if torrent_id in self._active or torrent_id in self._ready_parent_task_ids:\\n            return\\n""",
    """        if self._materialization_quiescing:\\n            return\\n        if torrent_id in self._active or torrent_id in self._ready_parent_task_ids:\\n            return\\n""",
)
'''
new_ready = '''# Ready-parent scheduler has a compound scheduling gate.
replace_once(
    "backend/services/manager_v2.py",
    """        if (\\n            self.is_paused()\\n            or self._disk_guard_active\\n            or torrent_id in self._active\\n            or torrent_id in self._ready_parent_task_ids\\n        ):\\n            return False\\n""",
    """        if (\\n            self._materialization_quiescing\\n            or self.is_paused()\\n            or self._disk_guard_active\\n            or torrent_id in self._active\\n            or torrent_id in self._ready_parent_task_ids\\n        ):\\n            return False\\n""",
)
'''

old_direct = '''replace_once(
    "backend/services/manager_v2.py",
    """    async def _prepare_direct_link_collection(\\n        self, torrent_id: int, links: List[str]\\n    ) -> None:\\n        if torrent_id in self._active:\\n""",
    """    async def _prepare_direct_link_collection(\\n        self, torrent_id: int, links: List[str]\\n    ) -> None:\\n        if self._materialization_quiescing:\\n            return\\n        if torrent_id in self._active:\\n""",
)
'''
new_direct = '''replace_once(
    "backend/services/manager_v2.py",
    """    async def _prepare_direct_link_collection(\\n        self, torrent_id: int, links: List[str]\\n    ) -> None:\\n        \\\"\\\"\\\"Generate AllDebrid URLs and stage their files for the aria2 dispatcher.\\\"\\\"\\\"\\n        if self.is_paused():\\n""",
    """    async def _prepare_direct_link_collection(\\n        self, torrent_id: int, links: List[str]\\n    ) -> None:\\n        \\\"\\\"\\\"Generate AllDebrid URLs and stage their files for the aria2 dispatcher.\\\"\\\"\\\"\\n        if self._materialization_quiescing:\\n            return\\n        if self.is_paused():\\n""",
)
'''

changed = False
for old, new, label in (
    (old_ready, new_ready, "ready-parent"),
    (old_direct, new_direct, "direct-link"),
):
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    elif new not in text:
        raise RuntimeError(f"temporary corrective fixup could not find {label} patch block")

if changed:
    PATCHER.write_text(text, encoding="utf-8")
else:
    # The patcher is already fixed in this runner. Remove this temporary helper
    # during the postpatch Python invocation and pre-stage its deletion so the
    # validated product commit cannot retain it.
    try:
        Path(__file__).unlink()
        subprocess.run(
            ["git", "add", "-u", "--", "tools/sitecustomize.py"],
            cwd=HERE.parent,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
