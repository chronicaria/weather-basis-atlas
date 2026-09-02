"""Deterministic, atomic file helpers used by pipeline stages."""

from __future__ import annotations

import gzip
import io
import os
import tempfile
from hashlib import sha256 as _sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def sha256(path: Path) -> str:
    """Calculate a file SHA-256 without loading the whole file in memory."""

    digest = _sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically replace *path*, creating its parent directory when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_parquet(df: pd.DataFrame, path: Path, *, compression: str = "zstd") -> None:
    """Write a stable Parquet table: deterministic row ordering and no user metadata."""

    ordered = df.copy()
    if len(ordered.columns) and len(ordered) > 1:
        ordered = ordered.sort_values(list(ordered.columns), kind="mergesort", na_position="last")
    table = pa.Table.from_pandas(ordered, preserve_index=False).replace_schema_metadata()
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression=compression, use_dictionary=False)
    atomic_write_bytes(path, buffer.getvalue())


def write_npy(arr: np.ndarray, path: Path) -> None:
    """Atomically write a NumPy array in standard ``.npy`` format."""

    buffer = io.BytesIO()
    np.save(buffer, arr, allow_pickle=False)
    atomic_write_bytes(path, buffer.getvalue())


def load_npy(path: Path, mmap: bool = True) -> np.ndarray:
    """Load an array, memory mapping by default for panel-sized data."""

    return np.load(path, mmap_mode="r" if mmap else None, allow_pickle=False)


def gzip_bytes(data: bytes) -> bytes:
    """Create byte-stable maximum-compression gzip data."""

    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as stream:
        stream.write(data)
    return buffer.getvalue()
