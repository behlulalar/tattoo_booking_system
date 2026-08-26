"""
Uygulama logu: okunabilir satır, hata kodu, kaynak dosya:satır, dönen + gzip arşiv.

Örnek:
2026-08-26 17:41:02 | ERROR | E-WA-001 | evolution_client.py:401 send_text | WhatsApp mesajı gönderilemedi | target=9053...
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import sys
from logging.handlers import TimedRotatingFileHandler

from error_codes import CODE_HELP, E_UNK_001

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.getenv("LOG_DIR", os.path.join(_BACKEND_DIR, "logs"))
LOG_FILE_PATH = os.path.join(LOG_DIR, "app.log")
LOG_BACKUP_DAYS = int(os.getenv("LOG_BACKUP_DAYS", "90"))

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U00002300-\U000023FF"
    "\U00002100-\U0000214F"
    "\U00002B00-\U00002BFF"
    "\U000025A0-\U000025FF"
    "\U0001F1E0-\U0001F1FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    cleaned = _EMOJI_RE.sub("", text or "")
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _safe_ctx_value(value, max_len=180):
    if value is None:
        return "-"
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = _strip_emoji(text)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


class _ErrorCodeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "error_code") or not record.error_code:
            record.error_code = E_UNK_001 if record.levelno >= logging.ERROR else "-"
        record.msg = _strip_emoji(str(record.msg))
        if record.args:
            try:
                if isinstance(record.args, dict):
                    record.args = {k: _strip_emoji(str(v)) if isinstance(v, str) else v for k, v in record.args.items()}
                else:
                    record.args = tuple(
                        _strip_emoji(a) if isinstance(a, str) else a for a in record.args
                    )
            except Exception:
                pass
        return True


def _backend_origin(exc_info):
    """Traceback icinden bizim backend dosyasinin son cercevesini bul."""
    if not exc_info or not exc_info[2]:
        return None
    tb = exc_info[2]
    last_ours = None
    backend = os.path.abspath(_BACKEND_DIR) + os.sep
    while tb:
        fname = os.path.abspath(tb.tb_frame.f_code.co_filename)
        if fname.startswith(backend) and "site-packages" not in fname:
            last_ours = tb
        tb = tb.tb_next
    if not last_ours:
        return None
    code = last_ours.tb_frame.f_code
    return os.path.basename(code.co_filename), last_ours.tb_lineno, code.co_name


class ReadableFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.error_code = getattr(record, "error_code", "-") or "-"
        origin = _backend_origin(getattr(record, "exc_info", None))
        if origin:
            record.filename, record.lineno, record.funcName = origin
        line = super().format(record)
        return _strip_emoji(line)

    def formatException(self, ei) -> str:
        return super().formatException(ei)


def _gzip_namer(default_name: str) -> str:
    return default_name + ".gz"


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as f_in:
        with gzip.open(dest, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)


def setup_logging(level: int | None = None) -> str:
    """Kök logger'ı dosya + stdout ile kurar. Dönüş: log dosya yolu."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_level = level
    if log_level is None:
        name = (os.getenv("LOG_LEVEL") or "INFO").upper()
        log_level = getattr(logging, name, logging.INFO)

    formatter = ReadableFormatter(
        fmt="%(asctime)s | %(levelname)-5s | %(error_code)-10s | %(filename)s:%(lineno)d %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    code_filter = _ErrorCodeFilter()

    file_handler = TimedRotatingFileHandler(
        LOG_FILE_PATH,
        when="midnight",
        interval=1,
        backupCount=LOG_BACKUP_DAYS,
        encoding="utf-8",
        utc=False,
        delay=True,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.namer = _gzip_namer
    file_handler.rotator = _gzip_rotator
    file_handler.setFormatter(formatter)
    file_handler.addFilter(code_filter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(code_filter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    return LOG_FILE_PATH


def log_error(logger: logging.Logger, code: str, message: str, exc: BaseException | None = None, **ctx) -> None:
    """Hata satırı: kod + net cümle + bağlam. Exception varsa traceback eklenir."""
    bits = [_strip_emoji(message)]
    if ctx:
        bits.append(" ".join(f"{k}={_safe_ctx_value(v)}" for k, v in ctx.items()))
    extra = {"error_code": code}
    # stacklevel=2: dosya:satır ve fonksiyon, log_error değil çağıran yer olsun
    if exc is not None:
        logger.error(" | ".join(bits), extra=extra, exc_info=exc, stacklevel=2)
    else:
        logger.error(" | ".join(bits), extra=extra, stacklevel=2)


def log_warning(logger: logging.Logger, code: str, message: str, **ctx) -> None:
    bits = [_strip_emoji(message)]
    if ctx:
        bits.append(" ".join(f"{k}={_safe_ctx_value(v)}" for k, v in ctx.items()))
    logger.warning(" | ".join(bits), extra={"error_code": code}, stacklevel=2)


def code_hint(code: str) -> str:
    return CODE_HELP.get(code, "")
