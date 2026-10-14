from unittest.mock import MagicMock, patch

import pytest

from src.market import get_item_name_id, get_order_histogram, place_buy_order, search_cards


def _mock_session_get(responses):
    session = MagicMock()
    mock_responses = []
    for body in responses:
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = body
        mock_responses.append(r)
    session.get.side_effect = mock_responses
    return session


class TestSearchCards:
    def test_basic_single_page(self):
        body = {
            'results': [
                {'hash_name': '730-Card A'},
                {'hash_name': '730-Card B'},
                {'hash_name': '730-Card C'},
            ]
        }
        session = _mock_session_get([body])
        result = search_cards(session, '730', num_cards=3)
        assert result == ['730-Card A', '730-Card B', '730-Card C']

    def test_stops_when_num_cards_reached(self):
        page1 = {'results': [{'hash_name': f'730-Card {i}'} for i in range(5)]}
        session = _mock_session_get([page1])
        result = search_cards(session, '730', num_cards=5)
        assert len(result) == 5
        assert session.get.call_count == 1

    def test_pagination_fetches_more(self):
        page1 = {'results': [{'hash_name': f'730-Card {i}'} for i in range(3)]}
        page2 = {'results': [{'hash_name': f'730-Card {i}'} for i in range(3, 5)]}
        page3 = {'results': []}
        session = _mock_session_get([page1, page2, page3])
        with patch('src.market.time.sleep'):
            result = search_cards(session, '730', num_cards=10)
        assert len(result) == 5

    def test_deduplicates_hash_names(self):
        page1 = {'results': [{'hash_name': '730-Card A'}, {'hash_name': '730-Card A'}]}
        session = _mock_session_get([page1, {'results': []}])
        with patch('src.market.time.sleep'):
            result = search_cards(session, '730', num_cards=10)
        assert result.count('730-Card A') == 1

    def test_empty_results(self):
        session = _mock_session_get([{'results': []}])
        result = search_cards(session, '730', num_cards=5)
        assert result == []

    def test_stops_when_count_stable(self):
        page1 = {'results': [{'hash_name': '730-Card A'}]}
        page2 = {'results': []}
        session = _mock_session_get([page1, page2])
        with patch('src.market.time.sleep'):
            result = search_cards(session, '730', num_cards=10)
        assert result == ['730-Card A']


class TestGetItemNameId:
    def _mock_html_session(self, html):
        session = MagicMock()
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.text = html
        session.get.return_value = r
        return session

    def test_extracts_nameid(self):
        html = 'some html Market_LoadOrderSpread( 175875560 ); more html'
        session = self._mock_html_session(html)
        result = get_item_name_id(session, '312660-Karl Fairburne')
        assert result == 175875560

    def test_extracts_nameid_no_spaces(self):
        html = 'Market_LoadOrderSpread(99999);'
        session = self._mock_html_session(html)
        result = get_item_name_id(session, '312660-Card')
        assert result == 99999

    def test_raises_if_not_found(self):
        html = '<html>no nameid here</html>'
        session = self._mock_html_session(html)
        with pytest.raises(ValueError, match='item_nameid not found'):
            get_item_name_id(session, '312660-Card')

    def test_retries_on_network_error(self):
        html = 'Market_LoadOrderSpread( 123 );'
        session = MagicMock()
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception('network error')
        ok_resp = MagicMock()
        ok_resp.raise_for_status.return_value = None
        ok_resp.text = html
        session.get.side_effect = [fail_resp, ok_resp]
        with patch('src.market.time.sleep'):
            result = get_item_name_id(session, '312660-Card', max_retries=2)
        assert result == 123


class TestGetOrderHistogram:
    def _mock(self, body):
        return _mock_session_get([body])

    def test_basic(self):
        body = {
            'success': 1,
            'lowest_sell_order': '41',
            'sell_order_graph': [[0.41, 11, '11 份']],
        }
        session = self._mock(body)
        our_price, available, graph = get_order_histogram(session, '312660-Karl Fairburne', 175875560)
        assert our_price == 42          # 41 + 1
        assert available == 11
        assert graph == body['sell_order_graph']

    def test_no_sell_orders(self):
        body = {'success': 1, 'lowest_sell_order': None, 'sell_order_graph': []}
        session = self._mock(body)
        our_price, available, graph = get_order_histogram(session, '312660-Card', 999)
        assert our_price == 0
        assert available == 0
        assert graph == []

    def test_multiple_graph_entries(self):
        body = {
            'success': 1,
            'lowest_sell_order': '40',
            'sell_order_graph': [
                [0.40, 5, '5 份'],
                [0.41, 15, '15 份'],   # cumulative includes 0.40
                [0.50, 50, '50 份'],
            ],
        }
        session = self._mock(body)
        our_price, available, graph = get_order_histogram(
            session, '312660-Card', 999, needed_qty=6)
        assert our_price == 42          # Sixth unit is at 0.41, plus one cent.
        assert available == 50          # Total market depth across all price levels.
        assert graph == body['sell_order_graph']

    def test_total_available_includes_entries_above_our_price(self):
        body = {
            'success': 1,
            'lowest_sell_order': '50',
            'sell_order_graph': [
                [0.50, 8, '8 份'],
                [0.60, 20, '20 份'],
            ],
        }
        session = self._mock(body)
        our_price, available, graph = get_order_histogram(session, '312660-Card', 999)
        assert our_price == 51
        assert available == 20
        assert graph == body['sell_order_graph']


class TestPlaceBuyOrder:
    def _make_client(self, resp_json):
        client = MagicMock()
        client._session.cookies.get.return_value = 'test_sessionid'
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_json
        client._session.post.return_value = mock_resp
        return client

    def test_posts_correct_fields(self):
        client = self._make_client({'success': 1, 'buy_orderid': '123'})
        place_buy_order(client, '312660-Karl Fairburne', price_cents=42, quantity=3)

        call_kwargs = client._session.post.call_args
        data = call_kwargs[1]['data']
        assert data['appid'] == '753'
        assert data['market_hash_name'] == '312660-Karl Fairburne'
        assert data['currency'] == '29'
        assert data['price_total'] == '126'      # 42 * 3
        assert data['quantity'] == '3'
        assert data['tradefee_tax'] == '0'
        assert 'billing_state' in data
        assert 'save_my_address' in data

    def test_posts_to_correct_url(self):
        client = self._make_client({'success': 1, 'buy_orderid': '123'})
        place_buy_order(client, '312660-Karl Fairburne', price_cents=42, quantity=1)
        url = client._session.post.call_args[0][0]
        assert 'createbuyorder' in url

    def test_raises_on_success_not_1_no_confirmation(self):
        from steampy.exceptions import ApiException
        client = self._make_client({'success': 8, 'message': 'access denied'})
        with pytest.raises(ApiException):
            place_buy_order(client, '312660-Card', price_cents=42, quantity=1)

    def test_406_confirmation_flow_succeeds(self):
        """406 + success=22 → block for user input → retry with confirmation_id → success."""
        from unittest.mock import patch

        needs_conf = {
            'success': 22,
            'need_confirmation': True,
            'confirmation': {'confirmation_id': 'CONF123'},
        }
        success_resp = {'success': 1, 'buy_orderid': '999'}

        client = MagicMock()
        client._session.cookies.get.return_value = 'test_sessionid'
        r1, r2 = MagicMock(), MagicMock()
        r1.json.return_value = needs_conf
        r2.json.return_value = success_resp
        client._session.post.side_effect = [r1, r2]

        with patch('builtins.input', return_value=''):
            with patch('builtins.print'):
                result = place_buy_order(client, '312660-Card', price_cents=42, quantity=1)

        assert result == success_resp
        assert client._session.post.call_count == 2
        # Second call must include confirmation_id
        second_data = client._session.post.call_args_list[1][1]['data']
        assert second_data['confirmation'] == 'CONF123'

    def test_406_confirmation_flow_fails_after_confirm(self):
        """User confirms but second request still fails → raises."""
        from steampy.exceptions import ApiException
        from unittest.mock import patch

        needs_conf = {
            'success': 22,
            'need_confirmation': True,
            'confirmation': {'confirmation_id': 'CONF123'},
        }
        client = MagicMock()
        client._session.cookies.get.return_value = 'test_sessionid'
        r1, r2 = MagicMock(), MagicMock()
        r1.json.return_value = needs_conf
        r2.json.return_value = {'success': 2, 'message': 'failed'}
        client._session.post.side_effect = [r1, r2]

        with patch('builtins.input', return_value=''):
            with patch('builtins.print'):
                with pytest.raises(ApiException):
                    place_buy_order(client, '312660-Card', price_cents=42, quantity=1)

    def test_raises_on_network_error(self):
        client = MagicMock()
        client._session.cookies.get.return_value = 'sid'
        client._session.post.side_effect = Exception('network error')
        with pytest.raises(Exception, match='network error'):
            place_buy_order(client, '312660-Card', price_cents=42, quantity=1)

    def test_no_retry_called_once(self):
        client = MagicMock()
        client._session.cookies.get.return_value = 'sid'
        client._session.post.side_effect = Exception('fail')
        with pytest.raises(Exception):
            place_buy_order(client, '312660-Card', price_cents=42, quantity=1)
        assert client._session.post.call_count == 1
