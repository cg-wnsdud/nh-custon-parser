"""Validate and package only files allowed by the KL result contract."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from hrc_exporter import validate_hrc_items


def collect_result_files(work_dir: str | Path) -> list[Path]:
    directory = Path(work_dir)
    jsonl_files = list(directory.glob("*_hrc.jsonl"))
    info_files = list(directory.glob("*_hrc.json"))
    if len(jsonl_files) != 1 or len(info_files) != 1:
        raise ValueError("Result requires exactly one *_hrc.jsonl and one *_hrc.json")
    if jsonl_files[0].stem.removesuffix("_hrc") != info_files[0].stem.removesuffix("_hrc"):
        raise ValueError("HRC JSONL and INFO JSON base names do not match")

    items = []
    with jsonl_files[0].open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise ValueError(f"HRC JSONL line {line_number} is empty")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"HRC JSONL line {line_number} is not an object")
            items.append(value)
    validate_hrc_items(items)
    with info_files[0].open("r", encoding="utf-8") as stream:
        info = json.load(stream)
    if not isinstance(info, dict) or info.get("parsed_status") != "S":
        raise ValueError("HRC INFO JSON is invalid")

    result_files = [jsonl_files[0], info_files[0]]
    image_zip = directory / f"{jsonl_files[0].stem.removesuffix('_hrc')}_img.zip"
    if image_zip.exists():
        if not zipfile.is_zipfile(image_zip):
            raise ValueError("HRC image result is not a valid ZIP")
        result_files.append(image_zip)
    doc_data = directory / "doc_data.json"
    if doc_data.exists():
        with doc_data.open("r", encoding="utf-8") as stream:
            if not isinstance(json.load(stream), dict):
                raise ValueError("doc_data.json must contain an object")
        result_files.append(doc_data)
    return result_files


def build_result_zip(work_dir: str | Path) -> bytes:
    result_files = collect_result_files(work_dir)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in result_files:
            archive.write(path, arcname=path.name)
    return output.getvalue()

