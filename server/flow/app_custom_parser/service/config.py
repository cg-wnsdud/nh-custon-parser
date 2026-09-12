"""Configuration resolved from KL option data and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping


ALLOWED_EXTRACT_TYPES = frozenset({"all", "dla", "parser"})
ALLOWED_PROJECT_OPTIONS = frozenset(
    {
        "extract_type",
        "table_to_struct",
        "tsr_model_name",
        "n_columns",
        "rm_overlap_dla_flag",
        "ocr_only",
        "adjusting_process",
        "merge_unknown_type",
        "draw_viz",
        "draw_tsr",
        "draw_sort",
        "dla_score_th",
        "str_score_th",
        "start_page",
        "end_page",
    }
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _number(value: Any, default: float, name: str, minimum: float) -> float:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


@dataclass(frozen=True, slots=True)
class EtlConfig:
    base_url: str
    author: str
    ws_id: str
    connect_timeout_seconds: float = 30.0
    analysis_timeout_seconds: float = 540.0
    poll_initial_seconds: float = 1.0
    poll_max_seconds: float = 5.0
    project_config: dict[str, Any] = field(
        default_factory=lambda: {
            "extract_type": "dla",
            "table_to_struct": "html",
        }
    )

    @classmethod
    def from_sources(
        cls,
        option: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "EtlConfig":
        option = _mapping(option)
        parser_info = _mapping(option.get("parser_info"))
        parser_properties = _mapping(parser_info.get("prop"))
        explicit = _mapping(option.get("etl"))
        env = os.environ if environ is None else environ

        def take(key: str, env_key: str, *property_aliases: str) -> Any:
            if key in explicit:
                return explicit[key]
            if key in parser_properties:
                return parser_properties[key]
            for alias in property_aliases:
                if alias in parser_properties:
                    return parser_properties[alias]
            return env.get(env_key)

        # The supplied KL option contract names the generic provider URL `url`.
        # author/ws_id are ETL 1.16 fields and are not defined by that generic
        # contract, so they still come from the ETL block, prop extension, or env.
        base_url = _nonempty(take("base_url", "ETL_BASE_URL", "url"))
        author = _nonempty(take("author", "ETL_AUTHOR"))
        ws_id = _nonempty(take("ws_id", "ETL_WS_ID"))
        missing = [
            name
            for name, value in (
                ("base_url/ETL_BASE_URL", base_url),
                ("author/ETL_AUTHOR", author),
                ("ws_id/ETL_WS_ID", ws_id),
            )
            if value is None
        ]
        if missing:
            raise ValueError("Missing ETL configuration: " + ", ".join(missing))

        raw_project_config: dict[str, Any] = {}
        raw_project_config.update(_mapping(parser_properties.get("prj_config")))
        raw_project_config.update(_mapping(explicit.get("prj_config")))
        unknown = sorted(set(raw_project_config) - ALLOWED_PROJECT_OPTIONS)
        if unknown:
            raise ValueError(f"Unsupported ETL prj_config keys: {unknown}")

        project_config: dict[str, Any] = {
            "extract_type": "dla",
            "table_to_struct": "html",
        }
        project_config.update(raw_project_config)
        extract_type = str(project_config["extract_type"]).lower()
        if extract_type not in ALLOWED_EXTRACT_TYPES:
            raise ValueError(
                "prj_config.extract_type must be one of all, dla, parser"
            )
        project_config["extract_type"] = extract_type

        connect_timeout = _number(
            take("connect_timeout_seconds", "ETL_CONNECT_TIMEOUT_SECONDS"),
            30.0,
            "connect_timeout_seconds",
            0.1,
        )
        analysis_timeout = _number(
            take("analysis_timeout_seconds", "ETL_ANALYSIS_TIMEOUT_SECONDS"),
            540.0,
            "analysis_timeout_seconds",
            1.0,
        )
        poll_initial = _number(
            take("poll_initial_seconds", "ETL_POLL_INITIAL_SECONDS"),
            1.0,
            "poll_initial_seconds",
            0.05,
        )
        poll_max = _number(
            take("poll_max_seconds", "ETL_POLL_MAX_SECONDS"),
            5.0,
            "poll_max_seconds",
            poll_initial,
        )

        return cls(
            base_url=base_url.rstrip("/"),
            author=author,
            ws_id=ws_id,
            connect_timeout_seconds=connect_timeout,
            analysis_timeout_seconds=analysis_timeout,
            poll_initial_seconds=poll_initial,
            poll_max_seconds=poll_max,
            project_config=project_config,
        )
