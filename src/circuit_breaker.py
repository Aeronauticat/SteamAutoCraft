def exceeds_single_game_limit(cost_cents: int, limit_cents: int) -> bool:
    """Return True if this game's total cost exceeds the per-game limit."""
    return cost_cents > limit_cents


def exceeds_run_total(current_spent: int, this_game_cost: int, run_total_limit: int) -> bool:
    """Return True if adding this game would push the run total over the limit."""
    return current_spent + this_game_cost > run_total_limit
