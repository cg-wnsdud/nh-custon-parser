# Offline wheels

This directory is part of the delivery artifact, not just a package list.

- `python_multipart-0.0.17-py3-none-any.whl` is copied from the supplied NH
  Custom Parser example and installed by `setup-application.sh`.
- FastAPI, Gunicorn and Uvicorn are platform-provided packages in the supplied
  example environment. The setup script checks that they can be imported and
  fails before startup if the target platform image differs.
- `SHA256SUMS` records the exact wheel payload delivered with this source.
- `setup-application.sh` runs `verify_wheels.py` before installing anything.
