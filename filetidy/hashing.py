"""Content hashing - shared by duplicate detection and the {hash} rename token."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1024 * 1024
QUICK_BYTES = 64 * 1024


def file_hash(path: Path, algorithm: str = "blake2b", limit: int | None = None) -> str:
    """Hex digest of a file's bytes, optionally only the first `limit` bytes."""
    digest = hashlib.new(algorithm) if algorithm != "blake2b" else hashlib.blake2b(digest_size=32)
    remaining = limit
    with open(path, "rb") as handle:
        while True:
            size = CHUNK if remaining is None else min(CHUNK, remaining)
            if size <= 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def quick_hash(path: Path, algorithm: str = "blake2b") -> str:
    """Cheap fingerprint of the first 64 KB - used to skip full reads."""
    return file_hash(path, algorithm=algorithm, limit=QUICK_BYTES)
