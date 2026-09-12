"""ETLwithLLM 1.16+ analysis API client using only the Python standard library."""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote, urlencode, urlsplit

from .config import EtlConfig


class EtlApiError(RuntimeError):
    """Raised for an HTTP, API-contract, or ETL processing failure."""


@dataclass(frozen=True, slots=True)
class EtlJob:
    task_id: str
    file_path: str


class JsonTransport(Protocol):
    def get_json(self, path: str, query: Mapping[str, str]) -> dict[str, Any]: ...

    def post_multipart_json(
        self,
        path: str,
        fields: Mapping[str, str],
        file_field: str,
        file_path: Path,
    ) -> dict[str, Any]: ...


class StandardLibraryTransport:
    """Small streaming HTTP transport; authentication is outside this project scope."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ETL base_url must be an absolute http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("ETL base_url must not contain a query or fragment")
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port
        self._prefix = parsed.path.rstrip("/")
        self._timeout = timeout_seconds

    def _connection(self) -> http.client.HTTPConnection:
        connection_type = (
            http.client.HTTPSConnection
            if self._scheme == "https"
            else http.client.HTTPConnection
        )
        return connection_type(self._host, self._port, timeout=self._timeout)

    def _read_json(self, response: http.client.HTTPResponse) -> dict[str, Any]:
        body = response.read()
        if not 200 <= response.status < 300:
            excerpt = body[:500].decode("utf-8", errors="replace")
            raise EtlApiError(f"ETL HTTP {response.status}: {excerpt}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EtlApiError("ETL response is not valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise EtlApiError("ETL response JSON must be an object")
        return payload

    def get_json(self, path: str, query: Mapping[str, str]) -> dict[str, Any]:
        target = f"{self._prefix}{path}?{urlencode(query)}"
        connection = self._connection()
        try:
            connection.request("GET", target, headers={"Accept": "application/json"})
            return self._read_json(connection.getresponse())
        except (OSError, http.client.HTTPException) as exc:
            raise EtlApiError(f"ETL GET failed: {exc}") from exc
        finally:
            connection.close()

    def post_multipart_json(
        self,
        path: str,
        fields: Mapping[str, str],
        file_field: str,
        file_path: Path,
    ) -> dict[str, Any]:
        boundary = f"----nh-custom-parser-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        safe_filename = file_path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{safe_filename}"; filename*=UTF-8\'\'{quote(file_path.name)}\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        prefix = b"".join(chunks)
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        content_length = len(prefix) + file_path.stat().st_size + len(suffix)
        target = f"{self._prefix}{path}"

        connection = self._connection()
        try:
            connection.putrequest("POST", target)
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            connection.send(prefix)
            with file_path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    connection.send(block)
            connection.send(suffix)
            return self._read_json(connection.getresponse())
        except (OSError, http.client.HTTPException) as exc:
            raise EtlApiError(f"ETL POST failed: {exc}") from exc
        finally:
            connection.close()


def _api_code(payload: Mapping[str, Any], operation: str) -> None:
    result = payload.get("result")
    if result is None:
        return
    if not isinstance(result, Mapping):
        raise EtlApiError(f"{operation}: result must be an object")
    code = result.get("code")
    try:
        successful = int(code) == 0
    except (TypeError, ValueError):
        successful = False
    if not successful:
        message = result.get("message") or f"unexpected result code {code!r}"
        raise EtlApiError(f"{operation}: {message}")


class EtlClient:
    def __init__(
        self,
        config: EtlConfig,
        transport: JsonTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.transport = transport or StandardLibraryTransport(
            config.base_url, config.connect_timeout_seconds
        )
        self._sleep = sleep
        self._monotonic = monotonic

    def start(self, file_path: str | os.PathLike[str]) -> EtlJob:
        path = Path(file_path)
        tr_data = {
            "author": self.config.author,
            "ws_id": self.config.ws_id,
            "res_type": ["default"],
            "prj_config": self.config.project_config,
            "meta_info": {},
        }
        payload = self.transport.post_multipart_json(
            "/api/v1/etl/auto/start",
            {"tr_data": json.dumps(tr_data, ensure_ascii=False, separators=(",", ":"))},
            "upfiles",
            path,
        )
        _api_code(payload, "start analysis")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise EtlApiError("start analysis: data must be an object")
        task_ids = data.get("task_ids")
        file_paths = data.get("file_paths")
        if not isinstance(task_ids, list) or len(task_ids) != 1:
            raise EtlApiError("start analysis: expected exactly one task_id")
        if not isinstance(file_paths, list) or len(file_paths) != 1:
            raise EtlApiError("start analysis: expected exactly one file_path")
        return EtlJob(task_id=str(task_ids[0]), file_path=str(file_paths[0]))

    def wait_until_done(self, file_path: str) -> dict[str, Any]:
        deadline = self._monotonic() + self.config.analysis_timeout_seconds
        delay = self.config.poll_initial_seconds
        while self._monotonic() < deadline:
            payload = self.transport.get_json(
                "/api/v1/file/info", {"file_path": file_path}
            )
            _api_code(payload, "get analysis status")
            data = payload.get("data")
            datasource = data.get("datasource") if isinstance(data, Mapping) else None
            if not isinstance(datasource, list) or not datasource:
                raise EtlApiError("get analysis status: data.datasource is empty")
            status_record = datasource[0]
            if not isinstance(status_record, Mapping):
                raise EtlApiError("get analysis status: datasource item is invalid")
            status = str(status_record.get("chunk_status", ""))
            if status == "002":
                return dict(status_record)
            if status == "999":
                message = status_record.get("message") or status_record.get("error_message")
                raise EtlApiError(f"ETL analysis reported STATUS_ERROR: {message or 'no detail'}")
            if status not in {"000", "001"}:
                raise EtlApiError(f"Unknown ETL chunk_status: {status!r}")
            self._sleep(delay)
            delay = min(delay * 1.5, self.config.poll_max_seconds)
        raise TimeoutError("ETL analysis timed out")

    def list_results(self, file_path: str) -> list[dict[str, Any]]:
        payload = self.transport.get_json(
            "/api/v1/file/result/list", {"docPath": file_path}
        )
        _api_code(payload, "list analysis results")
        data = payload.get("data")
        if not isinstance(data, list):
            raise EtlApiError("list analysis results: data must be an array")
        return [dict(item) for item in data if isinstance(item, Mapping)]

    @staticmethod
    def select_default_result(results: list[dict[str, Any]], source_name: str) -> str:
        source_stem = Path(source_name).stem.casefold()
        candidates: list[dict[str, Any]] = []
        for item in results:
            name = str(item.get("file_name", ""))
            folded = name.casefold()
            if not folded.endswith(".json") or folded.endswith("_edit.json"):
                continue
            candidates.append(item)

        exact = [
            item
            for item in candidates
            if Path(str(item.get("file_name", ""))).stem.casefold() == source_stem
        ]
        selected = exact if exact else candidates
        if len(selected) != 1:
            names = [str(item.get("file_name", "")) for item in candidates]
            raise EtlApiError(
                f"Expected one Default JSON result, found {len(selected)}; candidates={names}"
            )
        result_path = selected[0].get("file_path")
        if not result_path:
            raise EtlApiError("Selected Default JSON has no file_path")
        return str(result_path)

    def get_result_document(self, result_path: str) -> dict[str, Any]:
        payload = self.transport.get_json(
            "/api/v1/file/result/doc", {"docResultPath": result_path}
        )
        if not isinstance(payload, dict):
            raise EtlApiError("Default JSON response must be an object")
        _api_code(payload, "get Default JSON result")
        return payload

    def analyze(self, file_path: str | os.PathLike[str]) -> dict[str, Any]:
        path = Path(file_path)
        job = self.start(path)
        self.wait_until_done(job.file_path)
        results = self.list_results(job.file_path)
        result_path = self.select_default_result(results, path.name)
        return self.get_result_document(result_path)
