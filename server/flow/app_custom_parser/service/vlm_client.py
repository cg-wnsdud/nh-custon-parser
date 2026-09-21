"""VLM(OpenAI 호환) 호출 모듈.

HRC 생성 전 후처리 자리에 놓인다. 현재 단계에서는 농협 환경에서 VLM을 호출할 수
있는지 확인하는 용도로 1회만 호출하고, 결과를 HRC에 반영하지 않는다. 응답은
작업 디렉터리에 `{원본파일명}_vlm.json` 으로 남기며 이 파일은 결과 ZIP에 포함되지 않는다.

설정이 없으면 호출 자체를 건너뛰고, 호출이 실패해도 파싱은 계속 진행한다.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import requests

from document_model import NormalizedDocument


DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_PROMPT_CHARS = 1200
SIDECAR_SUFFIX = "_vlm.json"


class VlmError(RuntimeError):
    """Raised for an HTTP or response-shape failure of the VLM endpoint."""


def _number(env: Mapping[str, str], key: str, default: float, minimum: float) -> float:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class VlmConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    prompt_chars: int = DEFAULT_PROMPT_CHARS

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "VlmConfig | None":
        """설정이 하나도 없으면 None을 돌려 VLM 단계를 건너뛰게 한다."""
        env = os.environ if env is None else env
        base_url = (env.get("VLM_BASE_URL") or "").strip()
        model = (env.get("VLM_MODEL") or "").strip()
        if not base_url and not model:
            return None
        missing = [
            name
            for name, value in (("VLM_BASE_URL", base_url), ("VLM_MODEL", model))
            if not value
        ]
        if missing:
            raise ValueError("Missing VLM configuration: " + ", ".join(missing))

        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("VLM_BASE_URL must be an absolute http(s) URL")

        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=(env.get("VLM_API_KEY") or "").strip(),
            timeout_seconds=_number(env, "VLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, 1.0),
            prompt_chars=int(_number(env, "VLM_PROMPT_CHARS", DEFAULT_PROMPT_CHARS, 100.0)),
        )


def document_excerpt(document: NormalizedDocument, limit: int) -> str:
    """정규화된 문서 앞부분 텍스트를 프롬프트 길이에 맞춰 잘라 준다."""
    parts: list[str] = []
    length = 0
    for page in document.pages:
        for region in page.regions:
            text = region.contents.strip()
            if not text:
                continue
            parts.append(text)
            length += len(text) + 1
            if length >= limit:
                return "\n".join(parts)[:limit]
    return "\n".join(parts)[:limit]


def user_content(prompt: str, image: bytes | None = None, media_type: str = "image/png") -> Any:
    """이미지가 있으면 OpenAI 호환 멀티모달 content로, 없으면 문자열로 만든다."""
    if image is None:
        return prompt
    encoded = base64.b64encode(image).decode("ascii")
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
    ]


def chat(
    config: VlmConfig,
    messages: list[dict[str, Any]],
    session: Any | None = None,
) -> str:
    """OpenAI 호환 `/chat/completions` 를 호출하고 첫 응답 텍스트를 돌려준다."""
    caller = session or requests
    try:
        response = caller.post(
            f"{config.base_url}/chat/completions",
            json={
                "model": config.model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 256,
            },
            headers=_headers(config),
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise VlmError(f"VLM request failed: {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise VlmError(f"VLM HTTP {response.status_code}: {response.text[:300]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise VlmError("VLM response is not valid JSON") from exc

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VlmError("VLM response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise VlmError("VLM response message has no text content")
    return content.strip()


def _headers(config: VlmConfig) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def probe(
    document: NormalizedDocument,
    work_dir: str | os.PathLike[str],
    source_file: str | os.PathLike[str],
    env: Mapping[str, str] | None = None,
    session: Any | None = None,
) -> dict[str, Any] | None:
    """연결 확인용 1회 호출. 어떤 경우에도 예외를 밖으로 던지지 않는다."""
    try:
        config = VlmConfig.from_environment(env)
    except ValueError as exc:
        print(f"[vlm] 설정이 올바르지 않아 건너뜁니다: {exc}")
        return None

    if config is None:
        print("[vlm] VLM_BASE_URL/VLM_MODEL 미설정 - VLM 단계를 건너뜁니다")
        return None

    excerpt = document_excerpt(document, config.prompt_chars)
    messages = [
        {
            "role": "system",
            "content": "당신은 문서 분석 보조 도구입니다. 한국어로 한 문장만 답하십시오.",
        },
        {
            "role": "user",
            "content": user_content(f"다음 문서 일부의 주제를 한 문장으로 요약하세요.\n\n{excerpt}"),
        },
    ]

    record: dict[str, Any] = {
        "model": config.model,
        "base_url": config.base_url,
        "prompt_chars": len(excerpt),
        "document": document.name,
    }
    try:
        record["status"] = "ok"
        record["answer"] = chat(config, messages, session=session)
        print(f"[vlm] 호출 성공 ({config.model}): {record['answer'][:120]}")
    except Exception as exc:  # 파싱을 막지 않는다
        record["status"] = "error"
        record["error"] = f"{exc.__class__.__name__}: {exc}"
        print(f"[vlm] 호출 실패 - 파싱은 계속 진행합니다: {record['error']}")

    _write_sidecar(work_dir, source_file, record)
    return record


def _write_sidecar(
    work_dir: str | os.PathLike[str],
    source_file: str | os.PathLike[str],
    record: Mapping[str, Any],
) -> Path | None:
    """결과 ZIP에 포함되지 않는 확인용 파일로 남긴다."""
    path = Path(work_dir) / f"{Path(source_file).name}{SIDECAR_SUFFIX}"
    try:
        with path.open("w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[vlm] 확인용 파일 기록 실패: {exc}")
        return None
    return path
