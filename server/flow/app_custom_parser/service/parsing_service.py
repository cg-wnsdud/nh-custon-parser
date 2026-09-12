"""Project parsing entrypoint required by the KL Custom Parser contract."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any

from .config import EtlConfig
from .etl_adapter import convert_default_json
from .etl_client import EtlClient
from .hrc_exporter import export_hrc
from .result_contract import collect_result_files
from .status import read_parse_status as _read_parse_status
from .status import write_parse_status as _write_parse_status


ClientFactory = Callable[[EtlConfig], EtlClient]


# Preserve the names and signatures marked DO NOT EDIT in the supplied example.
def write_parse_status(work_dir: str, work_status: str, msg: str = "") -> None:
    _write_parse_status(work_dir, work_status, msg)


def get_parse_status(work_dir: str) -> tuple[str, str]:
    try:
        status = _read_parse_status(work_dir)
        return status["status"], status["message"]
    except FileNotFoundError:
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


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--img-dir", required=True)
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--option-stdin", action="store_true", required=True)
    args = parser.parse_args()
    option = json.loads(sys.stdin.read())
    parse(args.work_dir, args.img_dir, args.file_path, option)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
