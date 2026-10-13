def get_remaining_crafts(badges: dict, appid: str) -> int:
    """Return number of badge crafts still possible (0-5)."""
    level = badges.get(str(appid), {}).get('level', 0)
    return max(0, 5 - level)


def calculate_needs(hash_names: list, badges: dict, inventory: dict, appid: str) -> dict:
    """
    Compute how many of each card to buy.

    need = max(0, remaining_crafts - owned)

    Returns:
        {hash_name: need} for all hash_names in the input list.
    """
    remaining_crafts = get_remaining_crafts(badges, appid)
    inv_for_game = inventory.get(str(appid), {})
    return {hn: max(0, remaining_crafts - inv_for_game.get(hn, 0)) for hn in hash_names}
