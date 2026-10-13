import re
import time
import urllib.parse

from steampy.models import Currency, GameOptions

from src.http_utils import get_with_retry

SEARCH_URL = 'https://steamcommunity.com/market/search/render/'
LISTING_PAGE_URL = 'https://steamcommunity.com/market/listings/753/{hash_name}'
HISTOGRAM_URL = 'https://steamcommunity.com/market/itemordershistogram'


def search_cards(session, appid: str, num_cards: int, max_retries: int = 3, request_interval: int = 3) -> list:
    """
    Fetch all trading card hash_names for the given game via paginated market search.

    Returns:
        List of hash_name strings.
    """
    hash_names: list = []
    seen: set = set()
    start = 0
    prev_total = -1

    while True:
        params = {
            'query': '',
            'norender': '1',
            'appid': '753',
            'category_753_item_class[]': 'tag_item_class_2',
            'category_753_cardborder[]': 'tag_cardborder_0',   # 非闪卡
            'category_753_Game[]': f'tag_app_{appid}',
            'sort_column': 'popular',
            'sort_dir': 'desc',
            'currency': '29',
            'count': '10',
            'start': str(start),
        }
        headers = {
            'Referer': f'https://steamcommunity.com/market/search?appid=753&category_753_item_class%5B%5D=tag_item_class_2&category_753_Game%5B%5D=tag_app_{appid}',
        }

        data = get_with_retry(session, SEARCH_URL, params, max_retries, request_interval, headers=headers)
        results = data.get('results', [])

        for item in results:
            hn = item.get('hash_name', '')
            if hn and hn not in seen:
                seen.add(hn)
                hash_names.append(hn)

        current_total = len(hash_names)
        if not results or current_total >= num_cards or current_total == prev_total:
            break

        prev_total = current_total
        start += len(results)
        time.sleep(request_interval)

    return hash_names


def get_item_name_id(session, hash_name: str, max_retries: int = 3, request_interval: int = 3) -> int:
    """
    Fetch the listing page HTML and extract the Steam-internal item_nameid.

    Needed for itemordershistogram. Raises ValueError if not found.
    """
    encoded = urllib.parse.quote(hash_name)
    url = LISTING_PAGE_URL.format(hash_name=encoded)
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            m = re.search(r'Market_LoadOrderSpread\(\s*(\d+)\s*\)', resp.text)
            if m:
                return int(m.group(1))
            raise ValueError(f'item_nameid not found in page for {hash_name}')
        except ValueError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(request_interval)
    raise last_exc


def get_order_histogram(
    session, hash_name: str, item_nameid: int,
    max_retries: int = 3, request_interval: int = 3,
    needed_qty: int = 1,
) -> tuple:
    """
    Fetch itemordershistogram and compute our bid price + total available quantity.

    our_price = 1 cent above the lowest price level where cumulative count >= needed_qty.
    If total market depth < needed_qty, our_price is still set to cover as many as possible.
    available = total sell order depth across all price levels.

    Returns:
        (our_price_cents: int, total_available_qty: int, sell_order_graph: list)
        Returns (0, 0, []) if no sell orders exist.
    """
    encoded = urllib.parse.quote(hash_name)
    headers = {
        'Referer': f'https://steamcommunity.com/market/listings/753/{encoded}',
    }
    params = {'country': 'HK', 'language': 'schinese', 'currency': '29', 'item_nameid': str(item_nameid)}

    data = get_with_retry(session, HISTOGRAM_URL, params, max_retries, request_interval, headers=headers)

    lowest_str = data.get('lowest_sell_order')
    if not lowest_str:
        return 0, 0, []

    graph = data.get('sell_order_graph', [])
    if not graph:
        return 0, 0, []

    # 总可购数量 = 最后一条累计值
    total_available = int(graph[-1][1])

    # 找到累计数量首次 >= needed_qty 的最低价格层，以该价格 +1 分作为出价
    # 若市场总量不足 needed_qty，取最高价格层 +1 分（后续由调用方判断是否足够）
    lowest = int(lowest_str)
    our_price = lowest + 1  # 默认：最低价 +1 分
    for entry in graph:
        price_f, cum_count = entry[0], int(entry[1])
        if cum_count >= needed_qty:
            our_price = round(price_f * 100) + 1
            break

    return our_price, total_available, graph


def place_buy_order(client, hash_name: str, price_cents: int, quantity: int) -> dict:
    """
    Place a buy order for `quantity` copies of `hash_name` at `price_cents` per item.

    IMPORTANT: NO RETRY on success/failure. The 406+success=22 path is a
    Steam Guard confirmation flow (not a retry): first request returns a
    confirmation_id, user confirms on phone, second request carries that id.

    Raises ApiException on failure.
    """
    from steampy.exceptions import ApiException

    encoded = urllib.parse.quote(hash_name)
    data = {
        'sessionid':        client._session.cookies.get('sessionid'),
        'currency':         str(Currency.HKD.value),
        'appid':            '753',
        'market_hash_name': hash_name,
        'price_total':      str(price_cents * quantity),
        'tradefee_tax':     '0',
        'quantity':         str(quantity),
        'billing_state':    '',
        'save_my_address':  '0',
    }
    headers = {
        'Origin':  'https://steamcommunity.com',
        'Referer': f'https://steamcommunity.com/market/listings/753/{encoded}',
    }
    url = 'https://steamcommunity.com/market/createbuyorder/'

    resp = client._session.post(url, data=data, headers=headers).json()

    # Steam Guard confirmation required: block until user confirms on phone
    if resp.get('success') == 22 and resp.get('need_confirmation'):
        confirmation_id = resp.get('confirmation', {}).get('confirmation_id', '')
        print(
            f'\n[需要手机确认] {hash_name} x{quantity} @ HK${price_cents / 100:.2f}\n'
            f'请在 iPhone Steam App 确认"确认社区交易"后按回车继续...',
            flush=True,
        )
        input()
        data['confirmation'] = confirmation_id
        resp = client._session.post(url, data=data, headers=headers).json()

    if resp.get('success') != 1:
        raise ApiException(f'createbuyorder failed: {resp}')

    return resp
