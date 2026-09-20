"""ETLwithLLM settings supplied through process environment variables."""

from __future__ import annotations

import json
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


def _required(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    rendered = str(value).strip() if value is not None else ""
    return rendered or None


def _json_object(value: str | None, name: str) -> dict[str, Any]:
    if value is None or value.strip() == "":
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    return parsed


def _number(env: Mapping[str, str], key: str, default: float, minimum: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc
    if result < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
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
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "EtlConfig":
        env = os.environ if environ is None else environ
        values = {
            "ETL_BASE_URL": _required(env, "ETL_BASE_URL"),
            "ETL_AUTHOR": _required(env, "ETL_AUTHOR"),
            "ETL_WS_ID": _required(env, "ETL_WS_ID"),
        }
        missing = [key for key, value in values.items() if value is None]
        if missing:
            raise ValueError("Missing ETL configuration: " + ", ".join(missing))

        project_config = {
            "extract_type": "dla",
            "table_to_struct": "html",
        }
        supplied_project_config = _json_object(
            env.get("ETL_PRJ_CONFIG"), "ETL_PRJ_CONFIG"
        )
        unknown = sorted(set(supplied_project_config) - ALLOWED_PROJECT_OPTIONS)
        if unknown:
            raise ValueError(f"Unsupported ETL_PRJ_CONFIG keys: {unknown}")
        project_config.update(supplied_project_config)

        extract_type = str(project_config["extract_type"]).lower()
        if extract_type not in ALLOWED_EXTRACT_TYPES:
            raise ValueError("extract_type must be one of all, dla, parser")
        project_config["extract_type"] = extract_type

        poll_initial = _number(env, "ETL_POLL_INITIAL_SECONDS", 1.0, 0.05)
        poll_max = _number(env, "ETL_POLL_MAX_SECONDS", 5.0, poll_initial)
        return cls(
            base_url=values["ETL_BASE_URL"].rstrip("/"),
            author=values["ETL_AUTHOR"],
            ws_id=values["ETL_WS_ID"],
            connect_timeout_seconds=_number(
                env, "ETL_CONNECT_TIMEOUT_SECONDS", 30.0, 0.1
            ),
            analysis_timeout_seconds=_number(
                env, "ETL_ANALYSIS_TIMEOUT_SECONDS", 540.0, 1.0
            ),
            poll_initial_seconds=poll_initial,
            poll_max_seconds=poll_max,
            project_config=project_config,
        )
