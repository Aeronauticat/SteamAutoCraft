from src.circuit_breaker import exceeds_run_total, exceeds_single_game_limit


class TestExceedsSingleGameLimit:
    def test_under_limit(self):
        assert exceeds_single_game_limit(400, 500) is False

    def test_exactly_at_limit(self):
        assert exceeds_single_game_limit(500, 500) is False

    def test_over_limit(self):
        assert exceeds_single_game_limit(501, 500) is True

    def test_zero_cost(self):
        assert exceeds_single_game_limit(0, 500) is False


class TestExceedsRunTotal:
    def test_under_limit(self):
        assert exceeds_run_total(5000, 4999, 10000) is False

    def test_exactly_at_limit(self):
        assert exceeds_run_total(5000, 5000, 10000) is False

    def test_over_limit(self):
        assert exceeds_run_total(5000, 5001, 10000) is True

    def test_zero_spent_zero_cost(self):
        assert exceeds_run_total(0, 0, 10000) is False

    def test_already_at_limit_any_cost(self):
        assert exceeds_run_total(10000, 1, 10000) is True
