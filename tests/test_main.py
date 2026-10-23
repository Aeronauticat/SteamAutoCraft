from unittest.mock import MagicMock, patch

import pandas as pd

import main as autobuy


def test_marginal_set_cost_excludes_owned_cards_and_uses_depth():
    cards = ['10-Card A', '10-Card B']
    inventory = {'10-Card A': 1}
    graphs = {
        '10-Card A': [[0.40, 1]],
        '10-Card B': [[0.50, 1], [0.60, 2]],
    }

    assert autobuy._cost_of_kth_set_cents(1, cards, inventory, graphs) == (51, True)
    assert autobuy._cost_of_kth_set_cents(2, cards, inventory, graphs) == (102, True)
    assert autobuy._cost_of_kth_set_cents(3, cards, inventory, graphs) == (0, False)


def test_wallet_balance_is_read_from_market_response():
    client = MagicMock()
    client._session.get.return_value.text = 'var g_rgWalletInfo = {"wallet_balance": 123};'

    assert autobuy.get_wallet_cents(client) == 123
    client._session.get.assert_called_once_with('https://steamcommunity.com/market', timeout=15)


def test_main_skips_empty_market_without_placing_orders(tmp_path, monkeypatch):
    price_list = tmp_path / 'games.csv'
    price_list.write_text('AppId,Game,# Cards\n10,Example,2\n')
    progress = tmp_path / 'progress.csv'
    user_info = tmp_path / 'user_info.json'

    monkeypatch.setattr(autobuy, 'PRICE_LIST_PATH', str(price_list))
    monkeypatch.setattr(autobuy, 'PROGRESS_PATH', str(progress))
    monkeypatch.setattr(autobuy, 'USER_INFO_PATH', str(user_info))
    monkeypatch.setattr(autobuy, 'LOCKFILE_PATH', str(tmp_path / 'autobuy.lock'))

    config = {
        'single_game_limit_hkd_cents': 500,
        'run_total_limit_hkd_cents': 2000,
        'run_game_limit': 1,
        'max_query_retries': 1,
        'request_interval_seconds': 0,
        'order_interval_seconds': 0,
    }
    secrets = {
        'steamid': 'TEST_ID',
        'steam_login_secure': 'TEST_COOKIE',
        'sessionid': 'TEST_SESSION',
        'api_key': 'TEST_KEY',
    }
    client = MagicMock()
    client.username = None
    client._session.get.return_value.text = 'g_steamID'

    with patch.object(autobuy, 'load_config', return_value=config):
        with patch.object(autobuy, 'load_secrets', return_value=secrets):
            with patch.object(autobuy, 'SteamClient', return_value=client):
                with patch.object(autobuy, 'setup_loggers', return_value=(MagicMock(), MagicMock(), MagicMock())):
                    with patch.object(autobuy, 'fetch_badges', return_value={}):
                        with patch.object(autobuy, 'fetch_inventory', return_value={}):
                            with patch.object(autobuy, 'search_cards', return_value=[]):
                                with patch.object(autobuy, 'place_buy_order') as place_order:
                                    autobuy.main()

    place_order.assert_not_called()
    assert pd.read_csv(progress).loc[0, 'status'] == 'skipped'
    assert user_info.is_file()
