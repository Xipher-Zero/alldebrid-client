from __future__ import annotations

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (root / rel).write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str, label: str) -> None:
    text = read(rel)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    write(rel, text.replace(old, new, 1))


def replace_regex(rel: str, pattern: str, replacement: str, label: str) -> None:
    text = read(rel)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    write(rel, updated)


# ---------------------------------------------------------------------------
# Secret-update compatibility: HTTP uses SettingsUpdate, but older direct
# internal/tests may still pass AppSettings. Missing clear_secrets means no
# explicit clears, never an AttributeError and never implicit secret deletion.
# ---------------------------------------------------------------------------
replace_once(
    "backend/api/routes.py",
    '    requested_clears = {str(field) for field in new.clear_secrets}\n',
    '    requested_clears = {str(field) for field in getattr(new, "clear_secrets", [])}\n',
    "settings clear-secrets compatibility",
)


# ---------------------------------------------------------------------------
# Provider deletion requires positive local ownership. Keep the established DB
# cursor contract and notification behavior while adding source provenance.
# ---------------------------------------------------------------------------
replace_regex(
    "backend/services/manager_v2.py",
    r"    async def cleanup_no_peer_errors\(self\):\n.*?\n    async def cleanup_alldebrid_orphans",
    '''    async def cleanup_no_peer_errors(self):
        """Clean confirmed fatal provider errors only for locally owned objects."""
        async with get_db() as db:
            rows = await (await db.execute(
                """SELECT id, name, alldebrid_id, source, error_message, provider_status_code
                   FROM torrents
                   WHERE status = 'error'
                     AND provider_status = 'error'
                     AND (
                       provider_status_code = 8
                       OR provider_status_code = 7
                       OR LOWER(COALESCE(error_message, '')) LIKE '%no peer%'
                       OR LOWER(COALESCE(error_message, '')) LIKE '%more than 3 day%'
                       OR LOWER(COALESCE(error_message, '')) LIKE '%took more than%'
                       OR LOWER(COALESCE(error_message, '')) LIKE '%timeout%'
                       OR LOWER(COALESCE(error_message, '')) LIKE '%timed out%'
                     )"""
            )).fetchall()

        if not rows:
            return

        logger.info("cleanup_no_peer_errors: found %d torrent(s) to clean up", len(rows))

        for row in rows:
            ad_id = str(row.get("alldebrid_id") or "").strip()
            name = row.get("name") or f"torrent {row['id']}"
            owned = self._provider_delete_authorized(row.get("source"))
            removed_from_provider = False

            if ad_id and ad_id.lower() not in ("none", "null", "") and owned:
                try:
                    logger.info(
                        "no-peer cleanup: removing owned AllDebrid object for %s (%s)",
                        row["id"],
                        name,
                    )
                    removed_from_provider = bool(await self.ad().delete_magnet(ad_id))
                except Exception as exc:
                    logger.warning(
                        "no-peer cleanup: could not delete owned magnet %s: %s",
                        ad_id,
                        sanitize_exception(exc),
                    )
                event_msg = (
                    "Provider download failed — owned failed object removed from AllDebrid; local history retained"
                    if removed_from_provider
                    else "Provider download failed — owned AllDebrid cleanup failed; local history retained"
                )
            elif ad_id and ad_id.lower() not in ("none", "null", ""):
                logger.info(
                    "no-peer cleanup: preserving unowned AllDebrid object %s for torrent %s",
                    ad_id,
                    row["id"],
                )
                event_msg = (
                    "Provider download failed — AllDebrid object preserved because this instance does not own it"
                )
            else:
                logger.info(
                    "no-peer cleanup: torrent %s (%s) has no AllDebrid ID — retaining failed local record",
                    row["id"],
                    name,
                )
                event_msg = "Provider download failed — no AllDebrid ID remains; local history retained"

            async with get_db() as db:
                await db.execute(
                    """UPDATE torrents
                       SET status='error', provider_status='failed',
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (row["id"],),
                )
                await db.execute(
                    "INSERT INTO events (torrent_id, level, message) VALUES (?, 'warn', ?)",
                    (row["id"], event_msg),
                )
                await db.commit()

            await self._notify_provider_error(
                name,
                reason=str(row.get("error_message") or "Provider download failed"),
                context=(
                    f"Failed owned AllDebrid ID {ad_id} removed; DebridPulse history retained"
                    if removed_from_provider
                    else (
                        f"AllDebrid ID {ad_id} preserved; DebridPulse history retained"
                        if ad_id and ad_id.lower() not in ("none", "null", "")
                        else "No AllDebrid ID available; DebridPulse history retained"
                    )
                ),
                alldebrid_id=str(ad_id or ""),
                status_code=row.get("provider_status_code"),
            )

    async def cleanup_alldebrid_orphans''',
    "ownership-aware no-peer cleanup",
)


# Completion cleanup receives provenance from the caller. It never manufactures
# deletion authority from provider presence or performs a second brittle DB
# lookup after the caller has already loaded the transfer row.
replace_regex(
    "backend/services/manager_v2.py",
    r"    async def _delete_magnet_after_completion\(self, torrent_id: int, ad_id: str\) -> bool:\n.*?\n    async def _mark_finished",
    '''    async def _delete_magnet_after_completion(
        self, torrent_id: int, ad_id: str, source: object = None
    ) -> bool:
        """Delete a completed provider object only with positive local ownership."""
        ad_id = str(ad_id or "").strip()
        if not self._provider_delete_authorized(source):
            await self._log_event(
                torrent_id,
                "info",
                "Completed locally; observed AllDebrid object preserved (not owned by this instance)",
            )
            return False
        if not ad_id or ad_id.lower() in ("none", "null"):
            logger.warning(
                "torrent %s: skipping AllDebrid deletion — no alldebrid_id", torrent_id
            )
            await self._log_event(
                torrent_id,
                "warn",
                "Completed locally, but no AllDebrid ID — cannot remove from AllDebrid",
            )
            return False

        logger.info("torrent %s: removing owned AllDebrid object (id=%s)", torrent_id, ad_id)
        deleted = bool(await self.ad().delete_magnet(ad_id))
        msg = (
            "Removed owned object from AllDebrid after completion"
            if deleted
            else f"Completed, but AllDebrid removal failed (id={ad_id})"
        )
        await self._log_event(torrent_id, "info" if deleted else "warn", msg)
        return deleted

    async def _mark_finished''',
    "completion ownership provenance",
)

# The normal materialization path can read source alongside its state update and
# pass that proof to completion cleanup.
replace_once(
    "backend/services/manager_v2.py",
    '''        async with get_db() as db:
            await db.execute(
                "UPDATE torrents SET status=?, local_path=?, size_bytes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (final_status, str(destination_root), total_size_bytes, torrent_id),
            )
''',
    '''        async with get_db() as db:
            source_row = await db.fetchone(
                "SELECT source FROM torrents WHERE id=?", (torrent_id,)
            )
            transfer_source = source_row.get("source") if source_row else None
            await db.execute(
                "UPDATE torrents SET status=?, local_path=?, size_bytes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (final_status, str(destination_root), total_size_bytes, torrent_id),
            )
''',
    "materialization source lookup",
)
replace_once(
    "backend/services/manager_v2.py",
    '            await self._delete_magnet_after_completion(torrent_id, ad_id)\n',
    '            await self._delete_magnet_after_completion(torrent_id, ad_id, transfer_source)\n',
    "materialization completion provenance",
)
replace_once(
    "backend/services/manager_v2.py",
    '''            await self._delete_magnet_after_completion(
                torrent_id, torrent_dict["alldebrid_id"]
            )
''',
    '''            await self._delete_magnet_after_completion(
                torrent_id,
                torrent_dict["alldebrid_id"],
                torrent_dict.get("source"),
            )
''',
    "aria2 finalizer completion provenance",
)

# The terminal no-peer path was another automatic provider mutation. It must
# apply the same ownership rule and must not log that it removed an object when
# provenance says observation-only.
replace_once(
    "backend/services/manager_v2.py",
    '''                    await self._log_event(row["id"], "warn",
                        f"No peers after 30 minutes (code {status_code}) — no magnet stored, removing from AllDebrid")
                    try:
                        await self.ad().delete_magnet(str(row["alldebrid_id"]))
                    except Exception as exc:
                        logger.debug("Could not delete no-peer magnet %s: %s", row["alldebrid_id"], exc)
                    await self._fail_torrent(row["id"], "No peers after 30 minutes — no magnet stored for re-upload", notify=False)
''',
    '''                    if self._provider_delete_authorized(row.get("source")):
                        await self._log_event(
                            row["id"],
                            "warn",
                            f"No peers after 30 minutes (code {status_code}) — no magnet stored; removing owned AllDebrid object",
                        )
                        try:
                            await self.ad().delete_magnet(str(row["alldebrid_id"]))
                        except Exception as exc:
                            logger.debug(
                                "Could not delete owned no-peer magnet %s: %s",
                                row["alldebrid_id"],
                                sanitize_exception(exc),
                            )
                    else:
                        await self._log_event(
                            row["id"],
                            "warn",
                            f"No peers after 30 minutes (code {status_code}) — observed AllDebrid object preserved",
                        )
                    await self._fail_torrent(row["id"], "No peers after 30 minutes — no magnet stored for re-upload", notify=False)
''',
    "terminal no-peer ownership guard",
)


# ---------------------------------------------------------------------------
# Existing regressions need explicit ownership provenance now that deletion is
# fail-closed instead of inferred from mere provider presence.
# ---------------------------------------------------------------------------
manager_tests = "backend/tests/test_manager_v2.py"
replace_once(
    manager_tests,
    '''            "alldebrid_id": "ad-67",
            "error_message": "No peers after 30 minutes",
''',
    '''            "alldebrid_id": "ad-67",
            "source": "manual",
            "error_message": "No peers after 30 minutes",
''',
    "provider failure test ownership fixture",
)
replace_once(
    manager_tests,
    '            await mgr._delete_magnet_after_completion(1, "ad-123")\n',
    '            await mgr._delete_magnet_after_completion(1, "ad-123", "manual")\n',
    "completion test ownership fixture",
)
replace_once(
    manager_tests,
    '            await mgr._delete_magnet_after_completion(42, "ad-42")\n',
    '            await mgr._delete_magnet_after_completion(42, "ad-42", "manual")\n',
    "dashboard completion ownership fixture",
)


# ---------------------------------------------------------------------------
# Corrective regression harness: avoid duplicate kwargs and assert the actual
# ownership invariant rather than rejecting a legitimate local-status check.
# ---------------------------------------------------------------------------
path = root / "backend/tests/test_v106_corrective_regressions.py"
text = path.read_text(encoding="utf-8")
old = '''    preserve = SettingsUpdate(**previous.model_dump(), alldebrid_api_key="", auth_password="")
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    replace = SettingsUpdate(**previous.model_dump(), auth_username="new-user", auth_password="new-pass")
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    clear = SettingsUpdate(**previous.model_dump(), auth_password="", clear_secrets=["auth_password"])
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    with pytest.raises(Exception):
        bad = SettingsUpdate(**previous.model_dump(), clear_secrets=["not_a_secret"])
        _merge_secret_settings(bad, previous)
'''
new = '''    payload = previous.model_dump()
    payload.update(alldebrid_api_key="", auth_password="")
    preserve = SettingsUpdate(**payload)
    merged = _merge_secret_settings(preserve, previous)
    assert merged["alldebrid_api_key"] == "old-key"
    assert merged["auth_password"] == "old-pass"

    payload = previous.model_dump()
    payload.update(auth_username="new-user", auth_password="new-pass")
    replace = SettingsUpdate(**payload)
    merged = _merge_secret_settings(replace, previous)
    assert merged["auth_username"] == "new-user"
    assert merged["auth_password"] == "new-pass"

    payload = previous.model_dump()
    payload.update(auth_password="", clear_secrets=["auth_password"])
    clear = SettingsUpdate(**payload)
    merged = _merge_secret_settings(clear, previous)
    assert merged["auth_password"] == ""

    payload = previous.model_dump()
    payload.update(clear_secrets=["not_a_secret"])
    with pytest.raises(Exception):
        _merge_secret_settings(SettingsUpdate(**payload), previous)
'''
if old not in text:
    raise RuntimeError("corrective settings regression block not found")
text = text.replace(old, new, 1)

old_assert = '    assert "status\\") or \\\"\\\") != \\\"error\\\"" not in block  # source-level sanity only\n'
if old_assert not in text:
    raise RuntimeError("orphan ownership regression assertion not found")
text = text.replace(
    old_assert,
    '''    assert "local is None" in block
    assert "not self._provider_delete_authorized" in block
    assert block.index("local is None") < block.index("delete_magnet(ad_id)")
''',
    1,
)
path.write_text(text, encoding="utf-8")

print("corrective regression and ownership compatibility fixes applied")
