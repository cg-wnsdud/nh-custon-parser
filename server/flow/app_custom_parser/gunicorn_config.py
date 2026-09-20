# gunicorn_config.py 예시
import dlp
import os


pwd = os.getcwd()
proc_name = os.getenv("FLOW_APP_NAME", "app_flow")
MLDL_PROBE_PORT = os.getenv("MLDL_PROBE_PORT", "9101")

# ==============================================================================    
# Gunicorn Settings: https://docs.gunicorn.org/en/stable/settings.html#settings
#
#     worker_class: The type of workers to use
#     timeout: Workers silent for more than this many seconds are killed and restarted.
#     preload_app: Load application code before the worker processes are forked.
#     max_requests: The maximum number of requests a worker will process before restarting.
#     max_requests_jitter: The maximum jitter to add to the max_requests setting.
#     graceful_timeout: Timeout for graceful workers restart.
# ==============================================================================

worker_class = "uvicorn.workers.UvicornWorker"
timeout = os.getenv("GUNICORN_TIMEOUT", "180")
preload_app = os.getenv("PRELOAD_APP", "false")
max_requests = os.getenv("MAX_REQUESTS", "10000")
max_requests_jitter = os.getenv("MAX_REQUESTS_JITTER", "100")
graceful_timeout = os.getenv("MLDL_INFER_GRACEFUL_TIMEOUT", "30")


# 운영 환경일 때, 변경되는 config
workers = os.getenv("MLDL_INFER_WORKER_COUNT", "2")
log_level = os.getenv("MLDL_LOG_LEVEL", "debug")
logconfig = os.getenv("GUNICORN_LOG_CONF")
bind = "0.0.0.0:" + MLDL_PROBE_PORT


# 운영 환경일 때
if dlp.is_infer_env():
    workers = os.getenv("MLDL_INFER_WORKER_COUNT", "8")
    log_level = os.getenv("MLDL_LOG_LEVEL", "info")

