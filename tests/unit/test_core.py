"""Unit coverage for the core utilities required by plan Sections 2.2, 12, and 13."""

from __future__ import annotations

import gzip
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather_basis.config import config_hash, load_config
from weather_basis.http import fetch
from weather_basis.io import (
    atomic_write_bytes,
    gzip_bytes,
    load_npy,
    sha256,
    write_npy,
    write_parquet,
)
from weather_basis.manifest import Manifest, read_manifest, write_manifest


def test_config_is_immutable_and_hashes_canonical_yaml(tmp_path: Path) -> None:
    """Plan Sections 2.2 and 12.3: config is frozen and override order is immaterial."""

    config = tmp_path / "defaults.yaml"
    config.write_text("seed: 1\nhedge: {min_train: 15, first_test: 1981}\n", encoding="utf-8")
    first = load_config(config, {"hedge": {"min_train": 10}})
    second = load_config(config, {"hedge": {"min_train": 10}})
    assert first.hedge.min_train == 10
    assert first.hedge.first_test == 1981
    assert config_hash(first) == config_hash(second)
    with pytest.raises(TypeError):
        first.values["seed"] = 2  # type: ignore[index]


def test_io_helpers_are_atomic_and_deterministic(tmp_path: Path) -> None:
    """Plan Sections 2.2 and 12.3: binary, NPY, Parquet, and gzip outputs are stable."""

    payload_path = tmp_path / "nested" / "payload.bin"
    atomic_write_bytes(payload_path, b"atlas")
    assert payload_path.read_bytes() == b"atlas"
    assert sha256(payload_path) == (
        "7c82602500857aa6ed0cf38c4c3e4ec645bdcaa82c00b9155eb08be100c778a9"
    )

    array_path = tmp_path / "panel.npy"
    write_npy(np.array([[1, 2], [3, 4]], dtype=np.float32), array_path)
    assert np.array_equal(load_npy(array_path), np.array([[1, 2], [3, 4]], dtype=np.float32))

    first, second = tmp_path / "first.parquet", tmp_path / "second.parquet"
    frame = pd.DataFrame({"fips": ["01003", "01001"], "value": [2.0, 1.0]})
    write_parquet(frame, first)
    write_parquet(frame.iloc[::-1], second)
    assert first.read_bytes() == second.read_bytes()

    compressed = gzip_bytes(b"same bytes")
    assert compressed == gzip_bytes(b"same bytes")
    assert gzip.decompress(compressed) == b"same bytes"


def test_manifest_round_trip(tmp_path: Path) -> None:
    """Plan Section 13.3: manifests retain all required provenance fields."""

    manifest = Manifest(
        run_id="test-run",
        stage="unit",
        created_utc="2026-09-02T00:00:00Z",
        git_commit="abc",
        config_hash="1234",
        vintages={"county": "v1"},
        geography_vintage="geo-v1",
        seed=7,
        paths_in=["input"],
        paths_out=[str(tmp_path / "manifest.json")],
        sha256_out={"result": "deadbeef"},
        holdout_unlocked=False,
        prereg_sha256=None,
        extra={"worker": "unit"},
    )
    target = tmp_path / "manifest.json"
    write_manifest(manifest, target, started_at=datetime.now(UTC), allow_dirty=True)
    loaded = read_manifest(target)
    assert loaded.run_id == manifest.run_id
    assert loaded.config_hash == manifest.config_hash
    assert loaded.sha256_out == manifest.sha256_out


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"weather"
        self.send_response(200)
        self.send_header("ETag", '"fixture"')
        self.send_header("Last-Modified", "Tue, 02 Sep 2026 00:00:00 GMT")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_fetch_enforces_allowlist_and_uses_cache(tmp_path: Path) -> None:
    """Plan Sections 2.2 and 13.7: fetch rejects CME and preserves response provenance."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/fixture"
        dest = tmp_path / "fixture.bin"
        result = fetch(url, dest, allow_hosts=frozenset({"127.0.0.1"}), timeout=5)
        assert result.cached is False
        assert result.etag == '"fixture"'
        assert dest.read_bytes() == b"weather"
        cached = fetch(url, dest, allow_hosts=frozenset({"127.0.0.1"}), timeout=5)
        assert cached.cached is True
        assert cached.sha256 == result.sha256
        with pytest.raises(ValueError):
            fetch(
                "https://www.cmegroup.com/forbidden",
                dest,
                allow_hosts=frozenset({"www.cmegroup.com"}),
            )
    finally:
        server.shutdown()
        server.server_close()
