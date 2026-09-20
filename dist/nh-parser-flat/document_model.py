"""Dependency-free normalized representation of ETL Default JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Region:
    paragraph_id: str
    source_type: str
    contents: str
    page_id: int
    bbox: list[list[float]] = field(default_factory=list)
    rect: list[float] | None = None
    confidence: float | None = None
    section_level: int | None = None
    lines: list[dict[str, Any]] = field(default_factory=list)
    cells: list[dict[str, Any]] = field(default_factory=list)
    rows: int | None = None
    cols: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Page:
    page_id: int
    width: float | None
    height: float | None
    regions: list[Region] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedDocument:
    name: str
    pages: list[Page]
    warnings: list[str] = field(default_factory=list)

