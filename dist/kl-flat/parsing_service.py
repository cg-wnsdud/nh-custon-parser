import os
import json
import shutil


# ==============================================================
# DO NOT EDIT: 파싱 상태를 기록한다.
# ==============================================================
# PARSING : 파싱 중, DONE : 파싱 완료, ERROR : 파싱 오류
def write_parse_status(work_dir: str, work_status: str, msg: str=""):
    status_file = os.path.join(work_dir, "genaikl.status")
    temp_file = status_file + ".tmp"
    with open(temp_file, "w+", encoding="utf-8") as status_fd:
        _status = {"status": work_status, "message": msg}
        json.dump(_status, status_fd, ensure_ascii=False)
    shutil.move(temp_file, status_file, copy_function=shutil.copy)


# ==============================================================
# DO NOT EDIT: 현 파싱 상태를 반환한다.
# ==============================================================
def get_parse_status(work_dir: str):
    ret = ""
    status_file = os.path.join(work_dir, "genaikl.status")
    if os.path.exists(status_file):
        with open(status_file, "r", encoding="utf-8") as status_fd:
            json_data = json.load(status_fd)
            ret = (json_data["status"], json_data["message"])
    elif os.path.exists(work_dir) and os.path.exists(status_file + ".tmp"):
        ret = ("PARSING", "")
    else:
         # 디렉토리 및 상태 확인 파일이 없음. 즉, 잘못된 요청임.
        ret = ("UNKNOWN", "Requested url does not exist.")

    return ret


from collections.abc import Callable, Mapping
from typing import Any

from config import EtlConfig
from etl_adapter import convert_default_json
from etl_client import EtlClient
from hrc_exporter import export_hrc
from result_contract import collect_result_files

ClientFactory = Callable[[EtlConfig], EtlClient]


def process_document(
    work_dir: str,
    img_dir: str,
    file_path: str,
    option: Mapping[str, Any] | None,
    client_factory: ClientFactory = EtlClient,
) -> None:
    del img_dir  # v1 preserves Figure OCR text; it does not emit image references.
    options = dict(option or {})
    config = EtlConfig.from_sources(options)
    default_json = client_factory(config).analyze(file_path)
    document = convert_default_json(default_json)
    doc_data = options.get("doc_data")
    if doc_data is not None and not isinstance(doc_data, Mapping):
        raise ValueError("option.doc_data must be an object")
    # doc_data is read-only input. A future project postprocessor may compute a
    # separate update, but no non-standard option field is treated as an update.
    export_hrc(document, file_path, work_dir, doc_data)
    collect_result_files(work_dir)


# ==============================================================
# TODO: M A I N: 파싱
# ==============================================================
def parse(work_dir, img_dir, file_path, option=None):
    """Run ETL -> Default JSON -> HRC and record the terminal status."""
    try:
        write_parse_status(work_dir, "PARSING")
        process_document(work_dir, img_dir, file_path, option)
        write_parse_status(work_dir, "DONE")
    except Exception as exc:
        write_parse_status(work_dir, "ERROR", str(exc))
