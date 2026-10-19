"""
badge_cost.py — 计算每款游戏合成一次徽章的市场成本。

流程：
  启动时先重试 badge_cost.csv 中的报错行（error / no price data / no market listings），
  然后继续处理 steamcardexchange.csv 中尚未处理的新游戏。
  累计报错超过 MAX_ERRORS 次直接终止。

运行：
  python3 -m tools.badge_cost [--limit N] [--interval F] [--workers N]
首次运行前，将 data/steamcardexchange.example.csv 复制为 data/steamcardexchange.csv，
并填写真实游戏数据；示例文件仅包含表头。
"""

import csv
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.market import get_item_name_id, search_cards
from src.http_utils import get_with_retry

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_LIST_PATH = os.path.join(BASE_DIR, 'data', 'steamcardexchange.csv')
OUTPUT_PATH = os.path.join(BASE_DIR, 'data', 'badge_cost.csv')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.yaml')
SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'secrets.yaml')

OUTPUT_COLS = ['appid', 'game_name', 'num_cards', 'avg_card_price_hkd', 'badge_cost_hkd', 'cards_found', 'note']
HISTOGRAM_URL = 'https://steamcommunity.com/market/itemordershistogram'
MAX_ERRORS = 10
MAX_429 = 3
BACKOFF_429 = [60, 120]  # 第1次、第2次 429 的等待秒数；第3次直接退出

RETRY_NOTE_PATTERNS = ('error', 'no price data', 'no market listings', 'incomplete card data')


def is_429(exc) -> bool:
    return hasattr(exc, 'response') and getattr(exc.response, 'status_code', None) == 429


def weighted_avg_price_top10(sell_order_graph: list) -> float:
    total_cost = 0.0
    total_qty = 0
    target = 10
    prev_cum = 0
    for entry in sell_order_graph:
        price_f, cum_count = entry[0], int(entry[1])
        at_this_price = cum_count - prev_cum
        if at_this_price <= 0:
            prev_cum = cum_count
            continue
        take = min(at_this_price, target - total_qty)
        total_cost += price_f * take
        total_qty += take
        prev_cum = cum_count
        if total_qty >= target:
            break
    return total_cost / total_qty if total_qty > 0 else 0.0


def get_card_avg_price(session, hash_name: str, max_retries: int, req_interval: float) -> float:
    """
    查询单张卡前 10 挂单加权均价（HKD）。
    网络错误直接 raise；无挂单数据返回 0.0。
    """
    item_nameid = get_item_name_id(session, hash_name, max_retries, req_interval)
    time.sleep(req_interval)

    encoded = urllib.parse.quote(hash_name)
    headers = {'Referer': f'https://steamcommunity.com/market/listings/753/{encoded}'}
    params = {'country': 'HK', 'language': 'schinese', 'currency': '29', 'item_nameid': str(item_nameid)}
    data = get_with_retry(session, HISTOGRAM_URL, params, max_retries, req_interval, headers=headers)
    time.sleep(req_interval)

    graph = data.get('sell_order_graph', [])
    return weighted_avg_price_top10(graph) if graph else 0.0


def query_game(session, appid: str, game_name: str, num_cards: int,
               max_retries: int, req_interval: float, workers: int) -> tuple:
    """
    查询一款游戏的徽章成本。
    返回 (row_dict, card_error_count)。
    search_cards 失败时直接 raise。
    """
    hash_names = search_cards(session, appid, num_cards, max_retries, req_interval)

    if not hash_names:
        return {
            'appid': appid, 'game_name': game_name, 'num_cards': num_cards,
            'avg_card_price_hkd': '', 'badge_cost_hkd': '', 'cards_found': 0,
            'note': 'no market listings',
        }, 0, 0

    card_prices = []
    card_error_count = 0
    card_429_count = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_hn = {
            executor.submit(get_card_avg_price, session, hn, max_retries, req_interval): hn
            for hn in hash_names
        }
        for future in as_completed(future_to_hn):
            hn = future_to_hn[future]
            try:
                price = future.result()
                if price > 0:
                    card_prices.append(price)
                    print(f'    {hn}: HK${price:.2f}')
                else:
                    print(f'    {hn}: 无价格数据')
            except ValueError as e:
                # 数据错误（item_nameid not found 等），不计入任何计数
                print(f'    [SKIP] {hn}: {e}')
            except Exception as e:
                if is_429(e):
                    card_429_count += 1
                else:
                    card_error_count += 1
                print(f'    [ERROR] {hn}: {e}')

    if len(hash_names) != num_cards or len(card_prices) != num_cards:
        return {
            'appid': appid, 'game_name': game_name, 'num_cards': num_cards,
            'avg_card_price_hkd': '', 'badge_cost_hkd': '', 'cards_found': len(hash_names),
            'note': f'incomplete card data: priced {len(card_prices)}/{num_cards} cards',
        }, card_error_count, card_429_count

    avg = sum(card_prices) / len(card_prices)
    badge_cost = avg * num_cards
    print(f'  → 单卡均价 HK${avg:.2f}，合成一次 HK${badge_cost:.2f}')
    return {
        'appid': appid, 'game_name': game_name, 'num_cards': num_cards,
        'avg_card_price_hkd': round(avg, 4),
        'badge_cost_hkd': round(badge_cost, 4),
        'cards_found': len(hash_names),
        'note': f'priced {len(card_prices)}/{len(hash_names)} cards',
    }, card_error_count, card_429_count


def load_retry_rows(output_path: str) -> pd.DataFrame:
    """返回需要重试的行（note 包含报错关键词）。"""
    if not os.path.exists(output_path):
        return pd.DataFrame(columns=OUTPUT_COLS)
    df = pd.read_csv(output_path, dtype={'appid': str, 'game_name': str, 'num_cards': str})
    mask = df['note'].astype(str).str.contains('|'.join(RETRY_NOTE_PATTERNS), case=False, na=False)
    return df[mask].copy()


def update_row_in_place(output_path: str, appid: str, new_row: dict) -> None:
    """读取 CSV，更新指定 appid 的行，写回。"""
    df = pd.read_csv(output_path, dtype={'appid': str})
    idx = df.index[df['appid'] == appid].tolist()
    if not idx:
        return
    i = idx[0]
    # 将数值列转为 object，避免写入空字符串时的 dtype 兼容警告
    for col in ['avg_card_price_hkd', 'badge_cost_hkd', 'cards_found']:
        if col in df.columns:
            df[col] = df[col].astype(object)
    for col, val in new_row.items():
        if col in df.columns:
            df.at[i, col] = val
    df.to_csv(output_path, index=False)


def load_done_appids(output_path: str) -> set:
    if not os.path.exists(output_path):
        return set()
    try:
        df = pd.read_csv(output_path, dtype={'appid': str})
        # 只有成功有价格的行才算 done，其余需要重新处理
        done = df[~df['note'].astype(str).str.contains('|'.join(RETRY_NOTE_PATTERNS), case=False, na=False)]
        return set(done['appid'].dropna().unique())
    except Exception:
        return set()


def init_output_file(output_path: str) -> None:
    if not os.path.exists(output_path):
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=OUTPUT_COLS).writeheader()


def append_row(output_path: str, row: dict) -> None:
    with open(output_path, 'a', newline='', encoding='utf-8') as f:
        csv.DictWriter(f, fieldnames=OUTPUT_COLS).writerow(row)


def build_session(secrets: dict) -> requests.Session:
    session = requests.Session()
    for name, value in {
        'steamLoginSecure': secrets['steam_login_secure'],
        'sessionid': secrets['sessionid'],
        'steamCountry': secrets.get('steam_country_cookie', 'HK'),
        'timezoneOffset': '28800,0',
        'timezoneName': 'Asia%2FShanghai',
        'bMarketOptOut': '1',
    }.items():
        session.cookies.set(name, value, domain='steamcommunity.com')
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/149.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Prototype-Version': '1.7',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    })
    return session


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='新游戏最多处理 N 个（不含重试）')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--workers', type=int, default=5)
    args = parser.parse_args()

    with open(CONFIG_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    with open(SECRETS_PATH, encoding='utf-8') as f:
        secrets = yaml.safe_load(f)

    max_retries = cfg.get('max_query_retries', 3)
    req_interval = args.interval
    workers = args.workers

    session = build_session(secrets)

    init_output_file(OUTPUT_PATH)

    error_count = 0
    count_429 = 0

    def on_429() -> bool:
        """429 发生时调用。暂停程序，返回 True 表示已超上限应退出。"""
        nonlocal count_429
        count_429 += 1
        if count_429 >= MAX_429:
            print(f'[退出] 累计 {count_429} 次 429，已达上限 {MAX_429}，程序退出。')
            return True
        wait = BACKOFF_429[count_429 - 1] if count_429 - 1 < len(BACKOFF_429) else BACKOFF_429[-1]
        print(f'[429] 第 {count_429} 次，暂停 {wait}s 后继续...')
        time.sleep(wait)
        return False

    def check_errors(new_errors: int) -> bool:
        nonlocal error_count
        error_count += new_errors
        if error_count >= MAX_ERRORS:
            print(f'[终止] 累计报错 {error_count} 次，已达上限 {MAX_ERRORS}，程序退出。')
            return True
        return False

    def process_one(appid, game_name, num_cards, save_fn):
        """查询单个游戏，处理 429 退避。save_fn(row) 负责写结果。
        返回 True 表示应退出整个程序。"""
        while True:
            try:
                result_row, card_errs, c429 = query_game(
                    session, appid, game_name, num_cards, max_retries, req_interval, workers)
                if c429 > 0:
                    # 卡片级 429，暂停后重试整个游戏
                    if on_429():
                        return True
                    continue
                save_fn(result_row)
                return check_errors(card_errs)
            except Exception as e:
                if is_429(e):
                    if on_429():
                        return True
                    continue  # 重试当前游戏
                # 非 429 错误：记录并跳过
                print(f'  [ERROR] {game_name}: {e}')
                save_fn({
                    'appid': appid, 'game_name': game_name, 'num_cards': num_cards,
                    'avg_card_price_hkd': '', 'badge_cost_hkd': '', 'cards_found': 0,
                    'note': f'search_cards error: {e}',
                })
                return check_errors(1)

    # ── 阶段1：重试历史报错行 ──
    retry_rows = load_retry_rows(OUTPUT_PATH)
    if not retry_rows.empty:
        print(f'[重试阶段] 共 {len(retry_rows)} 行需要重试')
        for _, rrow in retry_rows.iterrows():
            appid = str(rrow['appid'])
            game_name = str(rrow['game_name'])
            num_cards = int(pd.to_numeric(rrow['num_cards'], errors='coerce') or 0)
            print(f'  [重试] {game_name} ({appid})')
            if process_one(appid, game_name, num_cards,
                           lambda row, aid=appid: update_row_in_place(OUTPUT_PATH, aid, row)):
                return
            time.sleep(req_interval)
        print(f'[重试阶段] 完成，429次数: {count_429}，错误次数: {error_count}')
    else:
        print('[重试阶段] 无需重试的行')

    # ── 阶段2：处理新游戏 ──
    price_df = pd.read_csv(PRICE_LIST_PATH, encoding='utf-8-sig', dtype={'AppId': str})
    num_cards_col = pd.to_numeric(price_df['# Cards'], errors='coerce').fillna(0).astype(int)
    done_appids = load_done_appids(OUTPUT_PATH)

    total = len(price_df)
    limit = args.limit or total
    processed = 0

    print(f'\n[新游戏阶段] 已完成 {len(done_appids)} 个，本次最多处理 {limit} 个新游戏')

    for i, row in price_df.iterrows():
        if processed >= limit:
            break

        appid = str(row['AppId'])
        game_name = str(row['Game'])
        num_cards = int(num_cards_col.iloc[i])

        if appid in done_appids:
            continue

        print(f'[{i+1}/{total}] {game_name} ({appid}) num_cards={num_cards}')
        if process_one(appid, game_name, num_cards,
                       lambda row: append_row(OUTPUT_PATH, row)):
            return
        processed += 1

    print(f'\n[完成] 新游戏处理 {processed} 个，429次数: {count_429}，错误次数: {error_count}')


if __name__ == '__main__':
    main()
