"""
grind_scan.py — 扫描库存，将所有物品信息（含宝石值）保存到 CSV。

用法：
    python3 -m tools.grind_scan [--output data/inventory_scan.csv]
"""

import argparse
import csv
import os
import re
import sys
import time

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'secrets.yaml')
CONFIG_PATH  = os.path.join(BASE_DIR, 'config', 'config.yaml')
DEFAULT_OUT  = os.path.join(BASE_DIR, 'data', 'inventory_scan.csv')

# 用于显示物品类型名称（仅展示用，不用于宝石查询）
ITEM_CLASS_NAMES = {
    'item_class_2':  'Trading Card',
    'item_class_3':  'Profile Background',
    'item_class_4':  'Emoticon',
    'item_class_5':  'Booster Pack',
    'item_class_7':  'Steam Gems',
    'item_class_8':  'Sale Item',
    'item_class_10': 'Trading Card',
    'item_class_11': 'Sale Item',
    'item_class_13': 'Sale Item',
    'item_class_14': 'Sale Item',
    'item_class_15': 'Sale Item',
}

# 从 owner_actions 的 GetGooValue 链接里提取 item_type 和 border_color
# 格式：GetGooValue( '%contextid%', '%assetid%', appid, item_type, border_color )
_GOO_VALUE_RE = re.compile(
    r"GetGooValue\s*\([^,]+,[^,]+,\s*\d+\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)

OUTPUT_COLS = [
    'assetid', 'classid', 'instanceid',
    'game_appid', 'name', 'market_hash_name',
    'item_type', 'item_type_name', 'border_color',
    'tradable', 'marketable',
]


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


def fetch_full_inventory(sess: requests.Session, steamid: str, interval: float) -> list:
    """获取完整库存，返回 [(asset, description), ...] 列表。"""
    url = f'https://steamcommunity.com/inventory/{steamid}/753/6'
    params = {'l': 'english', 'count': 2000}
    all_items = []

    while True:
        resp = sess.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data or data.get('success') != 1:
            break

        descs = {
            f"{d['classid']}_{d['instanceid']}": d
            for d in data.get('descriptions', [])
        }
        for asset in data.get('assets', []):
            key = f"{asset['classid']}_{asset['instanceid']}"
            desc = descs.get(key)
            if desc:
                all_items.append((asset, desc))

        if not data.get('more_items'):
            break
        last = data.get('last_assetid')
        if not last:
            break
        params = {'l': 'english', 'count': 2000, 'start_assetid': last}
        time.sleep(interval)

    return all_items


def parse_item(asset: dict, desc: dict) -> dict:
    """从 asset + description 提取结构化信息。"""
    tags = {t['category']: t['internal_name'] for t in desc.get('tags', [])}

    # item_type_name：展示用，来自 item_class tag
    item_class_tag = tags.get('item_class', '')
    item_type_name = ITEM_CLASS_NAMES.get(item_class_tag, item_class_tag)

    # item_type / border_color：从 owner_actions 的 GetGooValue 链接提取
    # 这才是 Steam 宝石查询真正使用的值，比 item_class 更准确
    item_type = ''
    border_color = '0'
    for action in desc.get('owner_actions', []):
        m = _GOO_VALUE_RE.search(action.get('link', ''))
        if m:
            item_type = m.group(1)
            border_color = m.group(2)
            break
    # 无 GetGooValue 的物品无法转宝石，item_type 留空，goo_value 查询会跳过

    # 游戏 appid
    game_tag = tags.get('Game', '')
    if game_tag.startswith('app_'):
        game_appid = game_tag[4:]
    else:
        mhn = desc.get('market_hash_name', '')
        game_appid = mhn.split('-', 1)[0] if '-' in mhn else ''

    return {
        'assetid':          asset['assetid'],
        'classid':          desc['classid'],
        'instanceid':       desc['instanceid'],
        'game_appid':       game_appid,
        'name':             desc.get('name', ''),
        'market_hash_name': desc.get('market_hash_name', ''),
        'item_type':        item_type,
        'item_type_name':   item_type_name,
        'border_color':     border_color,
        'tradable':         str(desc.get('tradable', 0)),
        'marketable':       str(desc.get('marketable', 0)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=DEFAULT_OUT)
    args = parser.parse_args()

    with open(SECRETS_PATH) as f:
        secrets = yaml.safe_load(f)
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    interval = cfg.get('request_interval_seconds', 3)
    steamid  = secrets['steamid']

    sess = build_session(secrets)

    print('正在获取库存...')
    items_raw = fetch_full_inventory(sess, steamid, interval)
    print(f'共 {len(items_raw)} 个物品，开始解析...')

    rows = [parse_item(a, d) for a, d in items_raw]

    # 写 CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLS)
        w.writeheader()
        w.writerows(rows)

    # 统计
    from collections import Counter
    type_counts = Counter(r['item_type_name'] for r in rows)
    print(f'\n已保存到 {args.output}，共 {len(rows)} 条：')
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f'  {t}: {c}')


if __name__ == '__main__':
    main()
