"""
level_cal.py — Steam 升级计算器

用法：
    python3 -m tools.level_cal <当前等级>

示例：
    python3 -m tools.level_cal 350

流程：
    1. 查询 Steam 库存中的交易卡片（排除表情、背景、补充包）
    2. 按游戏分组，计算每个游戏可合成的徽章次数
    3. 汇总总徽章数
    4. 根据 exp_cal.calc_target_level 计算可升到的等级
"""

import os
import re
import sys

import pandas as pd
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.steam_api import fetch_badges, fetch_inventory
from tools.exp_cal import calc_target_level

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'secrets.yaml')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.yaml')
PRICE_LIST_PATH = os.path.join(BASE_DIR, 'data', 'STC_set_data_sort.csv')


def is_trading_card(hash_name: str) -> bool:
    """排除表情（:xxx:）、背景（Profile Background）、补充包（Booster Pack）。"""
    parts = hash_name.split('-', 1)
    if len(parts) < 2:
        return False
    name = parts[1]
    if re.match(r'^:.+:$', name.strip()):
        return False
    if '(Profile Background)' in name:
        return False
    if 'Booster Pack' in name:
        return False
    return True


def build_session(secrets: dict) -> requests.Session:
    session = requests.Session()
    for name, value in {
        'steamLoginSecure': secrets['steam_login_secure'],
        'sessionid':        secrets['sessionid'],
        'steamCountry':     secrets.get('steam_country_cookie', 'HK'),
        'timezoneOffset':   '28800,0',
        'timezoneName':     'Asia%2FShanghai',
        'bMarketOptOut':    '1',
    }.items():
        session.cookies.set(name, value, domain='steamcommunity.com')
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'X-Requested-With': 'XMLHttpRequest',
    })
    return session


def main():
    if len(sys.argv) < 2:
        print('用法: python3 -m tools.level_cal <当前等级>')
        sys.exit(1)

    try:
        current_level = int(sys.argv[1])
    except ValueError:
        print('错误：等级必须是整数')
        sys.exit(1)
    if current_level < 0:
        print('错误：等级不能为负数')
        sys.exit(1)

    with open(SECRETS_PATH) as f:
        secrets = yaml.safe_load(f)
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    max_retries = cfg.get('max_query_retries', 3)
    req_interval = cfg.get('request_interval_seconds', 3)

    print(f'当前等级：{current_level}')
    print('正在查询库存...')

    session = build_session(secrets)
    badges = fetch_badges(session, secrets['api_key'], secrets['steamid'], max_retries)
    inventory = fetch_inventory(session, secrets['steamid'], max_retries, req_interval)

    # 加载卡种数映射（用于判断是否集齐全套）
    price_df = pd.read_csv(PRICE_LIST_PATH, encoding='utf-8-sig', dtype={'AppId': str})
    num_cards_map = dict(zip(
        price_df['AppId'],
        pd.to_numeric(price_df['# Cards'], errors='coerce').fillna(0).astype(int),
    ))

    # 按游戏计算可合成次数
    craftable = {}   # {appid: crafts}
    skipped_missing_types = []

    for appid, items in inventory.items():
        # 只保留交易卡片
        cards = {hn: cnt for hn, cnt in items.items() if is_trading_card(hn)}
        if not cards:
            continue

        num_types_owned = len(cards)
        num_types_expected = num_cards_map.get(appid, 0)

        if num_types_expected <= 0 or num_types_owned != num_types_expected:
            # 卡种不全，无法合成
            skipped_missing_types.append((appid, num_types_owned, num_types_expected))
            continue

        badge_level = badges.get(appid, {}).get('level', 0)
        crafts = min(min(cards.values()), max(0, 5 - badge_level))
        if crafts > 0:
            craftable[appid] = crafts

    total_badges = sum(craftable.values())

    # 输出可合成游戏明细
    print(f'\n可合成徽章的游戏（{len(craftable)} 个）：')
    game_name_map = dict(zip(price_df['AppId'], price_df['Game']))
    for appid, crafts in sorted(craftable.items(), key=lambda x: -x[1]):
        name = game_name_map.get(appid, appid)
        print(f'  {name[:40]:<40} {crafts:>3} 次')

    if skipped_missing_types:
        print(f'\n卡种不全、无法合成的游戏（{len(skipped_missing_types)} 个）：')
        for appid, owned, expected in skipped_missing_types[:10]:
            name = game_name_map.get(appid, appid)
            print(f'  {name[:40]:<40} 有 {owned}/{expected} 种卡')
        if len(skipped_missing_types) > 10:
            print(f'  ... 还有 {len(skipped_missing_types) - 10} 个')

    # 计算升级结果
    result = calc_target_level(current_level, total_badges)

    print(f'\n=== 升级计算结果 ===')
    print(f'当前等级：{current_level}')
    print(f'可合成徽章总数：{total_badges:,} 个')
    print(f'可升至等级：{result["target_level"]}（+{result["target_level"] - current_level} 级）')
    print(f'消耗 XP：{result["xp_used"]:,}，剩余 XP：{result["xp_remaining"]}')


if __name__ == '__main__':
    main()
