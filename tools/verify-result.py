"""Validate a downloaded KL Custom Parser result ZIP using the source contract."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


ALLOWED_ITEMS = {"text", "table", "image", "h1", "h2", "h3", "h4"}


def verify(zip_path: Path, original_name: str) -> None:
    required = {f"{original_name}_hrc.jsonl", f"{original_name}_hrc.json"}
    optional = {f"{original_name}_img.zip", "doc_data.json"}
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        missing = required - names
        unexpected = names - required - optional
        if missing or unexpected:
            raise ValueError(
                f"Invalid result members: missing={sorted(missing)}, "
                f"unexpected={sorted(unexpected)}"
            )
        if any("/" in name or "\\" in name for name in names):
            raise ValueError("Result ZIP members must be at the archive root")

        jsonl_name = f"{original_name}_hrc.jsonl"
        lines = archive.read(jsonl_name).decode("utf-8").splitlines()
        if not lines:
            raise ValueError("HRC JSONL is empty")
        for line_number, line in enumerate(lines, start=1):
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"HRC line {line_number} is not an object")
            if item.get("item") not in ALLOWED_ITEMS:
                raise ValueError(f"HRC line {line_number} has an invalid item")
            if not isinstance(item.get("value"), str) or not item["value"]:
                raise ValueError(f"HRC line {line_number} has no value")
            if item["item"] == "table":
                prop = item.get("type_property")
                if not isinstance(prop, dict) or "title" not in prop:
                    raise ValueError(f"HRC table line {line_number} has no title")

        info = json.loads(archive.read(f"{original_name}_hrc.json").decode("utf-8"))
        if not isinstance(info, dict) or info.get("parsed_status") != "S":
            raise ValueError("HRC INFO JSON is invalid")

    print("Result ZIP contract validation passed")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify-result.py RESULT_ZIP ORIGINAL_FILENAME")
    verify(Path(sys.argv[1]), sys.argv[2])

