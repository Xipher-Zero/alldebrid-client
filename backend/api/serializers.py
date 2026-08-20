"""Browser-facing serializers for persistence and aria2 records.

Persistence rows intentionally retain provider/materialization capabilities such
as magnets and unlocked URLs. Ordinary API responses must not expose those
capabilities merely because a database row contains them.
"""
from __future__ import annotations

from typing import Any, Mapping

from services.aria2 import Aria2DownloadStatus, aria2_download_to_dict

_TORRENT_PRIVATE_FIELDS = frozenset({"magnet", "download_url"})
_FILE_PRIVATE_FIELDS = frozenset({"source_url", "download_url"})


def _without_fields(value: Mapping[str, Any], private_fields: frozenset[str]) -> dict[str, Any]:
    return {key: item for key, item in dict(value).items() if key not in private_fields}


def public_torrent(value: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a torrent row without provider bearer/capability material."""
    return _without_fields(value, _TORRENT_PRIVATE_FIELDS)


def public_download_file(value: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a download_files row without source/unlocked URLs."""
    return _without_fields(value, _FILE_PRIVATE_FIELDS)


def public_aria2_download(download: Aria2DownloadStatus) -> dict[str, Any]:
    """Serialize aria2 state without the underlying request URIs."""
    payload = aria2_download_to_dict(download)
    payload["files"] = [
        {key: value for key, value in file_info.items() if key != "uris"}
        for file_info in payload.get("files", [])
    ]
    return payload
