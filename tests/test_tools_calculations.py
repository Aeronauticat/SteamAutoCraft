from unittest.mock import patch

import pytest

from tools import badge_cost, exp_cal, level_cal


def test_badge_cost_requires_every_card_price():
    with patch.object(badge_cost, 'search_cards', return_value=['10-Card A', '10-Card B']):
        with patch.object(badge_cost, 'get_card_avg_price', side_effect=lambda _session, name, *_: 0.5 if name.endswith('A') else 0.0):
            row, errors, limited = badge_cost.query_game(None, '10', 'Example', 2, 1, 0, 1)

    assert row['badge_cost_hkd'] == ''
    assert 'incomplete card data' in row['note']
    assert errors == 0
    assert limited == 0
    assert any(pattern in row['note'] for pattern in badge_cost.RETRY_NOTE_PATTERNS)


def test_badge_cost_reports_complete_set():
    with patch.object(badge_cost, 'search_cards', return_value=['10-Card A', '10-Card B']):
        with patch.object(badge_cost, 'get_card_avg_price', side_effect=lambda _session, name, *_: 0.4 if name.endswith('A') else 0.6):
            row, _, _ = badge_cost.query_game(None, '10', 'Example', 2, 1, 0, 1)

    assert row['badge_cost_hkd'] == 1.0
    assert row['cards_found'] == 2


def test_badge_cost_requires_all_card_types():
    with patch.object(badge_cost, 'search_cards', return_value=['10-Card A']):
        with patch.object(badge_cost, 'get_card_avg_price', return_value=0.5):
            row, _, _ = badge_cost.query_game(None, '10', 'Example', 2, 1, 0, 1)

    assert row['badge_cost_hkd'] == ''
    assert 'incomplete card data' in row['note']


def test_badge_cost_header_only_example_runs_without_queries(tmp_path, monkeypatch):
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / 'data' / 'steamcardexchange.example.csv'
    output = tmp_path / 'badge_cost.csv'
    config = tmp_path / 'config.yaml'
    config.write_text('max_query_retries: 1\n')
    secrets = tmp_path / 'secrets.yaml'
    secrets.write_text('steam_login_secure: "TEST_COOKIE"\nsessionid: "TEST_SESSION"\n')
    monkeypatch.setattr(badge_cost, 'PRICE_LIST_PATH', str(sample))
    monkeypatch.setattr(badge_cost, 'OUTPUT_PATH', str(output))
    monkeypatch.setattr(badge_cost, 'CONFIG_PATH', str(config))
    monkeypatch.setattr(badge_cost, 'SECRETS_PATH', str(secrets))
    monkeypatch.setattr(badge_cost.sys, 'argv', ['badge_cost', '--interval', '0', '--workers', '1'])
    with patch.object(badge_cost, 'query_game') as query_game:
        badge_cost.main()

    query_game.assert_not_called()
    assert output.read_text().startswith('appid,game_name,num_cards,')


def test_experience_rejects_negative_level():
    with pytest.raises(ValueError):
        exp_cal.calc_exp(-1, 1)
    with pytest.raises(ValueError):
        exp_cal.calc_target_level(-1, 0)
    assert exp_cal.calc_target_level(0, 1)['target_level'] == 1


def test_level_cal_respects_badge_cap_and_unknown_card_count(tmp_path, monkeypatch, capsys):
    price_list = tmp_path / 'games.csv'
    price_list.write_text('AppId,Game,# Cards\n10,Example,2\n')
    secrets = tmp_path / 'secrets.yaml'
    secrets.write_text('steamid: "TEST_ID"\napi_key: "TEST_KEY"\n')
    config = tmp_path / 'config.yaml'
    config.write_text('max_query_retries: 1\nrequest_interval_seconds: 0\n')

    monkeypatch.setattr(level_cal, 'PRICE_LIST_PATH', str(price_list))
    monkeypatch.setattr(level_cal, 'SECRETS_PATH', str(secrets))
    monkeypatch.setattr(level_cal, 'CONFIG_PATH', str(config))
    monkeypatch.setattr(level_cal.sys, 'argv', ['level_cal', '0'])
    inventory = {
        '10': {'10-Card A': 3, '10-Card B': 3},
        '99': {'99-Card A': 3},
    }
    with patch.object(level_cal, 'build_session', return_value=object()):
        with patch.object(level_cal, 'fetch_badges', return_value={'10': {'level': 4}}):
            with patch.object(level_cal, 'fetch_inventory', return_value=inventory):
                level_cal.main()

    output = capsys.readouterr().out
    assert '可合成徽章总数：1' in output
    assert '可升至等级：1' in output


def test_level_cal_rejects_negative_level_before_network(monkeypatch):
    monkeypatch.setattr(level_cal.sys, 'argv', ['level_cal', '-1'])
    with patch.object(level_cal, 'fetch_inventory') as fetch_inventory:
        with pytest.raises(SystemExit) as exc:
            level_cal.main()
    assert exc.value.code == 1
    fetch_inventory.assert_not_called()
