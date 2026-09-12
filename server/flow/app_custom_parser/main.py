"""Knowledge Lake HTTP entrypoint based on the supplied NH example."""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from service.parsing_service import get_parse_status, write_parse_status
from service.result_contract import build_result_zip


# The sample exposes TIMEOUT and PATH_TEMP through the platform environment.
TIMEOUT = int(os.getenv("TIMEOUT", "600"))
PATH_WORK = os.getenv("PATH_TEMP", "./temp")
JOB_RETENTION_SECONDS = int(
    os.getenv("JOB_RETENTION_SECONDS", str(max(86400, TIMEOUT * 2)))
)

app = FastAPI()


def _safe_filename(filename: str | None) -> str:
    if not filename:
        raise ValueError("Uploaded file has no filename")
    candidate = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if candidate in {"", ".", ".."} or "\x00" in candidate:
        raise ValueError("Uploaded filename is invalid")
    return candidate


def _decode_option(encoded: str | None) -> dict[str, Any]:
    if not encoded:
        return {}
    try:
        raw = base64.b64decode(encoded, validate=True)
        value = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("option must be Base64-encoded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("decoded option must be a JSON object")
    return value


def _cleanup_expired_workdirs() -> None:
    """Remove UUID work directories that KL never retrieved after retention."""
    root = Path(PATH_WORK)
    root.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - JOB_RETENTION_SECONDS
    for candidate in root.iterdir():
        name = candidate.name
        if (
            len(name) != 32
            or any(character not in "0123456789abcdef" for character in name)
            or candidate.is_symlink()
            or not candidate.is_dir()
        ):
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


@app.post(
    "/parsing",
    name="Request parsing for TEXT & DOCX file",
    description="TEXT, DOCX 파일 파싱을 요청한다.",
    deprecated=False,
)
async def parsing_text_docx_to_json(
    background_tasks: BackgroundTasks,
    src_file: UploadFile = File(...),
    option: str | None = Form(None),
):
    work_dir = ""
    try:
        _cleanup_expired_workdirs()
        options = _decode_option(option)
        base_filename = _safe_filename(src_file.filename)
        request_uuid = uuid.uuid4().hex
        work_dir = os.path.join(PATH_WORK, request_uuid)
        img_dir = os.path.join(work_dir, "image")
        os.makedirs(img_dir, exist_ok=False)

        file_fullpath = os.path.join(work_dir, base_filename)
        with open(file_fullpath, "wb") as file_object:
            while block := await src_file.read(1024 * 1024):
                file_object.write(block)
        if os.path.getsize(file_fullpath) == 0:
            raise ValueError("Uploaded file is empty")

        write_parse_status(work_dir, "PARSING")
        background_tasks.add_task(
            run_method_in_subprocess,
            TIMEOUT,
            work_dir,
            img_dir,
            file_fullpath,
            options,
        )

        result_form = {
            "result": "OK",
            "body": {"uuid": request_uuid, "timeout": TIMEOUT},
        }
        return JSONResponse(status_code=202, content=jsonable_encoder(result_form))
    except Exception as exc:
        print(traceback.format_exc())
        print(f"Exception in parsing {exc.__class__.__name__} {exc}")
        if work_dir and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        result_form = {"message": f"Exception : {exc.__class__.__name__} {exc}"}
        return JSONResponse(status_code=500, content=jsonable_encoder(result_form))
    finally:
        await src_file.close()


@app.get(
    "/parsing/result/{uuid}",
    name="Return the parsing results",
    description="파싱된 결과 조회하여 반환한다.",
    deprecated=False,
)
async def parsing_text_docx_to_json_result(uuid: str):
    work_dir = os.path.join(PATH_WORK, uuid)
    try:
        if not os.path.exists(work_dir):
            return JSONResponse(
                status_code=500,
                content=jsonable_encoder({"message": "Requested url does not exist."}),
            )

        parse_status, parse_message = get_parse_status(work_dir)
        if parse_status == "PARSING":
            return JSONResponse(status_code=200, content={"status": "PARSING"})

        if parse_status == "ERROR":
            result_form = {"status": "ERROR", "message": parse_message}
            shutil.rmtree(work_dir, ignore_errors=True)
            return JSONResponse(status_code=200, content=jsonable_encoder(result_form))

        if parse_status != "DONE":
            shutil.rmtree(work_dir, ignore_errors=True)
            return JSONResponse(
                status_code=500,
                content=jsonable_encoder({"message": parse_message}),
            )

        try:
            zip_bytes = build_result_zip(work_dir)
        except Exception as exc:
            result_form = {
                "status": "ERROR",
                "message": f"Invalid result artifacts: {exc}",
            }
            shutil.rmtree(work_dir, ignore_errors=True)
            return JSONResponse(status_code=200, content=jsonable_encoder(result_form))

        # The supplied example removes the work directory after materializing the ZIP.
        shutil.rmtree(work_dir, ignore_errors=True)
        zip_io = io.BytesIO(zip_bytes)
        return StreamingResponse(
            iter([zip_io.getvalue()]),
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": "attachment; filename=kl-core-s2-output.zip"},
        )
    except Exception as exc:
        print("Exception occurred: %s", traceback.format_exc())
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        result_form = {"message": f"Exception : {str(exc)}"}
        return JSONResponse(status_code=500, content=jsonable_encoder(result_form))


def run_method_in_subprocess(timeout: int, *args: Any) -> None:
    """Run parse in an isolated process without persisting option or putting it in argv."""
    work_dir, img_dir, file_path, options = args
    command = [
        sys.executable,
        "-m",
        "service.parsing_service",
        "--work-dir",
        str(work_dir),
        "--img-dir",
        str(img_dir),
        "--file-path",
        str(file_path),
        "--option-stdin",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent,
            input=json.dumps(options, ensure_ascii=False, separators=(",", ":")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(timeout) + 10,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[-2000:]
            write_parse_status(
                work_dir,
                "ERROR",
                f"Parser process exited with code {completed.returncode}: {stderr}",
            )
    except subprocess.TimeoutExpired:
        write_parse_status(work_dir, "ERROR", f"Parser timed out after {timeout} seconds")
    except Exception as exc:
        traceback.print_exc()
        write_parse_status(work_dir, "ERROR", f"Failed to run parser process: {exc}")


@app.get("/health")
async def health():
    return {"status": "OK"}
