"""Verify that the delivered offline wheels exactly match SHA256SUMS."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def verify(directory: Path) -> None:
    manifest = directory / "SHA256SUMS"
    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        digest, filename = line.split(maxsplit=1)
        expected[filename.strip()] = digest.lower()
    wheels = {path.name for path in directory.glob("*.whl")}
    if wheels != set(expected):
        raise RuntimeError(
            f"Wheel manifest mismatch: files={sorted(wheels)}, manifest={sorted(expected)}"
        )
    for filename, digest in expected.items():
        actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError(f"SHA-256 mismatch for {filename}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_wheels.py WHEEL_DIRECTORY")
    verify(Path(sys.argv[1]))

