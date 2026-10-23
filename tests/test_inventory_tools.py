import csv
from unittest.mock import MagicMock, patch

import pandas as pd

from tools import card_grind_prep, grind_scan


def test_scan_paginates_and_pairs_assets_with_descriptions():
    session = MagicMock()
    first = MagicMock()
    first.json.return_value = {
        'success': 1,
        'more_items': 1,
        'last_assetid': '2',
        'assets': [{'assetid': '1', 'classid': '11', 'instanceid': '0'}],
        'descriptions': [{'classid': '11', 'instanceid': '0', 'name': 'Example A'}],
    }
    second = MagicMock()
    second.json.return_value = {
        'success': 1,
        'more_items': 0,
        'assets': [{'assetid': '2', 'classid': '22', 'instanceid': '0'}],
        'descriptions': [{'classid': '22', 'instanceid': '0', 'name': 'Example B'}],
    }
    session.get.side_effect = [first, second]

    with patch.object(grind_scan.time, 'sleep'):
        pairs = grind_scan.fetch_full_inventory(session, 'TEST_ID', 0)

    assert [asset['assetid'] for asset, _ in pairs] == ['1', '2']
    assert session.get.call_args_list[1].kwargs['params']['start_assetid'] == '2'


def test_grind_prep_keeps_only_normal_cards_from_completed_badges(tmp_path, monkeypatch):
    inventory = tmp_path / 'inventory.csv'
    output = tmp_path / 'grind_list.csv'
    pd.DataFrame([
        {'assetid': '1', 'item_type_name': 'Trading Card', 'border_color': '0', 'game_appid': '10'},
        {'assetid': '2', 'item_type_name': 'Trading Card', 'border_color': '1', 'game_appid': '10'},
        {'assetid': '3', 'item_type_name': 'Trading Card', 'border_color': '0', 'game_appid': '20'},
        {'assetid': '4', 'item_type_name': 'Emoticon', 'border_color': '0', 'game_appid': '10'},
    ]).to_csv(inventory, index=False)
    secrets = tmp_path / 'secrets.yaml'
    secrets.write_text('api_key: "TEST_KEY"\nsteamid: "TEST_ID"\n')
    config = tmp_path / 'config.yaml'
    config.write_text('max_query_retries: 1\n')

    monkeypatch.setattr(card_grind_prep, 'SECRETS_PATH', str(secrets))
    monkeypatch.setattr(card_grind_prep, 'CONFIG_PATH', str(config))
    monkeypatch.setattr(card_grind_prep, 'DEFAULT_OUT', str(output))
    monkeypatch.setattr(card_grind_prep.sys, 'argv', ['card_grind_prep', '--input', str(inventory)])
    with patch.object(card_grind_prep, 'build_session', return_value=object()):
        with patch.object(card_grind_prep, 'fetch_badges', return_value={'10': {'level': 5}, '20': {'level': 4}}):
            card_grind_prep.main()

    with output.open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert [row['assetid'] for row in rows] == ['1']
