import multiprocessing
import os


bind = os.getenv("GUNICORN_BIND", "unix:/opt/roof_tattoo/run/gunicorn.sock")
workers = int(os.getenv("GUNICORN_WORKERS", str((multiprocessing.cpu_count() * 2) + 1)))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))
worker_tmp_dir = "/dev/shm"
# Nginx (www-data) ile aynı gruba socket erişimi
umask = 0o007
# IMPORTANT:
# preload_app=True causes DB pool to initialize in master process and get forked.
# In this project, connection pool is created at import-time, so preload must stay off
# to avoid SSL EOF / bad record mac / closed connection errors in workers.
preload_app = os.getenv("GUNICORN_PRELOAD", "false").strip().lower() == "true"

accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
