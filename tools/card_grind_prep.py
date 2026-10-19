"""
card_grind_prep.py — 从库存扫描结果中筛选可转宝石的普通卡牌。

筛选规则：
  1. 只保留普通交易卡（item_type_name=Trading Card 且 border_color=0）
  2. 只保留对应游戏徽章已达 5 级的卡牌

输出到 data/grind_list.csv，供 grind_run.py 使用。

用法：
    python3 -m tools.card_grind_prep [--input data/inventory_scan.csv]
"""

import argparse
import os
import sys

import pandas as pd
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.steam_api import fetch_badges

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'secrets.yaml')
CONFIG_PATH  = os.path.join(BASE_DIR, 'config', 'config.yaml')
DEFAULT_IN   = os.path.join(BASE_DIR, 'data', 'inventory_scan.csv')
DEFAULT_OUT  = os.path.join(BASE_DIR, 'data', 'grind_list.csv')

BADGE_LEVEL_MIN = 5


def build_session(secrets: dict) -> requests.Session:
    sess = requests.Session()
    for name, value in {
        'steamLoginSecure': secrets['steam_login_secure'],
        'sessionid':        secrets['sessionid'],
        'steamCountry':     secrets.get('steam_country_cookie', 'HK'),
        'timezoneOffset':   '28800,0',
        'timezoneName':     'Asia%2FShanghai',
    }.items():
        sess.cookies.set(name, value, domain='steamcommunity.com')
    sess.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
        ),
        'Referer': secrets.get('inventory_referer') or f"https://steamcommunity.com/profiles/{secrets['steamid']}/inventory",
        'X-Requested-With': 'XMLHttpRequest',
    })
    return sess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default=DEFAULT_IN)
    args = parser.parse_args()

    with open(SECRETS_PATH) as f:
        secrets = yaml.safe_load(f)
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    max_retries = cfg.get('max_query_retries', 3)

    # ── 步骤1：读库存，筛普通卡 ──
    df = pd.read_csv(args.input, dtype=str).fillna('')
    all_cards = df[df['item_type_name'] == 'Trading Card']
    normal_cards = all_cards[all_cards['border_color'] == '0'].copy()

    foil_count   = (all_cards['border_color'] == '1').sum()
    print(f'Trading Card 总数: {len(all_cards)}（普通: {len(normal_cards)}，稀有/foil: {foil_count}）')

    if normal_cards.empty:
        print('没有普通卡牌，退出。')
        sys.exit(0)

    # ── 步骤2：查询所有游戏徽章等级 ──
    print('正在查询徽章等级...')
    sess = build_session(secrets)
    badges = fetch_badges(sess, secrets['api_key'], secrets['steamid'], max_retries)
    print(f'共获取 {len(badges)} 个游戏徽章')

    # ── 步骤3：按徽章等级过滤 ──
    def badge_level(appid: str) -> int:
        return badges.get(appid, {}).get('level', 0)

    normal_cards['badge_level'] = normal_cards['game_appid'].apply(badge_level)
    qualified = normal_cards[normal_cards['badge_level'] >= BADGE_LEVEL_MIN].copy()
    removed   = normal_cards[normal_cards['badge_level'] <  BADGE_LEVEL_MIN]

    print(f'\n过滤结果：')
    print(f'  保留（徽章 >= {BADGE_LEVEL_MIN} 级）: {len(qualified)} 张')
    print(f'  移除（徽章 <  {BADGE_LEVEL_MIN} 级）: {len(removed)} 张')

    # 打印被移除的游戏（去重），方便核查
    if not removed.empty:
        removed_games = removed[['game_appid', 'badge_level']].drop_duplicates().sort_values('badge_level', ascending=False)
        print(f'\n  移除的游戏（appid → 当前徽章级）：')
        for _, row in removed_games.iterrows():
            print(f'    appid={row["game_appid"]}  badge_level={row["badge_level"]}')

    # ── 写出 ──
    out_cols = [c for c in qualified.columns if c != 'badge_level']
    qualified[out_cols].to_csv(DEFAULT_OUT, index=False)
    print(f'\n已写入 {DEFAULT_OUT}（{len(qualified)} 条）')


if __name__ == '__main__':
    main()
