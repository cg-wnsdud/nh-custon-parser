"""Convert normalized ETL documents into the exact KL HRC result files."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .document_model import NormalizedDocument, Region


ALLOWED_ITEMS = frozenset({"text", "table", "image", "h1", "h2", "h3", "h4"})
ATTR_NAMES = frozenset(f"cust_attr{index}" for index in range(1, 11))
SATTR_NAMES = frozenset(f"cust_sattr{index}" for index in range(1, 6))


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _item_for(region: Region) -> str:
    if region.source_type == "Table":
        return "table"
    if region.source_type == "Title" and region.section_level in {1, 2, 3, 4}:
        return f"h{region.section_level}"
    return "text"


def document_to_hrc_items(document: NormalizedDocument) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in document.pages:
        for region in page.regions:
            value = region.contents.strip()
            if not value:
                document.warnings.append(
                    f"page {page.page_id} paragraph {region.paragraph_id}: empty content omitted"
                )
                continue
            item_type = _item_for(region)
            item: dict[str, Any] = {"item": item_type, "value": value}
            # The source guide permits page on text/table/image. Its heading
            # examples omit page, so headings follow that exact conservative form.
            if item_type in {"text", "table", "image"}:
                item["page"] = page.page_id
            if item_type == "table":
                item["type_property"] = {"title": ""}
            items.append(item)
    return items


def validate_hrc_items(items: list[dict[str, Any]]) -> None:
    if not items:
        raise ValueError("HRC JSONL must contain at least one non-empty item")
    for index, item in enumerate(items, start=1):
        if item.get("item") not in ALLOWED_ITEMS:
            raise ValueError(f"HRC line {index}: unsupported item {item.get('item')!r}")
        if not isinstance(item.get("value"), str) or not item["value"]:
            raise ValueError(f"HRC line {index}: value must be a non-empty string")
        if item["item"] == "table":
            type_property = item.get("type_property")
            if not isinstance(type_property, dict) or "title" not in type_property:
                raise ValueError(f"HRC line {index}: table requires type_property.title")
        for meta in item.get("cust_meta", []):
            if not isinstance(meta, dict) or meta.get("name") not in ATTR_NAMES | SATTR_NAMES:
                raise ValueError(f"HRC line {index}: invalid cust_meta entry")
            if not isinstance(meta.get("value"), str) or not meta["value"]:
                raise ValueError(f"HRC line {index}: cust_meta value must be non-empty")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def export_hrc(
    document: NormalizedDocument,
    source_file: str | os.PathLike[str],
    work_dir: str | os.PathLike[str],
    doc_data: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    source = Path(source_file)
    output_dir = Path(work_dir)
    # The NH source guide uses src_file.filename + suffix, preserving extension.
    result_base_name = source.name
    jsonl_path = output_dir / f"{result_base_name}_hrc.jsonl"
    info_path = output_dir / f"{result_base_name}_hrc.json"

    items = document_to_hrc_items(document)
    validate_hrc_items(items)
    jsonl_text = "".join(
        json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
        for item in items
    )

    metadata = doc_data if isinstance(doc_data, Mapping) else {}
    first_title = next(
        (
            item["value"]
            for item in items
            if item["item"] in {"h1", "h2", "h3", "h4"}
        ),
        "",
    )
    info = {
        "name": source.name,
        "source": str(source),
        "file_type": source.suffix.lstrip(".").lower(),
        "size": source.stat().st_size,
        "title": str(_first(metadata, "title", "doc_title") or first_title),
        "subject": str(_first(metadata, "subject") or ""),
        "updated": str(_first(metadata, "updated", "updated_at") or ""),
        "parsed_status": "S",
        "page_info": [
            {"page": page.page_id, "width": page.width, "height": page.height}
            for page in document.pages
        ],
    }

    _atomic_write_text(jsonl_path, jsonl_text)
    _atomic_write_text(
        info_path, json.dumps(info, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return jsonl_path, info_path
