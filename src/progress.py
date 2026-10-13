import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

PROGRESS_COLS = ['appid', 'game_name', 'status', 'bought_count', 'total_spent_hkd_cents',
                 'last_updated', 'last_scan_time']
VALID_STATUSES = {'pending', 'in_progress', 'done', 'skipped', 'ready_to_craft', 'overpriced'}

SCAN_COOLDOWN_DAYS = 3  # 缺货游戏的重扫间隔


def init_progress_if_needed(price_list_path: str, progress_path: str) -> None:
    """Create progress.csv from price list if it does not exist yet."""
    if os.path.exists(progress_path):
        return

    df = pd.read_csv(price_list_path, encoding='utf-8-sig', dtype={'AppId': str})

    if 'Set Price USD' in df.columns:
        df['_sort_price'] = pd.to_numeric(
            df['Set Price USD'].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False),
            errors='coerce',
        )
    elif 'Set Price' in df.columns:
        df['_sort_price'] = pd.to_numeric(
            df['Set Price'].astype(str).str.replace(',', '', regex=False),
            errors='coerce',
        )
    else:
        df['_sort_price'] = range(len(df))

    df = df.sort_values('_sort_price', na_position='last').reset_index(drop=True)

    progress = pd.DataFrame({
        'appid': df['AppId'],
        'game_name': df['Game'],
        'status': 'pending',
        'bought_count': 0,
        'total_spent_hkd_cents': 0,
        'last_updated': '',
        'last_scan_time': '',
    })

    os.makedirs(os.path.dirname(os.path.abspath(progress_path)), exist_ok=True)
    progress.to_csv(progress_path, index=False)


def load_progress(progress_path: str) -> pd.DataFrame:
    df = pd.read_csv(
        progress_path,
        dtype={'appid': str, 'game_name': str, 'status': str,
               'last_updated': str, 'last_scan_time': str},
    )
    df['bought_count'] = pd.to_numeric(df['bought_count'], errors='coerce').fillna(0).astype(int)
    df['total_spent_hkd_cents'] = pd.to_numeric(df['total_spent_hkd_cents'], errors='coerce').fillna(0).astype(int)
    # 旧数据兼容：如果没有 last_scan_time 列，补空列
    if 'last_scan_time' not in df.columns:
        df['last_scan_time'] = ''
    return df


def _scan_too_recent(last_scan_time_series: pd.Series) -> pd.Series:
    """返回布尔 Series：True 表示该行上次扫描时间在 SCAN_COOLDOWN_DAYS 天内，应跳过。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SCAN_COOLDOWN_DAYS)

    def check(v) -> bool:
        if not v or pd.isna(v) or str(v).strip() == '':
            return False
        try:
            t = datetime.fromisoformat(str(v).strip())
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return t > cutoff
        except Exception:
            return False

    return last_scan_time_series.apply(check)


def get_next_game(progress_df: pd.DataFrame, visited_set: set) -> Optional[pd.Series]:
    """Return the first pending/in_progress row not yet visited this run."""
    scan_recent = _scan_too_recent(progress_df.get('last_scan_time', pd.Series([''] * len(progress_df))))
    mask = (
        progress_df['status'].isin(['pending', 'in_progress'])
        & ~progress_df['appid'].isin(visited_set)
        & ~scan_recent
    )
    candidates = progress_df[mask]
    if candidates.empty:
        return None
    return candidates.iloc[0]


def update_game(
    progress_path: str,
    appid: str,
    status: Optional[str] = None,
    bought_count_delta: int = 0,
    spent_delta: int = 0,
    set_scan_time: bool = False,
) -> None:
    """Read-modify-write a single row in progress.csv."""
    df = load_progress(progress_path)
    idx = df.index[df['appid'] == str(appid)].tolist()
    if not idx:
        return
    i = idx[0]

    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f'Invalid status: {status}')
        df.at[i, 'status'] = status

    if bought_count_delta:
        df.at[i, 'bought_count'] = int(df.at[i, 'bought_count']) + bought_count_delta

    if spent_delta:
        df.at[i, 'total_spent_hkd_cents'] = int(df.at[i, 'total_spent_hkd_cents']) + spent_delta

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    df.at[i, 'last_updated'] = now_str
    if set_scan_time:
        df.at[i, 'last_scan_time'] = now_str

    df.to_csv(progress_path, index=False)
