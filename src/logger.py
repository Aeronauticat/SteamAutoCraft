import logging
import os
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')


def _make_file_handler(filename: str) -> TimedRotatingFileHandler:
    os.makedirs(_LOG_DIR, exist_ok=True)
    path = os.path.join(_LOG_DIR, filename)
    handler = TimedRotatingFileHandler(path, when='midnight', backupCount=30, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    return handler


def setup_loggers():
    """Initialize and return (run_logger, business_logger, error_logger)."""
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

    run_log = logging.getLogger('autobuy.run')
    if not run_log.handlers:
        run_log.setLevel(logging.INFO)
        run_log.addHandler(_make_file_handler('run.log'))
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        run_log.addHandler(ch)

    biz_log = logging.getLogger('autobuy.business')
    if not biz_log.handlers:
        biz_log.setLevel(logging.INFO)
        biz_log.addHandler(_make_file_handler('business.log'))
        ch2 = logging.StreamHandler()
        ch2.setFormatter(fmt)
        biz_log.addHandler(ch2)

    err_log = logging.getLogger('autobuy.error')
    if not err_log.handlers:
        err_log.setLevel(logging.ERROR)
        err_log.addHandler(_make_file_handler('error.log'))
        ch3 = logging.StreamHandler()
        ch3.setFormatter(fmt)
        err_log.addHandler(ch3)

    return run_log, biz_log, err_log
