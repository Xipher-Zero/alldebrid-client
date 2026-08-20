from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def write(path, text):
    (ROOT / path).write_text(text)


def replace_once(path, old, new):
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one literal match, found {count}")
    write(path, text.replace(old, new, 1))


def regex_once(path, pattern, replacement):
    text = read(path)
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, found {count}")
    write(path, new)


# --- manager: durable deferred provider intake ---
replace_once(
    "backend/services/manager_v2.py",
    'DIRECT_LINK_SOURCE = "direct_link"\nMAX_DIRECT_LINKS_PER_BATCH = 100\n',
    'DIRECT_LINK_SOURCE = "direct_link"\nDEFERRED_PROVIDER_STATUS = "deferred"\nDEFERRED_TORRENT_KIND = "torrent_file"\nMAX_DIRECT_LINKS_PER_BATCH = 100\n',
)
replace_once(
    "backend/services/manager_v2.py",
    '        self._upload_sem: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_AD_UPLOADS)\n',
    '        self._upload_sem: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_AD_UPLOADS)\n        self._deferred_submission_lock = asyncio.Lock()\n',
)
replace_once(
    "backend/services/manager_v2.py",
    '    async def add_magnet_direct(self, magnet: str, source: str = "manual") -> dict:\n        if self.is_paused():\n            raise Exception("Processing is paused")\n        hash_value = extract_hash(magnet)\n',
    '    async def add_magnet_direct(self, magnet: str, source: str = "manual") -> dict:\n        hash_value = extract_hash(magnet)\n',
)
replace_once(
    "backend/services/manager_v2.py",
    '        result = await self._add_magnet(magnet, hash_value, source)\n',
    '        result = await self._add_magnet(\n            magnet, hash_value, source, duplicate_check=False\n        )\n',
)

file_block = r'''    async def _persist_deferred_magnet(
        self, magnet: str, hash_value: str, source: str
    ) -> dict:
        """Persist magnet intake without contacting AllDebrid while Pause All is active."""
        name = hash_value[:16]
        async with get_db() as db:
            await db.execute(
                """INSERT INTO torrents
                       (hash, magnet, name, status, source, provider_status,
                        progress, download_client, error_message, alldebrid_id)
                   VALUES (?, ?, ?, 'paused', ?, ?, 0, 'aria2', NULL, NULL)
                   ON CONFLICT(hash) DO UPDATE SET
                       magnet=excluded.magnet,
                       name=excluded.name,
                       source=excluded.source,
                       status='paused',
                       provider_status=excluded.provider_status,
                       provider_status_code=NULL,
                       polling_failures=0,
                       progress=0,
                       error_message=NULL,
                       alldebrid_id=NULL,
                       completed_at=NULL,
                       updated_at=CURRENT_TIMESTAMP""",
                (hash_value, magnet, name, source, DEFERRED_PROVIDER_STATUS),
            )
            row = await db.fetchone("SELECT * FROM torrents WHERE hash=?", (hash_value,))
            if not row:
                raise RuntimeError("Could not persist deferred magnet submission")
            torrent_id = int(row["id"])
            await db.execute("DELETE FROM download_files WHERE torrent_id=?", (torrent_id,))
            await db.execute(
                "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                (
                    torrent_id,
                    "Accepted while Pause All is active; queued for AllDebrid upload on resume",
                ),
            )
            await db.commit()
        result = dict(row)
        result["_deferred"] = True
        return result

    async def _persist_deferred_torrent_file(
        self,
        file_bytes: bytes,
        filename: str,
        source: str,
        local_hash: str,
    ) -> dict:
        """Persist a .torrent payload so paused intake survives restart."""
        if not local_hash:
            raise ValueError(
                "Could not determine torrent infohash; cannot queue this .torrent while processing is paused"
            )
        name = Path(filename or "upload.torrent").stem or local_hash[:16]
        async with get_db() as db:
            await db.execute(
                """INSERT INTO torrents
                       (hash, name, status, source, provider_status, progress,
                        download_client, error_message, alldebrid_id)
                   VALUES (?, ?, 'paused', ?, ?, 0, 'aria2', NULL, NULL)
                   ON CONFLICT(hash) DO UPDATE SET
                       name=excluded.name,
                       source=excluded.source,
                       status='paused',
                       provider_status=excluded.provider_status,
                       provider_status_code=NULL,
                       polling_failures=0,
                       progress=0,
                       error_message=NULL,
                       alldebrid_id=NULL,
                       completed_at=NULL,
                       updated_at=CURRENT_TIMESTAMP""",
                (local_hash, name, source, DEFERRED_PROVIDER_STATUS),
            )
            row = await db.fetchone("SELECT * FROM torrents WHERE hash=?", (local_hash,))
            if not row:
                raise RuntimeError("Could not persist deferred torrent-file submission")
            torrent_id = int(row["id"])
            await db.execute("DELETE FROM download_files WHERE torrent_id=?", (torrent_id,))
            await db.execute(
                """INSERT INTO deferred_provider_submissions
                       (torrent_id, kind, payload, filename, source, created_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(torrent_id) DO UPDATE SET
                       kind=excluded.kind,
                       payload=excluded.payload,
                       filename=excluded.filename,
                       source=excluded.source,
                       created_at=CURRENT_TIMESTAMP""",
                (
                    torrent_id,
                    DEFERRED_TORRENT_KIND,
                    bytes(file_bytes),
                    filename or "upload.torrent",
                    source,
                ),
            )
            await db.execute(
                "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                (
                    torrent_id,
                    "Accepted .torrent while Pause All is active; queued for AllDebrid upload on resume",
                ),
            )
            await db.commit()
        result = dict(row)
        result["_deferred"] = True
        return result

    async def _upload_torrent_file_provider(
        self,
        file_bytes: bytes,
        filename: str,
        source: str,
        local_hash: str,
        *,
        deferred_torrent_id: Optional[int] = None,
    ) -> dict:
        if self.is_paused():
            if deferred_torrent_id is not None:
                async with get_db() as db:
                    row = await db.fetchone(
                        "SELECT * FROM torrents WHERE id=?", (int(deferred_torrent_id),)
                    )
                result = dict(row or {"id": int(deferred_torrent_id)})
                result["_deferred"] = True
                return result
            return await self._persist_deferred_torrent_file(
                file_bytes, filename, source, local_hash
            )

        async with self._upload_sem:
            if self.is_paused():
                if deferred_torrent_id is not None:
                    async with get_db() as db:
                        row = await db.fetchone(
                            "SELECT * FROM torrents WHERE id=?", (int(deferred_torrent_id),)
                        )
                    result = dict(row or {"id": int(deferred_torrent_id)})
                    result["_deferred"] = True
                    return result
                return await self._persist_deferred_torrent_file(
                    file_bytes, filename, source, local_hash
                )
            result = await self.ad().upload_torrent_file(
                file_bytes, filename or "upload.torrent"
            )

        ad_id = str(result.get("id", ""))
        name = (
            result.get("name")
            or result.get("filename")
            or Path(filename or "upload.torrent").stem
        )
        hash_value = str(local_hash or result.get("hash", ad_id) or ad_id).strip().lower()
        logger.info("Torrent file uploaded %s (ad_id=%s)", name, ad_id)

        if deferred_torrent_id is None:
            row = await self._upsert(hash_value, None, name, ad_id, source)
        else:
            async with get_db() as db:
                await db.execute(
                    """UPDATE torrents
                       SET hash=?, name=?, alldebrid_id=?, status='uploading',
                           source=?, provider_status='queued', provider_status_code=NULL,
                           polling_failures=0, progress=0, error_message=NULL,
                           completed_at=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (
                        hash_value,
                        name,
                        ad_id,
                        source,
                        int(deferred_torrent_id),
                    ),
                )
                await db.execute(
                    "DELETE FROM deferred_provider_submissions WHERE torrent_id=?",
                    (int(deferred_torrent_id),),
                )
                await db.execute(
                    "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                    (
                        int(deferred_torrent_id),
                        f"Uploaded deferred .torrent to AllDebrid (id={ad_id})",
                    ),
                )
                await db.commit()
                row = await db.fetchone(
                    "SELECT * FROM torrents WHERE id=?", (int(deferred_torrent_id),)
                )
            row = dict(row or {})

        if get_settings().discord_notify_added:
            await self.notify().send_added(name, source=source, alldebrid_id=ad_id)

        status_code = int(result.get("statusCode") or result.get("status_code") or 0)
        if status_code == READY_CODE:
            logger.info(
                "Fast-path: %s already ready on AllDebrid (cached torrent file) — starting immediately",
                sanitize_log_value(name[:60]),
            )
            torrent_id = row.get("id")
            if torrent_id:
                self._schedule_ready_parent_download(int(torrent_id), ad_id, name)

        return row

    async def add_torrent_file_direct(
        self,
        file_bytes: bytes,
        filename: str,
        source: str = "manual",
        preferred_hash: Optional[str] = None,
    ) -> dict:
        if not get_settings().alldebrid_api_key:
            raise Exception("AllDebrid API key not configured")
        if not file_bytes:
            raise ValueError("Empty torrent file")

        local_hash = preferred_hash or ""
        if not local_hash:
            try:
                from services.alldebrid import extract_hash_from_torrent
                local_hash = extract_hash_from_torrent(file_bytes) or ""
            except Exception as exc:
                logger.debug("Failed to extract hash from torrent file: %s", exc)

        from services.duplicates import DuplicateCandidate, check_before_add
        decision = await check_before_add(DuplicateCandidate(
            source=source,
            infohash=local_hash,
            title=Path(filename or "").stem,
        ))
        if decision.action == "skip":
            existing = decision.matches[0] if decision.matches else None
            result: dict = {}
            if existing:
                try:
                    async with get_db() as db:
                        row = await db.fetchone(
                            "SELECT * FROM torrents WHERE id=?", (existing.torrent_id,)
                        )
                    result = dict(row) if row else {}
                except Exception:
                    pass
            result["_duplicate"] = decision.as_dict()
            return result

        result = await self._upload_torrent_file_provider(
            file_bytes, filename, source, local_hash
        )
        if decision.action == "warn":
            result["_duplicate"] = decision.as_dict()
        return result

    async def add_direct_links'''

regex_once(
    "backend/services/manager_v2.py",
    r"    async def add_torrent_file_direct\(.*?\n    async def add_direct_links",
    file_block,
)

new_direct = r'''    async def add_direct_links(self, links: List[str]) -> dict:
        """Create one tracked transfer collection from ordinary hoster URLs."""
        if not get_settings().alldebrid_api_key:
            raise Exception("AllDebrid API key not configured")

        normalized = normalize_direct_links(links)
        initial_name = (
            direct_link_filename(normalized[0])
            if len(normalized) == 1
            else f"Debrid link batch ({len(normalized)} links)"
        )
        payload = json.dumps(normalized, separators=(",", ":"))
        nonce = uuid.uuid4().hex
        collection_hash = "direct:" + hashlib.sha256(
            f"{nonce}:{payload}".encode("utf-8")
        ).hexdigest()

        async with get_db() as db:
            torrent_id = await db.execute_returning_id(
                """INSERT INTO torrents
                       (hash, name, magnet, status, source, provider_status,
                        progress, download_client, error_message)
                   VALUES (?, ?, ?, 'processing', ?, 'submitted', 0, 'aria2', NULL)""",
                (
                    collection_hash,
                    initial_name,
                    payload,
                    DIRECT_LINK_SOURCE,
                ),
            )
            if not torrent_id:
                raise RuntimeError("Could not create the debrid-link transaction")
            await db.execute(
                "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                (
                    torrent_id,
                    f"Accepted {len(normalized)} direct link(s)",
                ),
            )
            await db.commit()
            row = await db.fetchone("SELECT * FROM torrents WHERE id=?", (torrent_id,))

        if self.is_paused():
            async with get_db() as db:
                await db.execute(
                    """UPDATE torrents
                       SET status='paused', provider_status=?, updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (DEFERRED_PROVIDER_STATUS, int(torrent_id)),
                )
                await db.execute(
                    "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                    (
                        int(torrent_id),
                        "Pause All is active; direct-link generation is queued for resume",
                    ),
                )
                await db.commit()
                row = await db.fetchone("SELECT * FROM torrents WHERE id=?", (torrent_id,))
            await self._broadcast_direct_link_update(
                int(torrent_id), "paused", initial_name, 0.0
            )
            return {
                **dict(row or {}),
                "accepted_links": len(normalized),
                "_deferred": True,
            }

        await self._broadcast_direct_link_update(
            int(torrent_id), "processing", initial_name, 0.0
        )
        self._schedule_direct_link_collection(int(torrent_id), normalized)
        return {**dict(row or {}), "accepted_links": len(normalized)}

    def _schedule_direct_link_collection'''

regex_once(
    "backend/services/manager_v2.py",
    r"    async def add_direct_links\(.*?\n    def _schedule_direct_link_collection",
    new_direct,
)

replace_once(
    "backend/services/manager_v2.py",
    '''    async def _prepare_direct_link_collection(
        self, torrent_id: int, links: List[str]
    ) -> None:
        """Generate AllDebrid URLs and stage their files for the aria2 dispatcher."""
        if torrent_id in self._active:
            return
        self._active.add(torrent_id)
''',
    '''    async def _prepare_direct_link_collection(
        self, torrent_id: int, links: List[str]
    ) -> None:
        """Generate AllDebrid URLs and stage their files for the aria2 dispatcher."""
        if self.is_paused():
            async with get_db() as db:
                current = await db.fetchone(
                    "SELECT status, provider_status, name FROM torrents WHERE id=?",
                    (torrent_id,),
                )
                if current and current["status"] not in {"completed", "deleted", "error"}:
                    was_deferred = str(current.get("provider_status") or "") == DEFERRED_PROVIDER_STATUS
                    await db.execute(
                        """UPDATE torrents
                           SET status='paused', provider_status=?, updated_at=CURRENT_TIMESTAMP
                           WHERE id=?""",
                        (DEFERRED_PROVIDER_STATUS, torrent_id),
                    )
                    if not was_deferred:
                        await db.execute(
                            "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                            (torrent_id, "Pause All deferred direct-link generation until resume"),
                        )
                    await db.commit()
                    await self._broadcast_direct_link_update(
                        torrent_id,
                        "paused",
                        str(current.get("name") or "Debrid links"),
                        0.0,
                    )
            return
        if torrent_id in self._active:
            return
        self._active.add(torrent_id)
''',
)

resume_block = r'''    async def resume_deferred_provider_submissions(self) -> dict:
        """Start provider work that was durably accepted while Pause All was active."""
        if self.is_paused():
            return {"started": 0, "failed": 0}

        async with self._deferred_submission_lock:
            if self.is_paused():
                return {"started": 0, "failed": 0}
            async with get_db() as db:
                rows = await db.fetchall(
                    """SELECT t.*,
                              d.kind AS deferred_kind,
                              d.payload AS deferred_payload,
                              d.filename AS deferred_filename,
                              d.source AS deferred_source
                         FROM torrents t
                         LEFT JOIN deferred_provider_submissions d
                           ON d.torrent_id=t.id
                        WHERE t.provider_status=?
                          AND t.status NOT IN ('paused','completed','deleted','error')
                        ORDER BY t.priority DESC, t.id ASC""",
                    (DEFERRED_PROVIDER_STATUS,),
                )

            started = failed = 0
            for row in rows:
                if self.is_paused():
                    break
                torrent_id = int(row["id"])
                try:
                    async with get_db() as db:
                        current = await db.fetchone(
                            "SELECT status, provider_status FROM torrents WHERE id=?",
                            (torrent_id,),
                        )
                    if (
                        not current
                        or current["status"] == "paused"
                        or str(current.get("provider_status") or "") != DEFERRED_PROVIDER_STATUS
                    ):
                        continue

                    if str(row.get("source") or "") == DIRECT_LINK_SOURCE:
                        links = normalize_direct_links(
                            json.loads(row.get("magnet") or "[]")
                        )
                        async with get_db() as db:
                            await db.execute(
                                """UPDATE torrents
                                   SET status='processing', provider_status='submitted',
                                       error_message=NULL, updated_at=CURRENT_TIMESTAMP
                                   WHERE id=? AND provider_status=? AND status!='paused'""",
                                (torrent_id, DEFERRED_PROVIDER_STATUS),
                            )
                            await db.execute(
                                "INSERT INTO events (torrent_id, level, message) VALUES (?, 'info', ?)",
                                (torrent_id, "Pause All released; starting deferred direct-link generation"),
                            )
                            await db.commit()
                        self._schedule_direct_link_collection(torrent_id, links)
                        started += 1
                        continue

                    if str(row.get("deferred_kind") or "") == DEFERRED_TORRENT_KIND:
                        payload = row.get("deferred_payload")
                        if isinstance(payload, memoryview):
                            payload = payload.tobytes()
                        if not isinstance(payload, (bytes, bytearray)) or not payload:
                            raise ValueError("Deferred .torrent payload is missing")
                        result = await self._upload_torrent_file_provider(
                            bytes(payload),
                            str(row.get("deferred_filename") or "upload.torrent"),
                            str(row.get("deferred_source") or row.get("source") or "manual"),
                            str(row.get("hash") or ""),
                            deferred_torrent_id=torrent_id,
                        )
                        if not result.get("_deferred"):
                            started += 1
                        continue

                    magnet = str(row.get("magnet") or "").strip()
                    if not magnet:
                        raise ValueError("Deferred magnet payload is missing")
                    result = await self._add_magnet(
                        magnet,
                        str(row.get("hash") or ""),
                        str(row.get("source") or "manual"),
                        duplicate_check=False,
                        resume_deferred=True,
                    )
                    if not result.get("_deferred"):
                        started += 1
                except Exception as exc:
                    failed += 1
                    message = sanitize_exception(exc, max_length=300)
                    logger.warning(
                        "Deferred provider submission %s could not start: %s",
                        torrent_id,
                        message,
                    )
                    async with get_db() as db:
                        await db.execute(
                            """UPDATE torrents
                               SET error_message=?, updated_at=CURRENT_TIMESTAMP
                               WHERE id=? AND provider_status=?""",
                            (message, torrent_id, DEFERRED_PROVIDER_STATUS),
                        )
                        await db.execute(
                            "INSERT INTO events (torrent_id, level, message) VALUES (?, 'warn', ?)",
                            (torrent_id, f"Deferred provider submission retry failed: {message}"),
                        )
                        await db.commit()
            return {"started": started, "failed": failed}

    async def _add_magnet(
        self,
        magnet: str,
        hash_value: str,
        source: str,
        *,
        duplicate_check: bool = True,
        resume_deferred: bool = False,
    ) -> dict:
        decision = None
        if duplicate_check:
            from services.duplicates import DuplicateCandidate, check_before_add

            decision = await check_before_add(DuplicateCandidate(
                source=source,
                magnet=magnet,
                infohash=hash_value,
            ))
            if decision.action == "skip":
                existing = decision.matches[0] if decision.matches else None
                result: dict = {}
                if existing:
                    try:
                        async with get_db() as db:
                            row = await db.fetchone(
                                "SELECT * FROM torrents WHERE id=?", (existing.torrent_id,)
                            )
                        result = dict(row) if row else {}
                    except Exception:
                        pass
                result["_duplicate"] = decision.as_dict()
                return result

        async with get_db() as db:
            existing = await db.fetchone("SELECT * FROM torrents WHERE hash=?", (hash_value,))
        deferred_existing = bool(
            existing
            and str(existing.get("provider_status") or "") == DEFERRED_PROVIDER_STATUS
            and not str(existing.get("alldebrid_id") or "").strip()
        )
        if (
            existing
            and existing["status"] in (
                "uploading", "processing", "queued", "downloading", "ready", "completed"
            )
            and not (resume_deferred and deferred_existing)
        ):
            return dict(existing)

        if self.is_paused():
            result = await self._persist_deferred_magnet(magnet, hash_value, source)
            if decision is not None and decision.action == "warn":
                result["_duplicate"] = decision.as_dict()
            return result

        async with self._upload_sem:
            if self.is_paused():
                result = await self._persist_deferred_magnet(magnet, hash_value, source)
                if decision is not None and decision.action == "warn":
                    result["_duplicate"] = decision.as_dict()
                return result
            result = await self.ad().upload_magnet(magnet)
        ad_id = str(result.get("id", ""))
        name = result.get("name") or result.get("filename") or hash_value[:16]
        normalized_hash = result.get("hash", hash_value).lower()
        logger.info("Magnet uploaded %s (ad_id=%s)", sanitize_log_value(name[:80]), ad_id)

        row = await self._upsert(normalized_hash, magnet, name, ad_id, source)
        if decision is not None and decision.action == "warn":
            row["_duplicate"] = decision.as_dict()
        if get_settings().discord_notify_added:
            await self.notify().send_added(name, source=source, alldebrid_id=ad_id)

        status_code = int(result.get("statusCode") or result.get("status_code") or 0)
        if status_code == READY_CODE:
            logger.info(
                "Fast-path: %s already ready on AllDebrid (cached) — starting download immediately",
                sanitize_log_value(name[:60]),
            )
            torrent_id = row.get("id")
            if torrent_id:
                self._schedule_ready_parent_download(int(torrent_id), ad_id, name)

        return row

    async def _upsert'''

regex_once(
    "backend/services/manager_v2.py",
    r"    async def _add_magnet\(.*?\n    async def _upsert",
    resume_block,
)

# --- database schema / maintenance ---
replace_once(
    "backend/db/database.py",
    '''        await db.execute("""
            CREATE TABLE IF NOT EXISTS transfer_pause_intents (
                torrent_id INTEGER PRIMARY KEY,
                paused INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
''',
    '''        await db.execute("""
            CREATE TABLE IF NOT EXISTS transfer_pause_intents (
                torrent_id INTEGER PRIMARY KEY,
                paused INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deferred_provider_submissions (
                torrent_id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                payload BLOB NOT NULL,
                filename TEXT,
                source TEXT DEFAULT 'manual',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (torrent_id) REFERENCES torrents(id)
            )
        """)
''',
)
replace_once(
    "backend/services/db_maintenance.py",
    'import json\n',
    'import base64\nimport json\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    '    "transfer_pause_intents",\n    "debridpulse_aria2_owned_gids",\n',
    '    "transfer_pause_intents",\n    "deferred_provider_submissions",\n    "debridpulse_aria2_owned_gids",\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    '    "transfer_pause_intents": "torrent_id",\n    "debridpulse_aria2_owned_gids": "gid",\n',
    '    "transfer_pause_intents": "torrent_id",\n    "deferred_provider_submissions": "torrent_id",\n    "debridpulse_aria2_owned_gids": "gid",\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    '    if isinstance(value, bytes):\n        return value.decode("utf-8", errors="replace")\n',
    '    if isinstance(value, bytes):\n        return {"__base64__": base64.b64encode(value).decode("ascii")}\n',
)
replace_once(
    "backend/services/db_maintenance.py",
    '        await db.execute("DELETE FROM debridpulse_aria2_owned_gids")\n        await db.execute("DELETE FROM transfer_pause_intents")\n',
    '        await db.execute("DELETE FROM debridpulse_aria2_owned_gids")\n        await db.execute("DELETE FROM transfer_pause_intents")\n        await db.execute("DELETE FROM deferred_provider_submissions")\n',
)

# --- resume / reconciliation authority ---
replace_once(
    "backend/services/transfer_control_service.py",
    '''        if not bool(get_settings().paused):
            return await self.coordinator.resume_torrent(transfer_id)
''',
    '''        if not bool(get_settings().paused):
            result = await self.coordinator.resume_torrent(transfer_id)
            await self.engine.resume_deferred_provider_submissions()
            return result
''',
)
replace_once(
    "backend/services/transfer_control_service.py",
    '''        self.coordinator._schedule_queue()
        return result

    async def pause_all(self):
''',
    '''        await self.engine.resume_deferred_provider_submissions()
        self.coordinator._schedule_queue()
        return result

    async def pause_all(self):
''',
)
replace_once(
    "backend/services/transfer_control_service.py",
    '''    async def resume_all(self):
        result = await self.coordinator.resume_all_downloads()
        self._set_global_paused(False)
        self.coordinator._schedule_queue()
        return result
''',
    '''    async def resume_all(self):
        result = await self.coordinator.resume_all_downloads()
        self._set_global_paused(False)
        await self.engine.resume_deferred_provider_submissions()
        self.coordinator._schedule_queue()
        return result
''',
)
replace_once(
    "backend/services/reconciliation_service.py",
    '''    async def reconcile(self):
        if self.engine.download_client_name() != "aria2":
            return
        await self.control.ensure_initialized()
''',
    '''    async def reconcile(self):
        if self.engine.download_client_name() != "aria2":
            return
        if not bool(get_settings().paused):
            async with async_timer("reconcile.deferred_provider"):
                await self.engine.resume_deferred_provider_submissions()
        await self.control.ensure_initialized()
''',
)

# --- frontend feedback and cache bust ---
app = read("frontend/static/app.js")
app = app.replace("  let handled = 0;\n", "  let handled = 0;\n  let deferred = 0;\n", 1)
app = app.replace(
    "        await api('POST', '/links/add', {links: direct.map(entry => entry.value)}, 30000);\n        handled += direct.length;\n",
    "        const result = await api('POST', '/links/add', {links: direct.map(entry => entry.value)}, 30000);\n        handled += direct.length;\n        if (result && result._deferred) deferred += direct.length;\n",
    1,
)
app = app.replace(
    "        if (result.ok) handled += 1;\n        else failed.push({...magnets[index], error: result.error});\n",
    "        if (result.ok) {\n          handled += 1;\n          if (result.value && result.value._deferred) deferred += 1;\n        } else failed.push({...magnets[index], error: result.error});\n",
    1,
)
app = app.replace(
    "    } else {\n      toast(`${handled} item${handled === 1 ? '' : 's'} submitted`, 'success');\n    }\n",
    "    } else if (handled && deferred === handled) {\n      toast(`${handled} added · processing is paused`, 'success');\n    } else if (deferred) {\n      toast(`${handled} handled · ${deferred} waiting for Resume All`, 'success');\n    } else {\n      toast(`${handled} item${handled === 1 ? '' : 's'} submitted`, 'success');\n    }\n",
    1,
)
app = app.replace(
    "    } else if (res && res._duplicate && res._duplicate.action === 'warn') {\n      toast('Torrent file added (possible duplicate)', 'warn');\n    } else {\n      toast('Torrent file added!', 'success');\n    }\n",
    "    } else if (res && res._duplicate && res._duplicate.action === 'warn') {\n      toast('Torrent file added (possible duplicate)', 'warn');\n    } else if (res && res._deferred) {\n      toast('Torrent file added · processing is paused', 'success');\n    } else {\n      toast('Torrent file added!', 'success');\n    }\n",
    1,
)
if app == read("frontend/static/app.js"):
    raise SystemExit("frontend/static/app.js: no transformations applied")
write("frontend/static/app.js", app)
replace_once(
    "frontend/static/index.html",
    '<script src="/app.js?v=11" defer></script>',
    '<script src="/app.js?v=12" defer></script>',
)

# --- docs ---
replace_once(
    "README.md",
    '| **Torrent files** | Upload `.torrent` files directly to AllDebrid |\n',
    '| **Torrent files** | Upload `.torrent` files directly to AllDebrid |\n| **Pause-safe intake** | Pause All stops processing, not intake: new links, magnets, and `.torrent` files are recorded locally and begin provider work after Resume All |\n',
)
replace_once(
    "README.md",
    'The Dashboard intentionally shows only a small Recent Activity window. Use **Downloads** for full transfer history and management.\n',
    'The Dashboard intentionally shows only a small Recent Activity window. Use **Downloads** for full transfer history and management.\n\n**Pause All stops processing, not intake.** Submissions made while globally paused are durably recorded with a paused state; no new AllDebrid or aria2 work is started until Resume All (or an explicit per-transfer resume) releases them.\n',
)
replace_once(
    "CHANGELOG.md",
    '- Removed the obsolete hidden Runtime Database settings card and synchronized release documentation, compose metadata, API docs paths, and SQLite-only product surfaces.\n',
    '- Removed the obsolete hidden Runtime Database settings card and synchronized release documentation, compose metadata, API docs paths, and SQLite-only product surfaces.\n- Defined Pause All as an execution gate rather than an intake gate: new direct links, magnets, and `.torrent` files are durably accepted while paused and provider work begins only after resume.\n',
)

# --- regression contracts ---
test_path = "backend/tests/test_v106_audit_contracts.py"
tests = read(test_path)
tests = tests.replace(
    "from pathlib import Path\n",
    "from contextlib import asynccontextmanager\nfrom pathlib import Path\n",
    1,
)
tests = tests.replace(
    "from unittest.mock import AsyncMock\n",
    "from unittest.mock import AsyncMock, MagicMock\n",
    1,
)
append = r'''

@pytest.mark.asyncio
async def test_direct_link_intake_is_durable_while_pause_all_is_active(monkeypatch):
    import services.manager_v2 as manager_module

    class FakeDb:
        def __init__(self):
            self.statements = []

        async def execute_returning_id(self, sql, params=()):
            self.statements.append((sql, params))
            return 77

        async def execute(self, sql, params=()):
            self.statements.append((sql, params))

        async def fetchone(self, sql, params=()):
            return {
                "id": 77,
                "name": "sample.zip",
                "status": "paused",
                "source": "direct_link",
                "provider_status": "deferred",
            }

        async def commit(self):
            return None

    fake_db = FakeDb()

    @asynccontextmanager
    async def fake_get_db():
        yield fake_db

    settings = SimpleNamespace(paused=True, alldebrid_api_key="configured")
    manager = manager_module.TorrentManager()
    schedule = MagicMock()
    monkeypatch.setattr(manager_module, "get_settings", lambda: settings)
    monkeypatch.setattr(manager_module, "get_db", fake_get_db)
    monkeypatch.setattr(manager, "_schedule_direct_link_collection", schedule)
    monkeypatch.setattr(manager, "_broadcast_direct_link_update", AsyncMock())

    result = await manager.add_direct_links(["https://host.invalid/sample.zip"])

    assert result["accepted_links"] == 1
    assert result["_deferred"] is True
    assert result["status"] == "paused"
    schedule.assert_not_called()
    assert any("provider_status=?" in sql for sql, _ in fake_db.statements)


def test_pause_all_defers_provider_intake_instead_of_rejecting_it():
    root = Path(__file__).resolve().parents[2]
    manager = (root / "backend/services/manager_v2.py").read_text()
    database = (root / "backend/db/database.py").read_text()
    maintenance = (root / "backend/services/db_maintenance.py").read_text()
    control = (root / "backend/services/transfer_control_service.py").read_text()
    reconciliation = (root / "backend/services/reconciliation_service.py").read_text()
    app = (root / "frontend/static/app.js").read_text()

    assert "DEFERRED_PROVIDER_STATUS = \"deferred\"" in manager
    assert "resume_deferred_provider_submissions" in manager
    assert "deferred_provider_submissions" in database
    assert '"deferred_provider_submissions"' in maintenance
    assert "DELETE FROM deferred_provider_submissions" in maintenance
    assert "await self.engine.resume_deferred_provider_submissions()" in control
    assert 'async_timer("reconcile.deferred_provider")' in reconciliation
    assert "processing is paused" in app
    assert "waiting for Resume All" in app

    magnet_start = manager.index("async def add_magnet_direct")
    magnet_end = manager.index("async def add_torrent_file_direct", magnet_start)
    file_start = magnet_end
    file_end = manager.index("async def add_direct_links", file_start)
    link_start = file_end
    link_end = manager.index("def _schedule_direct_link_collection", link_start)
    for segment in (
        manager[magnet_start:magnet_end],
        manager[file_start:file_end],
        manager[link_start:link_end],
    ):
        assert 'raise Exception("Processing is paused")' not in segment
'''
if "test_direct_link_intake_is_durable_while_pause_all_is_active" in tests:
    raise SystemExit("paused intake tests already present")
tests = tests.rstrip() + append + "\n"
write(test_path, tests)

# Guard the exact intended semantic pieces before the workflow validates them.
manager = read("backend/services/manager_v2.py")
assert "DEFERRED_PROVIDER_STATUS" in manager
assert "resume_deferred_provider_submissions" in manager
assert "deferred_provider_submissions" in read("backend/db/database.py")
assert '<script src="/app.js?v=12" defer></script>' in read("frontend/static/index.html")

# Successful source commit must not retain temporary mutation machinery.
for temporary in (
    ROOT / ".github" / "v106_paused_intake.py",
    ROOT / ".github" / "workflows" / "v106-paused-intake.yml",
    ROOT / "v106-paused-intake-trigger.txt",
):
    temporary.unlink(missing_ok=True)
