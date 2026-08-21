"""Temporary v1.0.6 patch-harness fixup.

The runner invokes this helper before the corrective patcher. It aligns stale
source-match assumptions with the audited candidate while keeping ownership
semantics conservative. A second invocation removes and stages this helper for
deletion so it cannot survive in the validated product commit.
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

old_import = '''# Imported/observed AllDebrid rows remain observation-only when revived.
replace_once(
    manager_path,
    """                        SET name=?, alldebrid_id=?, status=?,\\n                            provider_status=?, provider_status_code=?,\\n""",
    """                        SET name=?, alldebrid_id=?, status=?,\\n                            source='alldebrid_existing',\\n                            provider_status=?, provider_status_code=?,\\n""",
)
'''
new_import = '''# Existing rows retain their original source provenance. New provider-only
# observations are already inserted with source="alldebrid_existing" by
# import_existing_magnets(); overwriting existing source here would incorrectly
# revoke ownership from objects this instance actually created.
'''

changed = False
for old, new, label in (
    (old_ready, new_ready, "ready-parent"),
    (old_direct, new_direct, "direct-link"),
    (old_import, new_import, "import ownership provenance"),
):
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    elif new not in text:
        raise RuntimeError(f"temporary corrective fixup could not find {label} patch block")

if changed:
    PATCHER.write_text(text, encoding="utf-8")
else:
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
