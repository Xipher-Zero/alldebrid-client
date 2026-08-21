"""Browser-facing serializers for persistence and aria2 records.

Persistence rows intentionally retain provider/materialization capabilities such
as magnets and unlocked URLs. Ordinary API responses must not expose those
capabilities merely because a database row contains them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any

from services.aria2 import Aria2DownloadStatus, aria2_download_to_dict

_TORRENT_PRIVATE_FIELDS = frozenset({"magnet", "download_url"})
_FILE_PRIVATE_FIELDS = frozenset({"source_url", "download_url"})
_CAPABILITY_FIELDS = _TORRENT_PRIVATE_FIELDS | _FILE_PRIVATE_FIELDS
_NAIVE_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$")


def _public_timestamp(value: Any) -> Any:
    """Serialize SQLite UTC timestamp values with an explicit UTC designator."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        stripped = value.strip()
        if _NAIVE_UTC_RE.fullmatch(stripped):
            return stripped.replace(" ", "T") + "Z"
    return value


def _public_field(key: str, value: Any) -> Any:
    return _public_timestamp(value) if key.endswith("_at") else value


def _without_fields(value: Mapping[str, Any], private_fields: frozenset[str]) -> dict[str, Any]:
    return {
        key: _public_field(key, item)
        for key, item in dict(value).items()
        if key not in private_fields
    }


def public_torrent(value: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a torrent row without provider bearer/capability material."""
    return _without_fields(value, _TORRENT_PRIVATE_FIELDS)


def public_download_file(value: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a download_files row without source/unlocked URLs."""
    return _without_fields(value, _FILE_PRIVATE_FIELDS)


def public_payload(value: Any) -> Any:
    """Recursively remove known capability-bearing persistence fields."""
    if isinstance(value, Mapping):
        return {
            key: _public_field(key, public_payload(item))
            for key, item in value.items()
            if key not in _CAPABILITY_FIELDS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [public_payload(item) for item in value]
    return value


def public_aria2_download(download: Aria2DownloadStatus) -> dict[str, Any]:
    """Serialize aria2 state without the underlying request URIs."""
    payload = aria2_download_to_dict(download)
    payload["files"] = [
        {key: value for key, value in file_info.items() if key != "uris"}
        for file_info in payload.get("files", [])
    ]
    return payload
