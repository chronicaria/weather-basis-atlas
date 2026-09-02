"""Restricted, retrying HTTP fetches with reproducibility metadata."""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256 as sha256_digest
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class FetchResult:
    path: Path
    url: str
    size: int
    sha256: str
    etag: str | None
    last_modified: str | None
    retrieved_at_utc: str
    cached: bool


def _sha256(path: Path) -> str:
    digest = sha256_digest()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Keep HTTP self-contained per the import boundary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _validate_url(url: str, allow_hosts: frozenset[str]) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    permitted = {item.lower() for item in allow_hosts}
    if parts.scheme not in {"http", "https"} or not host or host == "cmegroup.com" or host.endswith(
        ".cmegroup.com"
    ):
        raise ValueError(f"disallowed fetch URL: {url}")
    if host not in permitted:
        raise ValueError(f"host is not in fetch allowlist: {host}")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_hosts: frozenset[str]) -> None:
        super().__init__()
        self.allow_hosts = allow_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_url(newurl, self.allow_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _metadata_path(dest: Path) -> Path:
    return dest.with_name(f"{dest.name}.http.json")


def _optional_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _cached_result(url: str, dest: Path) -> FetchResult:
    metadata_path = _metadata_path(dest)
    metadata: dict[str, object] = {}
    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8") as stream:
            metadata = json.load(stream)
    return FetchResult(
        path=dest,
        url=url,
        size=dest.stat().st_size,
        sha256=_sha256(dest),
        etag=metadata.get("etag") if isinstance(metadata.get("etag"), str) else None,
        last_modified=_optional_string(metadata, "last_modified"),
        retrieved_at_utc=(
            metadata.get("retrieved_at_utc")
            if isinstance(metadata.get("retrieved_at_utc"), str)
            else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ),
        cached=True,
    )


def fetch(
    url: str,
    dest: Path,
    *,
    allow_hosts: frozenset[str],
    refresh: bool = False,
    timeout: int = 120,
) -> FetchResult:
    """Fetch an allowlisted URL atomically, or return the immutable local cache.

    A small sibling ``.http.json`` records response validators.  It lets later
    pipeline stages retain upstream ETag and Last-Modified provenance without
    making a network request for an already frozen raw file.
    """

    _validate_url(url, allow_hosts)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if dest.exists() and not refresh:
        return _cached_result(url, dest)

    opener = urllib.request.build_opener(_CheckedRedirect(allow_hosts))
    request = urllib.request.Request(url, headers={"User-Agent": "weather-basis-atlas/0.1"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with opener.open(request, timeout=timeout) as response:
                final_url = response.geturl()
                _validate_url(final_url, allow_hosts)
                data = response.read()
                retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                result = FetchResult(
                    path=dest,
                    url=url,
                    size=len(data),
                    sha256=sha256_digest(data).hexdigest(),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    retrieved_at_utc=retrieved_at,
                    cached=False,
                )
                _atomic_write_bytes(dest, data)
                metadata = asdict(result)
                metadata["path"] = str(dest)
                _atomic_write_bytes(
                    _metadata_path(dest),
                    (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                )
                return result
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code != 429:
                raise
        except urllib.error.URLError as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"failed to fetch {url} after 4 attempts") from last_error
