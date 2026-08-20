"""Browser-facing serializers for persistence and aria2 records.

Persistence rows intentionally retain provider/materialization capabilities such
as magnets and unlocked URLs. Ordinary API responses must not expose those
capabilities merely because a database row contains them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from services.aria2 import Aria2DownloadStatus, aria2_download_to_dict

_TORRENT_PRIVATE_FIELDS = frozenset({"magnet", "download_url"})
_FILE_PRIVATE_FIELDS = frozenset({"source_url", "download_url"})
_CAPABILITY_FIELDS = _TORRENT_PRIVATE_FIELDS | _FILE_PRIVATE_FIELDS


def _without_fields(value: Mapping[str, Any], private_fields: frozenset[str]) -> dict[str, Any]:
    return {key: item for key, item in dict(value).items() if key not in private_fields}


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
            key: public_payload(item)
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
