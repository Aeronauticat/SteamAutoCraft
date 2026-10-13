import time

from src.http_utils import get_with_retry

BADGES_URL = 'https://api.steampowered.com/IPlayerService/GetBadges/v1/'
INVENTORY_URL = 'https://steamcommunity.com/inventory/{steamid}/753/6'


def fetch_badges(session, api_key: str, steamid: str, max_retries: int = 3) -> dict:
    """
    Call GetBadges and return badge data keyed by appid string.

    Returns:
        {appid_str: {"level": int, "cards_remaining": int}, ...}
        Games not in the response are omitted; caller treats them as level=0.
    """
    params = {'key': api_key, 'steamid': steamid}
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.get(BADGES_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            badges = {}
            for badge in data.get('response', {}).get('badges', []):
                if 'appid' not in badge:
                    continue
                appid = str(badge['appid'])
                badges[appid] = {
                    'level': badge.get('level', 0),
                    'cards_remaining': badge.get('cards_remaining', 0),
                }
            return badges
        except Exception as exc:
            last_exc = exc
            is_429 = hasattr(exc, 'response') and getattr(exc.response, 'status_code', None) == 429
            if is_429 or attempt >= max_retries - 1:
                raise exc
            time.sleep(3)
    raise last_exc


def fetch_inventory(session, steamid: str, max_retries: int = 3, request_interval: int = 3) -> dict:
    """
    Fetch the full Steam community inventory (appid=753, contextid=6) with pagination.

    Returns:
        {appid_str: {market_hash_name: count, ...}, ...}
        appid is extracted from the first segment of market_hash_name before the first '-'.
    """
    inventory: dict = {}
    url = INVENTORY_URL.format(steamid=steamid)
    params: dict = {'l': 'english', 'count': 2000}

    while True:
        data = get_with_retry(session, url, params, max_retries, request_interval, timeout=30)

        if not data or data.get('success') != 1:
            break

        descriptions = {
            f"{d['classid']}_{d['instanceid']}": d
            for d in data.get('descriptions', [])
        }

        for asset in data.get('assets', []):
            key = f"{asset['classid']}_{asset['instanceid']}"
            desc = descriptions.get(key, {})
            hash_name = desc.get('market_hash_name', '')
            if not hash_name:
                continue
            appid = hash_name.split('-', 1)[0]
            inv_game = inventory.setdefault(appid, {})
            inv_game[hash_name] = inv_game.get(hash_name, 0) + 1

        if not data.get('more_items'):
            break

        last_assetid = data.get('last_assetid')
        if not last_assetid:
            break

        params = {'l': 'english', 'count': 2000, 'start_assetid': last_assetid}
        time.sleep(request_interval)

    return inventory


