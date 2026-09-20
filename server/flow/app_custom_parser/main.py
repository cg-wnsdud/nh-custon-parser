import os
import io
import shutil
import zipfile
import uuid
import subprocess
import sys
import traceback

from fastapi import FastAPI
from fastapi import UploadFile
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder

from service.parsing_service import get_parse_status, write_parse_status


TIMEOUT = os.getenv("TIMEOUT", 600)
PATH_WORK = os.getenv("PATH_TEMP", "./temp")

app = FastAPI()


@app.post("/parsing",
          name="Request parsing for TEXT & DOCX file",
          description="TEXT, DOCX 파일 파싱을 요청한다.",
          deprecated=False)
async def parsing_text_docx_to_json(src_file: UploadFile,
                                    background_tasks: BackgroundTasks,
                                    option: str = None):
    try:

        # ==============================================================
        # OPTIONAL: USER META 활용해야 한다면
        # ==============================================================
        # option_dec = base64.decodebytes(option)
        # options = json.loads(option_dec.decode("utf-8"))
        # doc_data = options.get("doc_data", {}) 
        #
        # {
        #     "doc_id": "doc_id",
        #     "title": "title",
        #     "category1": "category1",
        #     "category2": "category2",
        #     "category3": "category3",
        #     "category4": "category4",
        #     "lang_cd": "lang_cd",
        #     "origin_doc_id": "origin_doc_id",
        #     "origin_url": "origin_url",
        #     "origin_doc_auth": "origin_doc_auth",
        #     "origin_sys_nm": "origin_sys_nm",
        #     "doc_reg_date": "doc_reg_date",
        #     "reg_user_id": "reg_user_id",
        #     "reg_user_nm": "reg_user_nm",
        #     "doc_attr1": "doc_attr1",
        #     "doc_attr2": "doc_attr2",
        #     "doc_attr3": "doc_attr3",
        #     "doc_attr4": "doc_attr4",
        #     "doc_attr5": "doc_attr5",
        #     "category_path": "category_path"
        # }

        options = {}
        # ==============================================================
        # 입력값 처리 
        # ==============================================================
        # 파일명
        base_filename = src_file.filename

        # 고유 ID 생성 : 결과 조회 사용 Key 역할
        _uuid = (uuid.uuid4()).hex

        # 작업 디렉터리는 Base Top Dir + uuid 로 ...
        work_dir = os.path.join(PATH_WORK, _uuid)             # 작업 디렉터리
        img_dir = os.path.join(PATH_WORK, _uuid, "image")     # 이미지 디렉터리
        os.makedirs(img_dir, exist_ok=True)                   # 디렉터리 생성

        # 전달받은 원본 파일 저장
        file_fullpath = os.path.join(work_dir, base_filename)
        with open(file_fullpath, "wb") as file_object:
            file_object.write(src_file.file.read())

        write_parse_status(work_dir, "PARSING") # 파서 상태 설정

        # ==============================================================
        # 백그라운드에서 파싱처리 
        # ==============================================================
        background_tasks.add_task(run_method_in_subprocess, TIMEOUT, work_dir, img_dir, file_fullpath, options)

        # ==============================================================
        # 응답처리
        # ==============================================================
        # 파싱 요청에 대한 기본 정상 응답 코드는 반드시 202로 해야 하고, result_form 형식도 샘플과 동일하게 구성해야 함.
        # 리턴 body 에 고유한 uuid 와 결과 수신 timeout 값을 반드시 전달해야 함
        status_code = 202
        result_form = {
            'result': "OK",
            'body': {
                'uuid': _uuid,
                'timeout': TIMEOUT,
            }
        }

        # 파싱 요청 응답은 파싱 진행과 별도로 바로 넘김다.
        ret = JSONResponse(status_code=status_code, content=jsonable_encoder(result_form))
        return ret

    except Exception as e:
        print(traceback.format_exc())
        print(f"Exception in parsing {e.__class__.__name__} {e}")

        # 예외 발생 시, 작업 디렉터리 삭제
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)

        result_form = {"message": f"Exception : {e.__class__.__name__} {e}"}
        ret = JSONResponse(status_code=500, content=jsonable_encoder(result_form))
        return ret


@app.get("/parsing/result/{uuid}",
         name="Return the parsing results",
         description="파싱된 결과 조회하여 반환한다.",
         deprecated=False)
async def parsing_text_docx_to_json(uuid):
    try:
        work_dir = os.path.join(PATH_WORK, uuid)  # 작업 디렉터리
        img_dir = os.path.join(work_dir, "image")    # 이미지 디렉터리

        if os.path.exists(work_dir):
            _parse_status, _parse_msg = get_parse_status(work_dir)
            # 파싱 상태가 "DONE" 이면 파싱이 성공적으로 완료된 상태임.
            # 파싱 결과 파일들을 zip 으로 압축하여 리턴한다.
            if _parse_status == "DONE":
                status_code = 200
                zip_with_filenames = [] # ZIP 파일에 압축될 파일 리스트
                zip_subdir = ""

                # 작업 디렉터리 검색하여 xxx_hrc.json, xxx_hrc_jsonl 파일이 있는지 체크
                # 원본 파일명에 맟추어 결과 파일명을 만들기 위해서...
                items = os.listdir(work_dir)
                for item in items:
                    if os.path.isfile(os.path.join(work_dir, item)):
                        if str(item).endswith("_hrc.jsonl"):
                            s2_text_file = os.path.join(work_dir, str(item))  # 파싱 결과 텍스트 파일
                            img_zip_file = s2_text_file.replace("_hrc.jsonl", "_img.zip") # 이미지 압축 파일명
                            zip_with_filenames.append(s2_text_file) # ZIP 압축 파일 리스트에 추가
                        if str(item).endswith("_hrc.json"):
                            s2_info_file = os.path.join(work_dir, str(item))  # 파싱 결과 INFO 파일
                            zip_with_filenames.append(s2_info_file) # ZIP 압축 파일 리스트에 추가
                        if str(item).endswith("doc_data.json"):
                            doc_data_file = os.path.join(work_dir, str(item))  # Doc Data 변경 파일
                            zip_with_filenames.append(doc_data_file) # ZIP 압축 파일 리스트에 추가

                # image 디렉터리 검색하여 파일이 있으면 압축한다.
                # 모든 zip 파일은 경로 없이 파일들만 압축한다.
                items = os.listdir(img_dir)

                with zipfile.ZipFile(img_zip_file, mode='w', compression=zipfile.ZIP_DEFLATED) as img_zip:
                    for item in items:
                        if os.path.isfile(os.path.join(img_dir, item)):
                            img_file = os.path.join(img_dir, item)

                            fname = os.path.split(img_file)[1]
                            zip_path = os.path.join(zip_subdir, fname)
                            img_zip.write(img_file, zip_path)

                if os.path.exists(img_zip_file):
                    zip_with_filenames.append(img_zip_file) # ZIP 압축 파일 리스트에 추가

                # 결과 ZIP 파일을 압축한다.
                zip_io = io.BytesIO()
                with zipfile.ZipFile(zip_io, mode='w', compression=zipfile.ZIP_DEFLATED) as temp_zip:
                    for fpath in zip_with_filenames:
                        fname = os.path.split(fpath)[1]
                        zip_path = os.path.join(zip_subdir, fname)
                        temp_zip.write(fpath, zip_path)

                # ZIP 파일 압축이 완료되면 작업 디렉터리 삭제한다.
                if os.path.exists(work_dir):
                    print(f"Work directory {work_dir} deleted after parsing done")
                    shutil.rmtree(work_dir, ignore_errors=True)

                # 결과 ZIP 파일 리턴
                return StreamingResponse(
                    iter([zip_io.getvalue()]),
                    media_type="application/x-zip-compressed",
                    headers={"Content-Disposition": f"attachment; filename=kl-core-s2-output.zip"}
                )
            elif _parse_status == "PARSING":  # 파싱 진행 중 상태
                status_code = 200
                result_form = {"status": "PARSING"}
            else:
                status_code = 500
                result_form = {"message": _parse_msg}

                # 작업 디렉터리 삭제한다.
                if os.path.exists(work_dir):
                    print(f"Work directory {work_dir} deleted because parsing status is {_parse_msg}")
                    shutil.rmtree(work_dir, ignore_errors=True)
        else:
            status_code = 500
            result_form = {"message": "Requested url does not exist."}

        ret = JSONResponse(status_code=status_code, content=jsonable_encoder(result_form))
        return ret

    except Exception as e:
        print("Exception occurred: %s", traceback.format_exc())

        # 예외 발생 시, 작업 디렉터리 삭제
        if os.path.exists(work_dir):
            print(f"Work directory {work_dir} deleted because exception occurred.")
            shutil.rmtree(work_dir, ignore_errors=True)

        result_form = {"message": f"Exception : {str(e)}"}
        ret = JSONResponse(status_code=500, content=jsonable_encoder(result_form))
        return ret


def run_method_in_subprocess(timeout, *args):
    python_executable = sys.executable
    command = [python_executable, "-c", f"from service.parsing_service import parse; parse({','.join(map(repr, args))})"]

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        timeout2 = timeout + 10
        outs, errs = proc.communicate(timeout=timeout2)
        print(f"{outs}")
        print(f"{errs}")
    except subprocess.TimeoutExpired:
        # timeout 시간이 지나면 프로세스를 종료하고 작업 디렉터리 삭제
        work_dir = args[0]
        proc.kill()
        print(f"Process killed due to timeout")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"Work directory {work_dir} deleted because timeout occurred.")
    except subprocess.CalledProcessError as e:
        print(f"Command failed (Exit Code: {e.returncode})")
        print(e.stdout)
        print(e.stderr)
    except Exception as e:
        traceback.print_exc()


@app.get("/health")
async def health():
    return {"status": "OK"}
