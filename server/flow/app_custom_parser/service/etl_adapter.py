"""Validate and normalize ETLwithLLM Default JSON without Pydantic."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .document_model import NormalizedDocument, Page, Region


KNOWN_PARAGRAPH_FIELDS = frozenset(
    {
        "paragraphId",
        "type",
        "bbox",
        "contents",
        "confidence",
        "lines",
        "parentId",
        "childId",
        "error_type",
        "rows",
        "cols",
        "cells",
        "pageId",
        "section_level",
        "list_hierarchy",
        "warning_messages",
        "n_cols",
    }
)


class EtlSchemaError(ValueError):
    """Raised when an ETL response cannot be interpreted as Default JSON."""


def unwrap_default_json(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept the direct and wrapped result forms shown in the API guide."""
    current: Any = payload
    for _ in range(4):
        if isinstance(current, Mapping) and isinstance(current.get("pages"), list):
            return current
        if not isinstance(current, Mapping):
            break
        if isinstance(current.get("default"), Mapping):
            current = current["default"]
            continue
        if isinstance(current.get("doc_result"), Mapping):
            current = current["doc_result"]
            continue
        if isinstance(current.get("data"), Mapping):
            current = current["data"]
            continue
        break
    raise EtlSchemaError("ETL result does not contain a Default JSON pages array")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise EtlSchemaError(f"{field_name} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EtlSchemaError(f"{field_name} must be numeric") from exc


def _integer(value: Any, default: int, field_name: str) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise EtlSchemaError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EtlSchemaError(f"{field_name} must be an integer") from exc


def _polygon(value: Any, warnings: list[str], location: str) -> list[list[float]]:
    if value in (None, []):
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        warnings.append(f"{location}: bbox is not a polygon")
        return []
    points: list[list[float]] = []
    for point in value:
        if (
            not isinstance(point, Sequence)
            or isinstance(point, (str, bytes))
            or len(point) < 2
        ):
            warnings.append(f"{location}: bbox contains an invalid point")
            return []
        try:
            points.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            warnings.append(f"{location}: bbox contains a non-numeric point")
            return []
    return points


def convert_default_json(payload: Mapping[str, Any]) -> NormalizedDocument:
    source = unwrap_default_json(payload)
    raw_pages = source.get("pages")
    if not isinstance(raw_pages, list):
        raise EtlSchemaError("Default JSON pages must be an array")

    name = _text(source.get("pdfName")) or "document"
    warnings: list[str] = []
    pages: list[Page] = []

    declared_page_count = source.get("pageLen")
    if declared_page_count is not None:
        try:
            if int(declared_page_count) != len(raw_pages):
                warnings.append(
                    f"pageLen={declared_page_count} differs from pages={len(raw_pages)}"
                )
        except (TypeError, ValueError):
            warnings.append("pageLen is not an integer")

    for page_index, raw_page in enumerate(raw_pages, start=1):
        if not isinstance(raw_page, Mapping):
            raise EtlSchemaError(f"pages[{page_index - 1}] must be an object")
        source_page_id = _integer(raw_page.get("pageId"), page_index, "pageId")
        page_number = source_page_id if source_page_id > 0 else page_index
        raw_paragraphs = raw_page.get("paragraphs", [])
        if not isinstance(raw_paragraphs, list):
            raise EtlSchemaError(f"page {source_page_id} paragraphs must be an array")

        regions: list[Region] = []
        for region_index, raw_region in enumerate(raw_paragraphs):
            if not isinstance(raw_region, Mapping):
                warnings.append(
                    f"page {source_page_id} paragraph {region_index}: not an object"
                )
                continue
            location = f"page {source_page_id} paragraph {region_index}"
            paragraph_id = _text(raw_region.get("paragraphId")) or str(region_index)
            source_type = _text(raw_region.get("type")) or "Unknown"
            contents = _text(raw_region.get("contents"))
            lines = raw_region.get("lines")
            safe_lines = [dict(line) for line in lines if isinstance(line, Mapping)] if isinstance(lines, list) else []
            if not contents and safe_lines:
                contents = "\n".join(
                    _text(line.get("contents")) for line in safe_lines if line.get("contents")
                )

            bbox = _polygon(raw_region.get("bbox"), warnings, location)
            rect = None
            if bbox:
                xs = [point[0] for point in bbox]
                ys = [point[1] for point in bbox]
                rect = [min(xs), min(ys), max(xs), max(ys)]

            confidence = _number(raw_region.get("confidence"), "confidence")
            section_level = None
            if raw_region.get("section_level") not in (None, ""):
                try:
                    section_level = int(raw_region["section_level"])
                except (TypeError, ValueError):
                    warnings.append(f"{location}: section_level is not an integer")

            raw_cells = raw_region.get("cells")
            cells = [dict(cell) for cell in raw_cells if isinstance(cell, Mapping)] if isinstance(raw_cells, list) else []
            extra = {
                key: value
                for key, value in raw_region.items()
                if key not in KNOWN_PARAGRAPH_FIELDS
            }
            warning_messages = raw_region.get("warning_messages")
            if isinstance(warning_messages, list):
                warnings.extend(f"{location}: {message}" for message in warning_messages)

            regions.append(
                Region(
                    paragraph_id=paragraph_id,
                    source_type=source_type,
                    contents=contents,
                    page_id=page_number,
                    bbox=bbox,
                    rect=rect,
                    confidence=confidence,
                    section_level=section_level,
                    lines=safe_lines,
                    cells=cells,
                    rows=_integer(raw_region.get("rows"), 0, "rows") or None,
                    cols=_integer(
                        raw_region.get("cols", raw_region.get("n_cols")), 0, "cols"
                    )
                    or None,
                    extra=extra,
                )
            )

        pages.append(
            Page(
                page_id=page_number,
                width=_number(raw_page.get("width"), "page width"),
                height=_number(raw_page.get("height"), "page height"),
                regions=regions,
            )
        )

    return NormalizedDocument(name=name, pages=pages, warnings=warnings)

