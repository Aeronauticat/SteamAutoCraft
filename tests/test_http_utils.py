from unittest.mock import MagicMock, patch

import pytest

from src.http_utils import get_with_retry


def _mock_session(responses):
    session = MagicMock()
    mock_responses = []
    for body in responses:
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = body
        mock_responses.append(r)
    session.get.side_effect = mock_responses
    return session


class TestGetWithRetry:
    def test_success_on_first_attempt(self):
        session = _mock_session([{'ok': True}])
        result = get_with_retry(session, 'http://example.com', {}, max_retries=3, interval=1)
        assert result == {'ok': True}

    def test_retries_on_failure_then_succeeds(self):
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception('500')
        ok_resp = MagicMock()
        ok_resp.raise_for_status.return_value = None
        ok_resp.json.return_value = {'ok': True}
        session = MagicMock()
        session.get.side_effect = [fail_resp, ok_resp]
        with patch('src.http_utils.time.sleep'):
            result = get_with_retry(session, 'http://x.com', {}, max_retries=2, interval=1)
        assert result == {'ok': True}

    def test_raises_after_all_retries_fail(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception('timeout')
        session.get.return_value = resp
        with patch('src.http_utils.time.sleep'):
            with pytest.raises(Exception, match='timeout'):
                get_with_retry(session, 'http://x.com', {}, max_retries=2, interval=1)
        assert session.get.call_count == 2

    def test_max_retries_zero_raises_value_error(self):
        session = MagicMock()
        with pytest.raises(ValueError, match='max_retries must be >= 1'):
            get_with_retry(session, 'http://x.com', {}, max_retries=0, interval=1)

    def test_no_sleep_on_last_attempt(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception('err')
        session.get.return_value = resp
        with patch('src.http_utils.time.sleep') as mock_sleep:
            with pytest.raises(Exception):
                get_with_retry(session, 'http://x.com', {}, max_retries=2, interval=5)
        assert mock_sleep.call_count == 1
