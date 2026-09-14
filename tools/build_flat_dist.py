"""Build the Python/WHL-only flat upload bundle for NH Knowledge Lake."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "server" / "flow" / "app_custom_parser"
SERVICE_DIR = APP_DIR / "service"
WHEEL_DIR = ROOT / "server" / "flow" / "whl"
DIST_DIR = ROOT / "dist" / "kl-flat"

SOURCE_FILES = {
    "main.py": APP_DIR / "main.py",
    "gunicorn_config.py": APP_DIR / "gunicorn_config.py",
    "parsing_service.py": SERVICE_DIR / "parsing_service.py",
    "config.py": SERVICE_DIR / "config.py",
    "document_model.py": SERVICE_DIR / "document_model.py",
    "etl_adapter.py": SERVICE_DIR / "etl_adapter.py",
    "etl_client.py": SERVICE_DIR / "etl_client.py",
    "hrc_exporter.py": SERVICE_DIR / "hrc_exporter.py",
    "result_contract.py": SERVICE_DIR / "result_contract.py",
}

IMPORT_REPLACEMENTS = {
    "from service.parsing_service import": "from parsing_service import",
    "from .config import": "from config import",
    "from .document_model import": "from document_model import",
    "from .etl_adapter import": "from etl_adapter import",
    "from .etl_client import": "from etl_client import",
    "from .hrc_exporter import": "from hrc_exporter import",
    "from .result_contract import": "from result_contract import",
}


def flatten_imports(source: str) -> str:
    for package_import, flat_import in IMPORT_REPLACEMENTS.items():
        source = source.replace(package_import, flat_import)
    return source


def build() -> None:
    wheel_files = sorted(WHEEL_DIR.glob("*.whl"))
    if not wheel_files:
        raise RuntimeError(f"No wheel files found in {WHEEL_DIR}")

    expected_names = set(SOURCE_FILES) | {path.name for path in wheel_files}
    if DIST_DIR.exists():
        unexpected = sorted(path.name for path in DIST_DIR.iterdir() if path.name not in expected_names)
        if unexpected:
            raise RuntimeError(f"Refusing to remove unexpected dist entries: {unexpected}")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    for target_name, source_path in SOURCE_FILES.items():
        content = flatten_imports(source_path.read_text(encoding="utf-8"))
        (DIST_DIR / target_name).write_text(content, encoding="utf-8", newline="\n")

    for wheel_path in wheel_files:
        shutil.copy2(wheel_path, DIST_DIR / wheel_path.name)

    entries = list(DIST_DIR.iterdir())
    invalid = [path.name for path in entries if path.is_dir() or path.suffix not in {".py", ".whl"}]
    if invalid:
        raise RuntimeError(f"Flat dist contains unsupported entries: {invalid}")


if __name__ == "__main__":
    build()
