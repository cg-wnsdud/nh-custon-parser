"""Project parsing entrypoint required by the KL Custom Parser contract."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from typing import Any

from .config import EtlConfig
from .etl_adapter import convert_default_json
from .etl_client import EtlClient
from .hrc_exporter import export_hrc
from .result_contract import collect_result_files
ClientFactory = Callable[[EtlConfig], EtlClient]


# Preserve the implementations marked DO NOT EDIT in the supplied example.
def write_parse_status(work_dir: str, work_status: str, msg: str = "") -> None:
    status_file = os.path.join(work_dir, "genaikl.status")
    temp_file = status_file + ".tmp"
    with open(temp_file, "w+", encoding="utf-8") as status_fd:
        status = {"status": work_status, "message": msg}
        json.dump(status, status_fd, ensure_ascii=False)
    shutil.move(temp_file, status_file, copy_function=shutil.copy)


def get_parse_status(work_dir: str) -> tuple[str, str]:
    status_file = os.path.join(work_dir, "genaikl.status")
    if os.path.exists(status_file):
        with open(status_file, "r", encoding="utf-8") as status_fd:
            status = json.load(status_fd)
        return status["status"], status["message"]
    if os.path.exists(work_dir) and os.path.exists(status_file + ".tmp"):
        return "PARSING", ""
    return "UNKNOWN", "Requested url does not exist."


def process_document(
    work_dir: str,
    img_dir: str,
    file_path: str,
    option: Mapping[str, Any] | None,
    client_factory: ClientFactory = EtlClient,
) -> None:
    del img_dir  # v1 preserves Figure OCR text; it does not emit image references.
    options = dict(option or {})
    config = EtlConfig.from_sources(options)
    default_json = client_factory(config).analyze(file_path)
    document = convert_default_json(default_json)
    doc_data = options.get("doc_data")
    if doc_data is not None and not isinstance(doc_data, Mapping):
        raise ValueError("option.doc_data must be an object")
    # doc_data is read-only input. A future project postprocessor may compute a
    # separate update, but no non-standard option field is treated as an update.
    export_hrc(document, file_path, work_dir, doc_data)
    collect_result_files(work_dir)


def parse(work_dir: str, img_dir: str, file_path: str, option: Any = None) -> None:
    """Run ETL -> Default JSON -> HRC and record the terminal status."""
    try:
        write_parse_status(work_dir, "PARSING")
        process_document(work_dir, img_dir, file_path, option)
        write_parse_status(work_dir, "DONE")
    except Exception as exc:
        write_parse_status(work_dir, "ERROR", str(exc))
