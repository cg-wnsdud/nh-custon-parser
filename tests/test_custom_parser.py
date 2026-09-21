from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "server" / "flow" / "app_custom_parser"
SERVICE_DIR = APP_DIR / "service"
# 전달본과 같은 flat 배치로 임포트한다.
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(SERVICE_DIR))

from etl_config import EtlConfig  # noqa: E402
from etl_adapter import EtlSchemaError, convert_default_json  # noqa: E402
from etl_client import EtlApiError, EtlClient, RequestsTransport  # noqa: E402
from hrc_exporter import export_hrc  # noqa: E402
from parsing_service import process_document  # noqa: E402
from result_contract import build_result_zip, collect_result_files  # noqa: E402
from vlm_client import VlmConfig, document_excerpt, probe, user_content  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "default_result.json"


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self) -> None:
        self.statuses = ["000", "001", "002"]
        self.posted_tr_data: dict | None = None
        self.get_calls: list[tuple[str, dict[str, str]]] = []

    def post_multipart_json(self, path, fields, file_field, file_path):
        self.posted_tr_data = json.loads(fields["tr_data"])
        self.post_path = path
        self.file_field = file_field
        self.file_name = file_path.name
        return {
            "result": {"code": "0", "message": "success"},
            "data": {"task_ids": ["task-1"], "file_paths": ["광고.pdf/v1/광고.pdf"]},
        }

    def get_json(self, path, query):
        self.get_calls.append((path, dict(query)))
        if path.endswith("/info"):
            return {
                "result": {"code": 0},
                "data": {"datasource": [{"chunk_status": self.statuses.pop(0)}]},
            }
        if path.endswith("/list"):
            return {
                "result": {"code": 0},
                "data": [
                    {"file_name": "pipeline_log.log", "file_path": "log"},
                    {"file_name": "광고.json", "file_path": "result/광고.json"},
                    {"file_name": "광고_edit.json", "file_path": "result/edit.json"},
                ],
            }
        if path.endswith("/doc"):
            return {"doc_result": {"default": fixture_payload()}}
        raise AssertionError(path)


class ConfigTests(unittest.TestCase):
    def test_environment_values_and_defaults(self):
        config = EtlConfig.from_environment(
            {
                "ETL_BASE_URL": "http://etl.local/",
                "ETL_AUTHOR": "svc",
                "ETL_WS_ID": "ws",
            }
        )
        self.assertEqual(config.base_url, "http://etl.local")
        self.assertEqual(config.project_config["extract_type"], "dla")
        self.assertEqual(config.project_config["table_to_struct"], "html")

    def test_missing_environment_values_are_reported(self):
        with self.assertRaisesRegex(ValueError, "ETL_AUTHOR, ETL_WS_ID"):
            EtlConfig.from_environment({"ETL_BASE_URL": "http://etl"})

    def test_rejects_customize_extract_type(self):
        with self.assertRaises(ValueError):
            EtlConfig.from_environment(
                {
                    "ETL_BASE_URL": "http://etl",
                    "ETL_AUTHOR": "svc",
                    "ETL_WS_ID": "ws",
                    "ETL_PRJ_CONFIG": '{"extract_type":"customize"}',
                }
            )


class AdapterAndExporterTests(unittest.TestCase):
    def test_wrapped_default_json_and_polygon_are_preserved(self):
        document = convert_default_json({"doc_result": {"default": fixture_payload()}})
        self.assertEqual(document.name, "광고.pdf")
        self.assertEqual(document.pages[0].regions[0].bbox[0], [100.0, 100.0])
        self.assertEqual(document.pages[0].regions[0].rect, [100.0, 100.0, 800.0, 180.0])

    def test_missing_pages_is_rejected(self):
        with self.assertRaises(EtlSchemaError):
            convert_default_json({"pdfName": "bad.pdf"})

    def test_exact_result_contract_without_unconfirmed_cust_meta(self):
        document = convert_default_json(fixture_payload())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "광고.pdf"
            source.write_bytes(b"%PDF-test")
            export_hrc(
                document,
                source,
                directory,
                {
                    "doc_id": "DOC-1",
                    "origin_doc_id": "SRC-1",
                    "origin_sys_nm": "NH",
                    "product_group": "대출",
                },
            )
            (directory / "debug.json").write_text("{}", encoding="utf-8")
            result_files = collect_result_files(directory)
            self.assertEqual(
                {path.name for path in result_files}, {"광고.pdf_hrc.jsonl", "광고.pdf_hrc.json"}
            )
            actual_lines = (directory / "광고.pdf_hrc.jsonl").read_text(encoding="utf-8").splitlines()
            expected_lines = (ROOT / "tests" / "fixtures" / "expected_hrc.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line) for line in actual_lines], [json.loads(line) for line in expected_lines])
            first = json.loads(actual_lines[0])
            self.assertEqual(first["item"], "h1")
            self.assertNotIn("page", first)
            self.assertNotIn("cust_meta", first)
            table = json.loads(actual_lines[2])
            self.assertEqual(table["type_property"], {"title": ""})
            figure = json.loads(actual_lines[3])
            self.assertEqual(figure["item"], "text")

            archive_path = directory / "result.zip"
            archive_path.write_bytes(build_result_zip(directory))
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {"광고.pdf_hrc.jsonl", "광고.pdf_hrc.json"})


class EtlClientTests(unittest.TestCase):
    def test_requests_transport_builds_get_and_multipart_requests(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"code": 0}}
        response.text = ""
        session = Mock()
        session.get.return_value = response
        session.post.return_value = response
        transport = RequestsTransport("http://etl.local/base/", 30, session=session)

        transport.get_json("/status", {"file_path": "문서.pdf"})
        session.get.assert_called_once_with(
            "http://etl.local/base/status",
            params={"file_path": "문서.pdf"},
            headers={"Accept": "application/json"},
            timeout=(30, 30),
        )

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "문서.pdf"
            source.write_bytes(b"pdf")
            transport.post_multipart_json(
                "/start", {"tr_data": "{}"}, "upfiles", source
            )
        call = session.post.call_args
        self.assertEqual(call.args[0], "http://etl.local/base/start")
        self.assertEqual(call.kwargs["data"], {"tr_data": "{}"})
        self.assertIn("upfiles", call.kwargs["files"])

    def test_complete_analysis_flow_uses_section_116_contract(self):
        transport = FakeTransport()
        clock_values = iter([0.0, 0.0, 0.1, 0.2, 0.3])
        config = EtlConfig(
            base_url="http://etl",
            author="svc",
            ws_id="workspace",
            analysis_timeout_seconds=10,
            poll_initial_seconds=0.01,
            poll_max_seconds=0.02,
        )
        client = EtlClient(
            config,
            transport=transport,
            sleep=lambda _: None,
            monotonic=lambda: next(clock_values),
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "광고.pdf"
            source.write_bytes(b"pdf")
            result = client.analyze(source)
        self.assertIn("doc_result", result)
        self.assertEqual(transport.post_path, "/api/v1/etl/auto/start")
        self.assertEqual(transport.file_field, "upfiles")
        self.assertEqual(transport.posted_tr_data["res_type"], ["default"])
        self.assertEqual(transport.posted_tr_data["prj_config"]["extract_type"], "dla")
        self.assertEqual(
            transport.get_calls[:3],
            [
                ("/api/v1/file/info", {"file_path": "광고.pdf/v1/광고.pdf"}),
                ("/api/v1/file/info", {"file_path": "광고.pdf/v1/광고.pdf"}),
                ("/api/v1/file/info", {"file_path": "광고.pdf/v1/광고.pdf"}),
            ],
        )
        self.assertEqual(
            transport.get_calls[3],
            ("/api/v1/file/result/list", {"docPath": "광고.pdf/v1/광고.pdf"}),
        )
        self.assertEqual(
            transport.get_calls[4],
            ("/api/v1/file/result/doc", {"docResultPath": "result/광고.json"}),
        )

    def test_ambiguous_default_result_is_rejected(self):
        with self.assertRaises(EtlApiError):
            EtlClient.select_default_result(
                [
                    {"file_name": "a.json", "file_path": "a"},
                    {"file_name": "b.json", "file_path": "b"},
                ],
                "source.pdf",
            )


class ParsingServiceTests(unittest.TestCase):
    def test_process_document_is_injectable_without_real_etl(self):
        class FakeClient:
            def __init__(self, config):
                self.config = config

            def analyze(self, file_path):
                return fixture_payload()

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "광고.pdf"
            source.write_bytes(b"pdf")
            image_dir = directory / "image"
            image_dir.mkdir()
            with patch.dict(
                os.environ,
                {
                    "ETL_BASE_URL": "http://etl",
                    "ETL_AUTHOR": "svc",
                    "ETL_WS_ID": "ws",
                },
                clear=False,
            ):
                process_document(
                    str(directory),
                    str(image_dir),
                    str(source),
                    None,
                    client_factory=FakeClient,
                )
            self.assertTrue((directory / "광고.pdf_hrc.jsonl").is_file())
            self.assertTrue((directory / "광고.pdf_hrc.json").is_file())


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import main
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"platform web dependencies are unavailable: {exc}")
        cls.main = main
        cls.TestClient = TestClient

    def test_post_returns_202_uuid_and_integer_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            old_root = self.main.PATH_WORK
            self.main.PATH_WORK = Path(temporary)
            try:
                with patch.object(self.main, "run_method_in_subprocess", return_value=None) as mocked:
                    with self.TestClient(self.main.app) as client:
                        response = client.post(
                            "/parsing",
                            files={"src_file": ("광고.pdf", b"pdf", "application/pdf")},
                            data={"option": "e30="},
                        )
                self.assertEqual(response.status_code, 202)
                payload = response.json()
                self.assertEqual(payload["result"], "OK")
                self.assertEqual(len(payload["body"]["uuid"]), 32)
                self.assertEqual(payload["body"]["timeout"], self.main.TIMEOUT)
                job_dir = Path(temporary) / payload["body"]["uuid"]
                self.assertTrue((job_dir / "광고.pdf").is_file())
                # 템플릿 원본 main.py는 option을 parse()로 전달하지 않는다.
                # ETL 접속 정보를 환경변수로 받는 이유가 이것이다.
                self.assertEqual(mocked.call_args.args[4], {})
            finally:
                self.main.PATH_WORK = old_root

    def test_template_ignores_option_and_unknown_uuid_returns_500(self):
        with tempfile.TemporaryDirectory() as temporary:
            old_root = self.main.PATH_WORK
            self.main.PATH_WORK = Path(temporary)
            try:
                with self.TestClient(self.main.app) as client:
                    with contextlib.redirect_stdout(io.StringIO()):
                        with patch.object(self.main, "run_method_in_subprocess", return_value=None):
                            response = client.post(
                                "/parsing",
                                files={"src_file": ("광고.pdf", b"pdf", "application/pdf")},
                                data={"option": "not-base64"},
                            )
                    # 원본 main.py는 option을 읽지 않으므로 잘못된 값이어도 오류가 되지 않는다.
                    self.assertEqual(response.status_code, 202)
                    response = client.get("/parsing/result/" + "f" * 32)
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(response.json()["message"], "Requested url does not exist.")
            finally:
                self.main.PATH_WORK = old_root

    def test_subprocess_uses_original_parse_entrypoint_and_passes_option(self):
        options = {"etl": {"base_url": "http://internal", "ws_id": "workspace"}}
        process = Mock()
        process.communicate.return_value = (b"", b"")
        process.returncode = 0
        with patch.object(self.main.subprocess, "Popen", return_value=process) as mocked:
            self.main.run_method_in_subprocess(
                600, "work", "image", "document.pdf", options
            )
        command = mocked.call_args.args[0]
        self.assertEqual(command[1], "-c")
        self.assertIn("from service.parsing_service import parse", command[2])
        self.assertIn(repr(options), command[2])
        process.communicate.assert_called_once_with(timeout=610)

    def test_health(self):
        with self.TestClient(self.main.app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "OK"})

    def test_polling_error_and_done_zip_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            old_root = self.main.PATH_WORK
            self.main.PATH_WORK = Path(temporary)
            try:
                job_id = "a" * 32
                directory = Path(temporary) / job_id
                directory.mkdir()
                source = directory / "광고.pdf"
                source.write_bytes(b"pdf")
                from parsing_service import write_parse_status

                with self.TestClient(self.main.app) as client:
                    write_parse_status(directory, "PARSING")
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"status": "PARSING"})

                    # 원본 main.py에는 ERROR 전용 분기가 없어 500 + message로 응답한다.
                    write_parse_status(directory, "ERROR", "etl failed")
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(response.json()["message"], "etl failed")

                    directory.mkdir()
                    (directory / "image").mkdir()
                    source = directory / "광고.pdf"
                    source.write_bytes(b"pdf")
                    export_hrc(convert_default_json(fixture_payload()), source, directory)
                    write_parse_status(directory, "DONE")
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["content-type"], "application/x-zip-compressed")
                    self.assertFalse(directory.exists())
                    archive_path = Path(temporary) / "response.zip"
                    archive_path.write_bytes(response.content)
                    with zipfile.ZipFile(archive_path) as archive:
                        # 원본 main.py는 이미지가 없어도 빈 _img.zip을 함께 넣는다.
                        self.assertEqual(
                            set(archive.namelist()),
                            {"광고.pdf_hrc.jsonl", "광고.pdf_hrc.json", "광고.pdf_img.zip"},
                        )
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 500)
            finally:
                self.main.PATH_WORK = old_root


class FakeVlmResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeVlmSession:
    """requests.post 만 흉내 내는 최소 세션."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


def sample_document():
    return convert_default_json(fixture_payload())


class VlmConfigTests(unittest.TestCase):
    def test_absent_settings_skip_the_step(self):
        self.assertIsNone(VlmConfig.from_environment({}))

    def test_partial_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            VlmConfig.from_environment({"VLM_BASE_URL": "http://vlm/v1"})

    def test_values_are_parsed(self):
        config = VlmConfig.from_environment(
            {
                "VLM_BASE_URL": "http://vlm.local/v1/",
                "VLM_MODEL": "gemma-3-27b-it",
                "VLM_API_KEY": "secret",
                "VLM_TIMEOUT_SECONDS": "15",
            }
        )
        self.assertEqual(config.base_url, "http://vlm.local/v1")
        self.assertEqual(config.model, "gemma-3-27b-it")
        self.assertEqual(config.timeout_seconds, 15.0)


class VlmProbeTests(unittest.TestCase):
    ENV = {"VLM_BASE_URL": "http://vlm.local/v1", "VLM_MODEL": "gemma-3-27b-it"}

    def test_successful_call_writes_a_sidecar_outside_the_result_zip(self):
        session = FakeVlmSession(
            FakeVlmResponse(payload={"choices": [{"message": {"content": "대출 상품 안내 문서입니다."}}]})
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "광고.pdf"
            source.write_bytes(b"pdf")
            with contextlib.redirect_stdout(io.StringIO()):
                record = probe(sample_document(), directory, source, env=self.ENV, session=session)

            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["answer"], "대출 상품 안내 문서입니다.")
            sidecar = directory / "광고.pdf_vlm.json"
            self.assertTrue(sidecar.is_file())

            # 결과 규격 파일이 아니므로 ZIP 대상에서 제외된다.
            export_hrc(sample_document(), source, directory)
            names = {path.name for path in collect_result_files(directory)}
            self.assertNotIn(sidecar.name, names)

        call = session.calls[0]
        self.assertEqual(call["url"], "http://vlm.local/v1/chat/completions")
        self.assertEqual(call["json"]["model"], "gemma-3-27b-it")
        self.assertNotIn("Authorization", call["headers"])

    def test_failure_is_recorded_without_breaking_parsing(self):
        session = FakeVlmSession(error=RuntimeError("connection refused"))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "광고.pdf"
            source.write_bytes(b"pdf")
            with contextlib.redirect_stdout(io.StringIO()):
                record = probe(sample_document(), directory, source, env=self.ENV, session=session)
        self.assertEqual(record["status"], "error")
        self.assertIn("connection refused", record["error"])

    def test_api_key_and_image_content_are_supported(self):
        env = dict(self.ENV, VLM_API_KEY="secret")
        session = FakeVlmSession(FakeVlmResponse(payload={"choices": [{"message": {"content": "요약"}}]}))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "광고.pdf"
            source.write_bytes(b"pdf")
            with contextlib.redirect_stdout(io.StringIO()):
                probe(sample_document(), directory, source, env=env, session=session)
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret")

        content = user_content("설명", image=b"fake-png-bytes", media_type="image/png")
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_excerpt_is_capped(self):
        excerpt = document_excerpt(sample_document(), 20)
        self.assertLessEqual(len(excerpt), 20)


class DeliveryBundleTests(unittest.TestCase):
    """농협 전달본은 flat 구성이며 플랫폼 진입점을 포함하지 않는다."""

    @staticmethod
    def _builder():
        sys.path.insert(0, str(ROOT / "tools"))
        import build_delivery_bundle

        return build_delivery_bundle

    def test_bundle_is_flat_and_excludes_platform_entrypoints(self):
        builder = self._builder()
        with tempfile.TemporaryDirectory() as temporary:
            target = builder.build(Path(temporary) / "bundle")
            names = {path.name for path in target.iterdir()}
        self.assertEqual(names, set(builder.REQUIRED_NAMES))
        self.assertNotIn("main.py", names)
        self.assertNotIn("gunicorn_config.py", names)

    def test_service_sources_stay_flat(self):
        for path in SERVICE_DIR.iterdir():
            if path.name == "__pycache__":
                continue
            self.assertTrue(path.is_file(), f"flat 구성 위반: {path}")


if __name__ == "__main__":
    unittest.main()
