# app/cfg/logging.py
import sys
import logging
from loguru import logger
from app.cfg.config import AppSettings

app_logger = logger

class LoguruInterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = app_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        app_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logging(settings: AppSettings) -> None:
    app_logger.remove()
    log_level = settings.logging.level.upper()
    is_debug = settings.app.debug

    # 控制台日志
    app_logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<level>{level.icon}</level> "
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=is_debug,
        diagnose=is_debug,
        enqueue=True,
    )

    # 文件日志
    app_logger.add(
        settings.logging.file_path,
        level=log_level,
        rotation=f"{settings.logging.max_bytes} B",
        retention=settings.logging.backup_count,
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        backtrace=is_debug,
        diagnose=is_debug,
        enqueue=True,
    )

    # 拦截标准库 logging
    logging.basicConfig(handlers=[LoguruInterceptHandler()], level=0, force=True)
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = False