"""Build the flat bundle delivered to NH: parse() implementation files only.

The platform entrypoints (main.py, gunicorn_config.py) stay as the supplied
template provides them, so they are deliberately excluded from the bundle.
"""

from __future__ import annotations

import py_compile
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT / "server" / "flow" / "app_custom_parser" / "service"
DIST_DIR = ROOT / "dist"
BUNDLE_NAME = "nh-parser-flat"

EXCLUDED_NAMES = frozenset({"main.py", "gunicorn_config.py", "__init__.py"})
REQUIRED_NAMES = frozenset(
    {
        "parsing_service.py",
        "etl_config.py",
        "etl_client.py",
        "etl_adapter.py",
        "document_model.py",
        "hrc_exporter.py",
        "result_contract.py",
        "README.md",
    }
)


def collect_sources() -> list[Path]:
    """Return the flat file set, rejecting anything the bundle must not carry."""
    sources: list[Path] = []
    for path in sorted(SERVICE_DIR.iterdir()):
        if path.name == "__pycache__":
            continue
        if path.is_dir():
            raise RuntimeError(f"Bundle must stay flat; remove the directory {path}")
        if path.suffix not in {".py", ".md"}:
            raise RuntimeError(f"Unexpected file in the delivery source: {path.name}")
        if path.name in EXCLUDED_NAMES:
            raise RuntimeError(f"{path.name} belongs to the platform template, not the bundle")
        sources.append(path)

    names = {path.name for path in sources}
    if names != REQUIRED_NAMES:
        missing = sorted(REQUIRED_NAMES - names)
        extra = sorted(names - REQUIRED_NAMES)
        raise RuntimeError(f"Unexpected bundle contents (missing={missing}, extra={extra})")
    return sources


def check_flat_imports(sources: list[Path]) -> None:
    """Relative imports cannot resolve once the files are dropped in flat."""
    for path in sources:
        if path.suffix != ".py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.startswith("from .") or line.startswith("import ."):
                raise RuntimeError(f"{path.name}:{number} uses a relative import: {line.strip()}")


def build(dest: Path | None = None) -> Path:
    sources = collect_sources()
    check_flat_imports(sources)

    target = Path(dest) if dest is not None else DIST_DIR / BUNDLE_NAME
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for path in sources:
        shutil.copy2(path, target / path.name)
        if path.suffix == ".py":
            py_compile.compile(str(target / path.name), doraise=True, cfile=str(target / "__check__"))
    (target / "__check__").unlink(missing_ok=True)
    return target


def build_archive() -> Path:
    target = build()
    archive_path = target.parent / f"{BUNDLE_NAME}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(target.iterdir()):
            archive.write(path, arcname=f"{BUNDLE_NAME}/{path.name}")
    return archive_path


if __name__ == "__main__":
    created = build_archive()
    print(f"bundle: {created.parent / BUNDLE_NAME}")
    print(f"archive: {created}")
