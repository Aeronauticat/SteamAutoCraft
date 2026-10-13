import fcntl
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd
import yaml
from steampy.client import SteamClient

from src.card_analyzer import calculate_needs, get_remaining_crafts
from src.circuit_breaker import exceeds_run_total, exceeds_single_game_limit
from src.logger import setup_loggers
from src.market import get_item_name_id, get_order_histogram, place_buy_order, search_cards
from src.progress import SCAN_COOLDOWN_DAYS, get_next_game, init_progress_if_needed, load_progress, update_game
from src.steam_api import fetch_badges, fetch_inventory

MAX_429 = 3          # 单次运行累计 429 次数上限，超过直接退出
BACKOFF_429_INIT = 60  # 首次 429 等待秒数，之后每次翻倍

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_LIST_PATH = os.path.join(BASE_DIR, 'data', 'STC_set_data_sort.csv')
PROGRESS_PATH = os.path.join(BASE_DIR, 'data', 'progress.csv')
USER_INFO_PATH = os.path.join(BASE_DIR, 'data', 'user_info.json')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.yaml')
SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'secrets.yaml')
LOCKFILE_PATH = os.path.join(BASE_DIR, 'autobuy.lock')


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_secrets():
    with open(SECRETS_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_user_info(steamid: str, badges: dict, inventory: dict) -> None:
    data = {
        'steamid': steamid,
        'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
        'badges': badges,
        'inventory': inventory,
    }
    os.makedirs(os.path.dirname(USER_INFO_PATH), exist_ok=True)
    with open(USER_INFO_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_wallet_cents(client) -> int:
    """Return wallet balance in HKD cents as int.
    Parses g_rgWalletInfo from the market page directly instead of relying on
    steampy's get_wallet_balance, which fails if the page response varies.
    """
    import json as _json
    resp = client._session.get('https://steamcommunity.com/market', timeout=15)
    resp.raise_for_status()
    m = re.search(r'var g_rgWalletInfo = ({.*?});', resp.text)
    if not m:
        raise ValueError('g_rgWalletInfo not found in market page')
    info = _json.loads(m.group(1))
    return int(info['wallet_balance'])


def _is_429(exc) -> bool:
    return hasattr(exc, 'response') and getattr(exc.response, 'status_code', None) == 429


def _marginal_unit_price_cents(sell_order_graph: list, unit_index: int):
    """
    返回 sell_order_graph 中第 unit_index 便宜的单位的价格（HKD 分，1-indexed）。
    市场深度不足时返回 None。
    """
    for entry in sell_order_graph:
        price_f, cum_count = entry[0], int(entry[1])
        if cum_count >= unit_index:
            return round(price_f * 100) + 1
    return None


def _cost_of_kth_set_cents(k: int, hash_names: list, inv_for_game: dict, graphs: dict):
    """
    返回 (cost_cents, feasible)：第 k 套徽章卡片的边际成本（HKD 分）。
    只计算 owned < k 的卡——已有库存的卡无需再买，不计入本套成本。
    graphs: {hash_name: sell_order_graph}
    """
    total = 0
    for hn in hash_names:
        owned = inv_for_game.get(hn, 0)
        if owned >= k:
            continue
        unit_idx = k - owned  # 需要该卡的第 unit_idx 便宜的单位
        price = _marginal_unit_price_cents(graphs.get(hn, []), unit_idx)
        if price is None:
            return 0, False
        total += price
    return total, True


def ensure_session(client, err_log) -> bool:
    """Return False if session is dead — caller must break the run."""
    try:
        if client.username is not None:
            alive = client.is_session_alive()
        else:
            resp = client._session.get('https://steamcommunity.com/', timeout=10)
            alive = 'g_steamID' in resp.text
    except Exception:
        alive = False
    if not alive:
        err_log.error('Session expired. Re-paste cookies in secrets.yaml and re-run.')
        return False
    return True


def main():
    # 防止多实例并发运行
    _lockfile = open(LOCKFILE_PATH, 'w')
    try:
        fcntl.flock(_lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('[错误] 检测到另一个 AutoBuy 实例正在运行，退出。', flush=True)
        sys.exit(1)

    run_log, biz_log, err_log = setup_loggers()
    run_log.info('AutoBuy started')

    cfg = load_config()
    secrets = load_secrets()

    single_game_limit = cfg['single_game_limit_hkd_cents']
    run_total_limit = cfg['run_total_limit_hkd_cents']
    run_game_limit = cfg['run_game_limit']
    max_retries = cfg['max_query_retries']
    req_interval = cfg['request_interval_seconds']
    order_interval = cfg['order_interval_seconds']

    steamid = secrets['steamid']
    login_cookies = {
        'steamLoginSecure': secrets['steam_login_secure'],
        'sessionid': secrets['sessionid'],
    }
    client = SteamClient(api_key=secrets['api_key'], login_cookies=login_cookies)

    # Set full browser-compatible cookies and headers so market API accepts requests
    client._session.cookies.update({
        'steamCountry': secrets.get('steam_country_cookie', 'HK'),
        'timezoneOffset': '28800,0',
        'timezoneName': 'Asia%2FShanghai',
        'bMarketOptOut': '1',
    })
    client._session.headers.update({
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
    run_log.info('Session initialised, steamid=%s', steamid)

    init_progress_if_needed(PRICE_LIST_PATH, PROGRESS_PATH)
    run_log.info('Progress file ready: %s', PROGRESS_PATH)

    # Load price list once; used inside the loop for num_cards lookup
    price_df = pd.read_csv(PRICE_LIST_PATH, encoding='utf-8-sig', dtype={'AppId': str})
    num_cards_map: dict = dict(zip(
        price_df['AppId'],
        pd.to_numeric(price_df['# Cards'], errors='coerce').fillna(999).astype(int),
    ))

    games_bought = 0
    total_spent = 0
    error_count = 0
    total_crafts_ready = 0   # 本次买齐缺口、可立即合成的次数合计
    visited_this_run: set = set()
    bought_summary: list = []
    count_429 = 0
    backoff_429_secs = BACKOFF_429_INIT
    first_request_done = False   # 首次请求完成前遇到 429 直接退出

    def on_429(log) -> bool:
        """遇到 429/限流时调用。返回 True 表示应终止运行。"""
        nonlocal count_429, backoff_429_secs, first_request_done
        if not first_request_done:
            log.error('[退出] 首次请求即遭遇 429/限流，直接终止运行。')
            return True
        count_429 += 1
        if count_429 >= MAX_429:
            log.error('[退出] 累计 %d 次 429/限流，达上限 %d，终止运行。', count_429, MAX_429)
            return True
        log.warning('[429] 第 %d 次限流，暂停 %ds 后继续...', count_429, backoff_429_secs)
        time.sleep(backoff_429_secs)
        backoff_429_secs *= 2
        return False

    # --- main loop ---
    while True:
        # Exit condition 0
        if games_bought >= run_game_limit:
            run_log.info('Run game limit reached (%d)', run_game_limit)
            break

        # Session check
        if not ensure_session(client, err_log):
            break

        # Step 1: refresh badges + inventory
        try:
            badges = fetch_badges(client._session, secrets['api_key'], steamid, max_retries)
            first_request_done = True  # badges 成功说明会话有效，后续 429 走指数退避
            inventory = fetch_inventory(client._session, steamid, max_retries, req_interval)
            save_user_info(steamid, badges, inventory)
        except Exception as exc:
            if _is_429(exc):
                if on_429(run_log):
                    break
                continue  # 暂停后重试本次循环
            err_log.error('Step1 failed: %s\n%s', exc, traceback.format_exc())
            break

        # Step 2: pick next game
        progress_df = load_progress(PROGRESS_PATH)
        game = get_next_game(progress_df, visited_this_run)
        if game is None:
            run_log.info('No more pending/in_progress games, exiting')
            break

        appid = str(game['appid'])
        game_name = game['game_name']
        current_status = game['status']
        badge_level = badges.get(appid, {}).get('level', 0)

        biz_log.info('Target game: appid=%s name=%s badge_level=%d status=%s',
                     appid, game_name, badge_level, current_status)
        biz_log.info('Inventory snapshot for appid=%s: %s', appid, inventory.get(appid, {}))

        # Step 3a: market search for card hash_names
        num_cards = num_cards_map.get(appid, 999)

        try:
            hash_names = search_cards(client._session, appid, num_cards, max_retries, req_interval)
        except Exception as exc:
            if _is_429(exc):
                if on_429(run_log):
                    break
                continue  # 暂停后重试，不标记 visited，下次循环重新处理本游戏
            err_log.error('Step3a search_cards failed appid=%s: %s\n%s', appid, exc, traceback.format_exc())
            visited_this_run.add(appid)
            continue

        if not hash_names:
            if current_status == 'pending':
                update_game(PROGRESS_PATH, appid, status='skipped')
                biz_log.info('No market listings found for appid=%s (pending→skipped)', appid)
            else:
                biz_log.info('No market listings found for appid=%s (in_progress, will retry next run)', appid)
            visited_this_run.add(appid)
            continue

        if len(hash_names) < num_cards:
            biz_log.info('appid=%s 卡种不全：找到 %d/%d，记录扫描时间，%d天内跳过',
                         appid, len(hash_names), num_cards, SCAN_COOLDOWN_DAYS)
            update_game(PROGRESS_PATH, appid, set_scan_time=True)
            visited_this_run.add(appid)
            continue

        # Step 3b: check if done or all-inventory-covered
        remaining_crafts = get_remaining_crafts(badges, appid)
        if remaining_crafts == 0:
            update_game(PROGRESS_PATH, appid, status='done')
            biz_log.info('appid=%s badge already level 5, marking done', appid)
            visited_this_run.add(appid)
            continue

        needs = calculate_needs(hash_names, badges, inventory, appid)
        if all(n == 0 for n in needs.values()):
            update_game(PROGRESS_PATH, appid, status='ready_to_craft')
            biz_log.info('appid=%s 卡片已买齐，标记 ready_to_craft，等待合成', appid)
            visited_this_run.add(appid)
            continue

        # Step 3c-pre: 预扫描市场，用边际定价确定 target_crafts
        inv_for_game = inventory.get(appid, {})
        pre_scan_graphs: dict = {}  # {hn: sell_order_graph}
        pre_scan_abort = False
        stop_outer = False  # 显式初始化，防止首次迭代中 on_429 引用未绑定变量

        for hn in hash_names:
            full_need = needs.get(hn, 0)
            if full_need == 0:
                pre_scan_graphs[hn] = []
                continue
            try:
                _nameid = get_item_name_id(client._session, hn, max_retries, req_interval)
                time.sleep(req_interval)
                _, _, graph = get_order_histogram(
                    client._session, hn, _nameid, max_retries, req_interval,
                    needed_qty=full_need)
                time.sleep(req_interval)
                pre_scan_graphs[hn] = graph
            except Exception as exc:
                if _is_429(exc):
                    pre_scan_abort = True
                    if on_429(run_log):
                        stop_outer = True
                    break
                err_log.error('Pre-scan failed hn=%s: %s', hn, exc)
                pre_scan_graphs[hn] = []

        if pre_scan_abort:
            if stop_outer:
                visited_this_run.add(appid)
                break
            continue  # 非终止次 429：等待后重试本游戏，不标记 visited

        # 逐套计算边际成本，找最大可行 target_crafts
        target_crafts = 0
        cumulative_cost = 0
        skip_reason = None  # 'market_out_of_stock' | 'overpriced' | 'cost_too_high' | 'run_total'
        skipped_for_run_total = False
        for k in range(1, remaining_crafts + 1):
            set_cost, feasible = _cost_of_kth_set_cents(k, hash_names, inv_for_game, pre_scan_graphs)
            if not feasible:
                biz_log.info('appid=%s 第 %d 套市场库存不足，目标定为 %d 套', appid, k, k - 1)
                if k == 1:
                    skip_reason = 'market_out_of_stock'
                break
            if set_cost > single_game_limit:
                if k == 1 and set_cost > 2 * single_game_limit:
                    skip_reason = 'overpriced'
                    biz_log.info('appid=%s 第1套成本 %d > 上限2倍 %d，标记 overpriced',
                                 appid, set_cost, 2 * single_game_limit)
                else:
                    biz_log.info('appid=%s 第 %d 套边际成本 %d > 单套上限 %d，目标定为 %d 套',
                                 appid, k, set_cost, single_game_limit, k - 1)
                    if k == 1:
                        skip_reason = 'cost_too_high'
                break
            if exceeds_run_total(total_spent, cumulative_cost + set_cost, run_total_limit):
                biz_log.info('appid=%s 加入第 %d 套后将超运行总限额，目标定为 %d 套',
                             appid, k, k - 1)
                if k == 1:
                    skipped_for_run_total = True
                    skip_reason = 'run_total'
                break
            cumulative_cost += set_cost
            target_crafts = k

        if target_crafts == 0:
            biz_log.info('appid=%s 无法完成任何一套合成（原因: %s），跳过', appid, skip_reason)
            if skip_reason == 'overpriced':
                update_game(PROGRESS_PATH, appid, status='overpriced')
            elif skip_reason == 'market_out_of_stock':
                update_game(PROGRESS_PATH, appid, set_scan_time=True)
            visited_this_run.add(appid)
            if skipped_for_run_total:
                run_log.info('run_total 预算耗尽（appid=%s），终止运行', appid)
                break
            continue

        if target_crafts < remaining_crafts:
            biz_log.info('appid=%s 目标 %d 套（剩余 %d 次），重算需求',
                         appid, target_crafts, remaining_crafts)
            needs = {hn: max(0, target_crafts - inv_for_game.get(hn, 0)) for hn in hash_names}
            if all(n == 0 for n in needs.values()):
                update_game(PROGRESS_PATH, appid, status='ready_to_craft')
                biz_log.info('appid=%s 库存已满足 %d 次合成需求，标记 ready_to_craft', appid, target_crafts)
                visited_this_run.add(appid)
                continue

        # Steps 3c-5: 内循环，持续购买直到需求全满足或熔断
        game_spent = 0          # 本游戏本轮运行累计花费（含所有重试）
        game_bought_count = 0
        cards_ordered: dict = {}        # {hash_name: qty_ordered_this_game}
        cards_bought_this_game: list = []
        # 注意：stop_outer 已在 pre-scan 前初始化，此处不重置，保留 pre-scan 的设值

        while True:
            # 计算本轮剩余需求（原始 need 减去已下单数量）
            round_needs = {
                hn: max(0, need - cards_ordered.get(hn, 0))
                for hn, need in needs.items()
            }
            if not any(v > 0 for v in round_needs.values()):
                biz_log.info('appid=%s 所有卡片需求已满足，可合成到 5 级', appid)
                break

            # Step 3c: 对剩余需求查 histogram
            to_buy: list = []
            round_abort = False  # 本轮遇到 429，不用不完整的 to_buy 继续下单
            for hn, rem_need in round_needs.items():
                if rem_need == 0:
                    continue
                try:
                    item_nameid = get_item_name_id(client._session, hn, max_retries, req_interval)
                    time.sleep(req_interval)
                    our_price, available, _ = get_order_histogram(
                        client._session, hn, item_nameid, max_retries, req_interval,
                        needed_qty=rem_need)
                    time.sleep(req_interval)
                except Exception as exc:
                    if _is_429(exc):
                        round_abort = True
                        if on_429(run_log):
                            stop_outer = True
                        break
                    err_log.error('Step3c histogram failed hn=%s: %s\n%s', hn, exc, traceback.format_exc())
                    continue

                if our_price == 0:
                    err_log.error('No sell orders for card: %s', hn)
                    continue

                actual_qty = min(rem_need, available)
                if actual_qty == 0:
                    biz_log.info('Card %s: rem_need=%d but available=0 at price=%d, skipping',
                                 hn, rem_need, our_price)
                    continue

                if available < rem_need:
                    biz_log.info('Card %s: rem_need=%d available=%d at price=%d, ordering %d',
                                 hn, rem_need, available, our_price, actual_qty)

                to_buy.append((hn, our_price, actual_qty))

            if round_abort:
                break  # 退出 while True，不用不完整的 to_buy 下单

            if not to_buy:
                biz_log.info('appid=%s 本轮无可购卡片（市场无货或全部满足），停止', appid)
                break

            # Step 4: 熔断检查
            round_cost = sum(p * q for _, p, q in to_buy)
            game_budget = target_crafts * single_game_limit  # 本游戏总预算上限

            if game_spent + round_cost > game_budget:
                biz_log.info('appid=%s 本轮费用 %d + 已花费 %d 超出游戏总预算 %d，停止',
                             appid, round_cost, game_spent, game_budget)
                break

            try:
                wallet = get_wallet_cents(client)
                if wallet < round_cost:
                    biz_log.info('Insufficient wallet balance: %d cents < %d cents needed', wallet, round_cost)
                    stop_outer = True
                    break
            except Exception as exc:
                err_log.warning('钱包余额查询失败，跳过预检继续下单（余额不足时订单会自行失败）: %s', exc)

            # Step 5: 下单（严禁重试）
            for hn, our_price, qty in to_buy:
                order_cost = our_price * qty
                try:
                    place_buy_order(client, hn, our_price, qty)
                    total_spent += order_cost
                    game_spent += order_cost
                    game_bought_count += qty
                    cards_ordered[hn] = cards_ordered.get(hn, 0) + qty
                    cards_bought_this_game.append((hn, qty, order_cost))
                    biz_log.info('ORDER PLACED appid=%s card=%s qty=%d price=%d cost=%d cents',
                                 appid, hn, qty, our_price, order_cost)
                except Exception as exc:
                    error_count += 1
                    err_log.error('ORDER FAILED appid=%s card=%s qty=%d price=%d: %s\n%s',
                                  appid, hn, qty, our_price, exc, traceback.format_exc())
                time.sleep(order_interval)

        visited_this_run.add(appid)

        if game_bought_count > 0:
            games_bought += 1
            gap = {hn: need - cards_ordered.get(hn, 0)
                   for hn, need in needs.items()
                   if cards_ordered.get(hn, 0) < need}
            if gap:
                biz_log.info('appid=%s 仍有缺口（市场不足或预算限制）: %s', appid, gap)
                new_status = 'in_progress'
                crafts_this_game = 0
            else:
                biz_log.info('appid=%s 本次买齐所有缺口，标记 ready_to_craft', appid)
                new_status = 'ready_to_craft'
                crafts_this_game = target_crafts
                total_crafts_ready += target_crafts
            update_game(
                PROGRESS_PATH,
                appid,
                status=new_status,
                bought_count_delta=game_bought_count,
                spent_delta=game_spent,
            )
            bought_summary.append({
                'appid': appid,
                'game_name': game_name,
                'cards': cards_bought_this_game,
                'spent': game_spent,
                'crafts': crafts_this_game,
            })
        else:
            biz_log.info('appid=%s 内循环未下单（市场变化/预算/429），进度不更新', appid)

        if stop_outer:
            break

    # Run summary
    games_skipped = len(visited_this_run) - games_bought
    run_log.info('--- Run complete ---')
    run_log.info(
        '本次处理 %d 个游戏：购买成功 %d 个（本次新买齐可合成 %d 组徽章），跳过 %d 个',
        len(visited_this_run), games_bought, total_crafts_ready, games_skipped,
    )
    run_log.info(
        '总花费 HK$%.2f（%d 分），下单失败 %d 次',
        total_spent / 100, total_spent, error_count,
    )
    for entry in bought_summary:
        crafts_str = ('可合成 %d 次' % entry['crafts']) if entry['crafts'] > 0 else '有缺口'
        run_log.info('  %s (%s): %s，花费 HK$%.2f',
                     entry['game_name'], entry['appid'], crafts_str, entry['spent'] / 100)
        for card_name, qty, cost in entry['cards']:
            run_log.info('    %s: qty=%d cost=%d 分', card_name, qty, cost)


if __name__ == '__main__':
    main()
