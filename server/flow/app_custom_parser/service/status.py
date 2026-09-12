"""Atomic read/write helpers for the KL file-based job status contract."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


STATUS_FILE_NAME = "genaikl.status"
VALID_STATUSES = frozenset({"PARSING", "DONE", "ERROR"})


def status_path(work_dir: str | os.PathLike[str]) -> Path:
    return Path(work_dir) / STATUS_FILE_NAME


def write_parse_status(
    work_dir: str | os.PathLike[str], status: str, message: str = ""
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported parse status: {status}")

    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "message": str(message)}

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{STATUS_FILE_NAME}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, status_path(directory))
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def read_parse_status(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    path = status_path(work_dir)
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    status = payload.get("status")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid parse status in {path}: {status!r}")
    return {"status": status, "message": str(payload.get("message", ""))}

