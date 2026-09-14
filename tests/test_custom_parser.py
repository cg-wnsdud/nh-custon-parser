from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "server" / "flow" / "app_custom_parser"
sys.path.insert(0, str(APP_DIR))

from service.config import EtlConfig  # noqa: E402
from service.etl_adapter import EtlSchemaError, convert_default_json  # noqa: E402
from service.etl_client import EtlApiError, EtlClient  # noqa: E402
from service.hrc_exporter import export_hrc  # noqa: E402
from service.parsing_service import process_document  # noqa: E402
from service.result_contract import build_result_zip, collect_result_files  # noqa: E402


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
    def test_option_overrides_environment_and_defaults_to_dla(self):
        config = EtlConfig.from_sources(
            {"etl": {"base_url": "http://etl.local/", "author": "svc", "ws_id": "ws"}},
            {"ETL_BASE_URL": "http://ignored", "ETL_AUTHOR": "ignored", "ETL_WS_ID": "ignored"},
        )
        self.assertEqual(config.base_url, "http://etl.local")
        self.assertEqual(config.project_config["extract_type"], "dla")
        self.assertEqual(config.project_config["table_to_struct"], "html")

    def test_original_parser_info_prop_url_is_supported(self):
        config = EtlConfig.from_sources(
            {
                "parser_info": {
                    "prop": {
                        "supplier": "agilesoda",
                        "url": "http://etl.from-kl",
                        "key": "not-used-without-an-etl-header-contract",
                        "author": "svc",
                        "ws_id": "ws",
                    }
                }
            },
            {},
        )
        self.assertEqual(config.base_url, "http://etl.from-kl")

    def test_rejects_customize_extract_type(self):
        with self.assertRaises(ValueError):
            EtlConfig.from_sources(
                {
                    "etl": {
                        "base_url": "http://etl",
                        "author": "svc",
                        "ws_id": "ws",
                        "prj_config": {"extract_type": "customize"},
                    }
                },
                {},
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
            process_document(
                str(directory),
                str(image_dir),
                str(source),
                {"etl": {"base_url": "http://etl", "author": "svc", "ws_id": "ws"}},
                client_factory=FakeClient,
            )
            self.assertTrue((directory / "광고.pdf_hrc.jsonl").is_file())
            self.assertTrue((directory / "광고.pdf_hrc.json").is_file())


class MainHelpersTests(unittest.TestCase):
    def test_timeout_is_an_integer_for_the_sample_response_contract(self):
        try:
            import main
        except ModuleNotFoundError as exc:
            self.skipTest(f"platform web dependencies are unavailable: {exc}")
        self.assertIsInstance(main.TIMEOUT, int)


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
                with patch.object(self.main, "run_method_in_subprocess", return_value=None):
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
                self.assertIsInstance(payload["body"]["timeout"], int)
                job_dir = Path(temporary) / payload["body"]["uuid"]
                self.assertTrue((job_dir / "광고.pdf").is_file())
                self.assertFalse((job_dir / "option.json").exists())
            finally:
                self.main.PATH_WORK = old_root

    def test_invalid_option_and_unknown_uuid_follow_source_error_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            old_root = self.main.PATH_WORK
            self.main.PATH_WORK = Path(temporary)
            try:
                with self.TestClient(self.main.app) as client:
                    with contextlib.redirect_stdout(io.StringIO()):
                        response = client.post(
                            "/parsing",
                            files={"src_file": ("광고.pdf", b"pdf", "application/pdf")},
                            data={"option": "not-base64"},
                        )
                    self.assertEqual(response.status_code, 500)
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
                from service.status import write_parse_status

                with self.TestClient(self.main.app) as client:
                    write_parse_status(directory, "PARSING")
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"status": "PARSING"})

                    write_parse_status(directory, "ERROR", "etl failed")
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["status"], "ERROR")

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
                        self.assertEqual(
                            set(archive.namelist()), {"광고.pdf_hrc.jsonl", "광고.pdf_hrc.json"}
                        )
                    response = client.get(f"/parsing/result/{job_id}")
                    self.assertEqual(response.status_code, 500)
            finally:
                self.main.PATH_WORK = old_root


if __name__ == "__main__":
    unittest.main()
