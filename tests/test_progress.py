import os
import tempfile

import pandas as pd
import pytest

from src.progress import (
    get_next_game,
    init_progress_if_needed,
    load_progress,
    update_game,
)


@pytest.fixture()
def price_list_csv(tmp_path):
    """Minimal price list CSV with BOM and comma-separated Set Price."""
    content = (
        '﻿"Game","# Owned","# Unique","# Cards","Badge Lvl","Set Price","Price Diff",'
        '"Card Avg","Booster Avg","Booster %","Emote Avg","BG Avg","Avg Qty","Discount","Added","AppId"\n'
        '"Game C","0","0","5","0","3.00","3.00","0.60","1.00","-50.0","0.50","0.50","100","1.00","2020-01-01","300"\n'
        '"Game A","0","0","4","0","1.00","1.00","0.25","0.80","-100.0","0.40","0.40","200","0.90","2020-01-01","100"\n'
        '"Game B","0","0","6","0","2.00","2.00","0.40","0.90","-80.0","0.45","0.45","150","0.95","2020-01-01","200"\n'
    )
    p = tmp_path / 'STC_set_data.csv'
    p.write_text(content, encoding='utf-8')
    return str(p)


@pytest.fixture()
def progress_csv(tmp_path):
    return str(tmp_path / 'progress.csv')


class TestInitProgressIfNeeded:
    def test_creates_file_when_missing(self, price_list_csv, progress_csv):
        init_progress_if_needed(price_list_csv, progress_csv)
        assert os.path.exists(progress_csv)

    def test_columns_correct(self, price_list_csv, progress_csv):
        init_progress_if_needed(price_list_csv, progress_csv)
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert list(df.columns) == ['appid', 'game_name', 'status', 'bought_count',
                                    'total_spent_hkd_cents', 'last_updated', 'last_scan_time']

    def test_all_pending(self, price_list_csv, progress_csv):
        init_progress_if_needed(price_list_csv, progress_csv)
        df = pd.read_csv(progress_csv)
        assert (df['status'] == 'pending').all()

    def test_sorted_by_set_price_ascending(self, price_list_csv, progress_csv):
        init_progress_if_needed(price_list_csv, progress_csv)
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert df['appid'].tolist() == ['100', '200', '300']

    def test_idempotent_does_not_overwrite(self, price_list_csv, progress_csv):
        init_progress_if_needed(price_list_csv, progress_csv)
        df_first = pd.read_csv(progress_csv)
        # Manually modify the file
        df_first.at[0, 'status'] = 'done'
        df_first.to_csv(progress_csv, index=False)
        # Second call should not overwrite
        init_progress_if_needed(price_list_csv, progress_csv)
        df_second = pd.read_csv(progress_csv)
        assert df_second.at[0, 'status'] == 'done'


class TestGetNextGame:
    def _make_df(self, rows):
        return pd.DataFrame(rows, columns=['appid', 'game_name', 'status',
                                           'bought_count', 'total_spent_hkd_cents', 'last_updated'])

    def test_returns_first_pending(self):
        df = self._make_df([
            ['100', 'A', 'pending', 0, 0, ''],
            ['200', 'B', 'pending', 0, 0, ''],
        ])
        row = get_next_game(df, set())
        assert row['appid'] == '100'

    def test_returns_in_progress(self):
        df = self._make_df([
            ['100', 'A', 'done', 5, 100, '2024-01-01'],
            ['200', 'B', 'in_progress', 2, 40, '2024-01-01'],
        ])
        row = get_next_game(df, set())
        assert row['appid'] == '200'

    def test_skips_visited(self):
        df = self._make_df([
            ['100', 'A', 'pending', 0, 0, ''],
            ['200', 'B', 'pending', 0, 0, ''],
        ])
        row = get_next_game(df, {'100'})
        assert row['appid'] == '200'

    def test_skips_done_and_skipped(self):
        df = self._make_df([
            ['100', 'A', 'done', 5, 100, '2024-01-01'],
            ['200', 'B', 'skipped', 0, 0, '2024-01-01'],
        ])
        assert get_next_game(df, set()) is None

    def test_returns_none_when_all_visited(self):
        df = self._make_df([
            ['100', 'A', 'pending', 0, 0, ''],
        ])
        assert get_next_game(df, {'100'}) is None

    def test_returns_none_on_empty_df(self):
        df = self._make_df([])
        assert get_next_game(df, set()) is None


class TestUpdateGame:
    def _write_progress(self, path, rows):
        df = pd.DataFrame(rows, columns=['appid', 'game_name', 'status',
                                         'bought_count', 'total_spent_hkd_cents', 'last_updated'])
        df.to_csv(path, index=False)

    def test_update_status(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'pending', 0, 0, '']])
        update_game(progress_csv, '730', status='in_progress')
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert df.loc[df['appid'] == '730', 'status'].iloc[0] == 'in_progress'

    def test_update_bought_count_delta(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'in_progress', 3, 60, '']])
        update_game(progress_csv, '730', bought_count_delta=2)
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert int(df.loc[df['appid'] == '730', 'bought_count'].iloc[0]) == 5

    def test_update_spent_delta(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'in_progress', 3, 60, '']])
        update_game(progress_csv, '730', spent_delta=40)
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert int(df.loc[df['appid'] == '730', 'total_spent_hkd_cents'].iloc[0]) == 100

    def test_sets_last_updated(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'pending', 0, 0, '']])
        update_game(progress_csv, '730', status='done')
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        ts = df.loc[df['appid'] == '730', 'last_updated'].iloc[0]
        assert ts != ''

    def test_no_op_for_unknown_appid(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'pending', 0, 0, '']])
        update_game(progress_csv, '999', status='done')
        df = pd.read_csv(progress_csv, dtype={'appid': str})
        assert df.loc[df['appid'] == '730', 'status'].iloc[0] == 'pending'

    def test_invalid_status_raises(self, progress_csv):
        self._write_progress(progress_csv, [['730', 'CS2', 'pending', 0, 0, '']])
        with pytest.raises(ValueError):
            update_game(progress_csv, '730', status='invalid_status')


class TestLoadProgressNaNTolerance:
    def test_nan_in_bought_count_coerced_to_zero(self, tmp_path):
        p = tmp_path / 'progress.csv'
        p.write_text('appid,game_name,status,bought_count,total_spent_hkd_cents,last_updated\n'
                     '730,CS2,pending,,0,\n')
        df = load_progress(str(p))
        assert int(df.loc[df['appid'] == '730', 'bought_count'].iloc[0]) == 0

    def test_nan_in_spent_coerced_to_zero(self, tmp_path):
        p = tmp_path / 'progress.csv'
        p.write_text('appid,game_name,status,bought_count,total_spent_hkd_cents,last_updated\n'
                     '730,CS2,pending,0,,\n')
        df = load_progress(str(p))
        assert int(df.loc[df['appid'] == '730', 'total_spent_hkd_cents'].iloc[0]) == 0

    def test_normal_values_unchanged(self, tmp_path):
        p = tmp_path / 'progress.csv'
        p.write_text('appid,game_name,status,bought_count,total_spent_hkd_cents,last_updated\n'
                     '730,CS2,in_progress,5,200,2024-01-01T00:00:00\n')
        df = load_progress(str(p))
        assert int(df.loc[df['appid'] == '730', 'bought_count'].iloc[0]) == 5
        assert int(df.loc[df['appid'] == '730', 'total_spent_hkd_cents'].iloc[0]) == 200
