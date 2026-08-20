from pathlib import Path


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = Path(path)
    text = target.read_text()
    found = text.count(old)
    if found != count:
        raise RuntimeError(
            f"expected {count} exact match(es) in {path}, found {found}: {old[:160]!r}"
        )
    target.write_text(text.replace(old, new))


# Complete the service -> event-bus boundary for legacy materialization events.
replace(
    "backend/services/manager_v2.py",
    "from services.extractor import archive_paths_from_downloads, get_extractor\nfrom services.notifications import NotificationService\n",
    "from services.extractor import archive_paths_from_downloads, get_extractor\nfrom services.event_bus import publish\nfrom services.notifications import NotificationService\n",
)
replace(
    "backend/services/manager_v2.py",
    '''    async def _broadcast_direct_link_update(\n        self,\n        torrent_id: int,\n        status: str,\n        name: str,\n        progress: float,\n    ) -> None:\n        try:\n            from api.routes import _sse_broadcast\n            await _sse_broadcast(\n                "torrent_updated",\n                {\n                    "id": torrent_id,\n                    "status": status,\n                    "name": name,\n                    "progress": progress,\n                    "source": DIRECT_LINK_SOURCE,\n                },\n            )\n        except Exception as exc:\n            logger.debug(\n                "Direct-link SSE broadcast failed for transfer %s: %s",\n                torrent_id,\n                exc,\n            )\n''',
    '''    async def _broadcast_direct_link_update(\n        self,\n        torrent_id: int,\n        status: str,\n        name: str,\n        progress: float,\n    ) -> None:\n        try:\n            await publish(\n                "torrent_updated",\n                {\n                    "id": torrent_id,\n                    "status": status,\n                    "name": name,\n                    "progress": progress,\n                    "source": DIRECT_LINK_SOURCE,\n                },\n            )\n        except Exception as exc:\n            logger.debug(\n                "Direct-link event publication failed for transfer %s: %s",\n                torrent_id,\n                exc,\n            )\n''',
)

# RAR must have the same preflight guarantee as 7z. Fail closed rather than
# invoking an extractor that cannot be safely inspected first.
replace(
    "backend/services/extractor.py",
    '''    for binary in ("7z", "7za", "7zz"):\n        if _tool_available(binary):\n            _preflight_7z(archive, binary, candidates)\n            for pw in candidates:\n                cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n                if pw:\n                    cmd.insert(-1, f"-p{pw}")\n                rc, _out = _run_tool(cmd)\n                if rc == 0:\n                    return\n            break\n\n    if _tool_available("unrar"):\n        for pw in candidates:\n            cmd = ["unrar", "x", "-y", str(archive), str(dest) + "/"]\n            if pw:\n                cmd.insert(2, f"-p{pw}")\n            rc, _out = _run_tool(cmd)\n            if rc == 0:\n                return\n\n    if _tool_available("unrar-free"):\n        rc, _out = _run_tool(["unrar-free", "-x", str(archive), str(dest) + "/"])\n        if rc == 0:\n            return\n\n    raise RuntimeError("No RAR extraction tool available (p7zip-full or unrar-free required)")\n''',
    '''    for binary in ("7z", "7za", "7zz"):\n        if not _tool_available(binary):\n            continue\n        _preflight_7z(archive, binary, candidates)\n        for pw in candidates:\n            cmd = [binary, "x", "-mmt=1", str(archive), f"-o{dest}", "-y"]\n            if pw:\n                cmd.insert(-1, f"-p{pw}")\n            rc, _out = _run_tool(cmd)\n            if rc == 0:\n                return\n        raise RuntimeError(f"{binary} failed to extract {archive.name}")\n\n    raise RuntimeError("Safe RAR extraction requires a 7z-compatible binary")\n''',
)

replace(
    "Dockerfile",
    "    gosu \\\n    p7zip-full \\\n    unrar-free && rm -rf /var/lib/apt/lists/*\n",
    "    gosu \\\n    p7zip-full && rm -rf /var/lib/apt/lists/*\n",
)

# Preserve the old performance contract at its new persistence boundary.
replace(
    "backend/tests/test_ui_responsiveness.py",
    '''    aggregate = (REPO_ROOT / "backend/services/transfer_state_machine.py").read_text()\n\n    assert "if progress != current_progress or status != current_status:" in aggregate\n    assert "if int(progress) != int(current_progress) or status != current_status:" in aggregate\n    assert "await db.executemany(" in aggregate\n    assert "updates.append((progress, status, transfer_id))" in aggregate\n''',
    '''    aggregate = (REPO_ROOT / "backend/services/transfer_state_machine.py").read_text()\n    repository = (REPO_ROOT / "backend/services/transfer_repository.py").read_text()\n\n    assert "if progress != current_progress or status != current_status:" in aggregate\n    assert "if int(progress) != int(current_progress) or status != current_status:" in aggregate\n    assert "updates.append((progress, status, transfer_id))" in aggregate\n    assert "self.repository.persist_parent_progress(updates)" in aggregate\n    assert "await db.executemany(" in repository\n''',
)

# Extend the final architecture/security contracts.
test_path = Path("backend/tests/test_v106_audit_contracts.py")
tests = test_path.read_text()
append = '''\n\ndef test_materialization_engine_publishes_without_importing_http_layer():\n    source = (Path(__file__).resolve().parents[1] / "services" / "manager_v2.py").read_text()\n    assert "from api.routes" not in source\n    assert "from services.event_bus import publish" in source\n    direct = source.split("async def _broadcast_direct_link_update", 1)[1].split("@staticmethod", 1)[0]\n    assert 'await publish(' in direct\n\n\ndef test_rar_extraction_fails_closed_without_preflight_capable_7z():\n    source = (Path(__file__).resolve().parents[1] / "services" / "extractor.py").read_text()\n    rar = source.split("def _extract_rar_to", 1)[1].split("def _extract_rar(", 1)[0]\n    assert "_preflight_7z" in rar\n    assert '"unrar"' not in rar\n    assert '"unrar-free"' not in rar\n    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()\n    assert "p7zip-full" in dockerfile\n    assert "unrar-free" not in dockerfile\n'''
if "test_materialization_engine_publishes_without_importing_http_layer" in tests:
    raise RuntimeError("final audit tests already present")
test_path.write_text(tests.rstrip() + append.rstrip() + "\n")

print("final v1.0.6 audit corrections applied")
