import logging

import pytest

from src import logger


def test_file_handler_creates_log_directory_and_writes(tmp_path, monkeypatch):
    log_dir = tmp_path / 'logs'
    monkeypatch.setattr(logger, '_LOG_DIR', str(log_dir))

    handler = logger._make_file_handler('run.log')
    try:
        handler.handle(logging.LogRecord('test', logging.INFO, __file__, 1, 'fixture event', (), None))
        handler.flush()
    finally:
        handler.close()

    assert 'fixture event' in (log_dir / 'run.log').read_text()


def test_file_handler_reports_directory_conflict(tmp_path, monkeypatch):
    conflict = tmp_path / 'logs'
    conflict.write_text('fixture')
    monkeypatch.setattr(logger, '_LOG_DIR', str(conflict))

    with pytest.raises(FileExistsError):
        logger._make_file_handler('run.log')
