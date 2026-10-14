from unittest.mock import MagicMock, call, patch

import pytest

from src.steam_api import fetch_badges, fetch_inventory


def _mock_session_get(responses):
    """Returns a mock session where .get() returns responses in sequence."""
    session = MagicMock()
    mock_responses = []
    for body in responses:
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = body
        mock_responses.append(r)
    session.get.side_effect = mock_responses
    return session


class TestFetchBadges:
    def test_basic(self):
        body = {
            'response': {
                'badges': [
                    {'appid': 730, 'level': 2, 'cards_remaining': 3},
                    {'appid': 280910, 'level': 0, 'cards_remaining': 5},
                ]
            }
        }
        session = _mock_session_get([body])
        result = fetch_badges(session, 'API_KEY', 'TEST_STEAM_ID')
        assert result['730'] == {'level': 2, 'cards_remaining': 3}
        assert result['280910'] == {'level': 0, 'cards_remaining': 5}

    def test_empty_badges_list(self):
        body = {'response': {'badges': []}}
        session = _mock_session_get([body])
        result = fetch_badges(session, 'API_KEY', 'TEST_STEAM_ID')
        assert result == {}

    def test_retry_on_first_failure(self):
        good_body = {'response': {'badges': [{'appid': 730, 'level': 1, 'cards_remaining': 4}]}}
        session = MagicMock()
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception('500')
        good_resp = MagicMock()
        good_resp.raise_for_status.return_value = None
        good_resp.json.return_value = good_body
        session.get.side_effect = [fail_resp, good_resp]

        with patch('src.steam_api.time.sleep'):
            result = fetch_badges(session, 'API_KEY', 'TEST_STEAM_ID', max_retries=2)

        assert result['730']['level'] == 1

    def test_all_retries_fail_raises(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception('timeout')
        session.get.return_value = resp

        with patch('src.steam_api.time.sleep'):
            with pytest.raises(Exception, match='timeout'):
                fetch_badges(session, 'API_KEY', 'TEST_STEAM_ID', max_retries=2)


class TestFetchInventory:
    def _asset(self, classid, instanceid):
        return {'classid': classid, 'instanceid': instanceid, 'appid': '753', 'contextid': '6', 'assetid': '1'}

    def _desc(self, classid, instanceid, hash_name):
        return {'classid': classid, 'instanceid': instanceid, 'market_hash_name': hash_name}

    def test_basic_single_page(self):
        body = {
            'success': 1,
            'more_items': 0,
            'assets': [
                self._asset('111', '222'),
                self._asset('333', '444'),
            ],
            'descriptions': [
                self._desc('111', '222', '730-Card A'),
                self._desc('333', '444', '730-Card B'),
            ],
        }
        session = _mock_session_get([body])
        result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert result['730']['730-Card A'] == 1
        assert result['730']['730-Card B'] == 1

    def test_pagination(self):
        page1 = {
            'success': 1,
            'more_items': 1,
            'last_assetid': '9999',
            'assets': [self._asset('111', '222')],
            'descriptions': [self._desc('111', '222', '730-Card A')],
        }
        page2 = {
            'success': 1,
            'more_items': 0,
            'assets': [self._asset('333', '444')],
            'descriptions': [self._desc('333', '444', '280910-Card X')],
        }
        session = _mock_session_get([page1, page2])
        with patch('src.steam_api.time.sleep'):
            result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert result['730']['730-Card A'] == 1
        assert result['280910']['280910-Card X'] == 1

    def test_duplicate_assets_counted(self):
        body = {
            'success': 1,
            'more_items': 0,
            'assets': [
                self._asset('111', '222'),
                self._asset('111', '222'),
            ],
            'descriptions': [
                self._desc('111', '222', '730-Card A'),
            ],
        }
        session = _mock_session_get([body])
        result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert result['730']['730-Card A'] == 2

    def test_appid_extracted_from_hash_name(self):
        body = {
            'success': 1,
            'more_items': 0,
            'assets': [self._asset('111', '222')],
            'descriptions': [self._desc('111', '222', '12345-Some Long Card Name With Dashes-X')],
        }
        session = _mock_session_get([body])
        result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert '12345' in result

    def test_empty_inventory(self):
        body = {'success': 1, 'more_items': 0, 'assets': [], 'descriptions': []}
        session = _mock_session_get([body])
        result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert result == {}

    def test_failed_response_stops_loop(self):
        body = {'success': 0}
        session = _mock_session_get([body])
        result = fetch_inventory(session, 'TEST_STEAM_ID')
        assert result == {}
