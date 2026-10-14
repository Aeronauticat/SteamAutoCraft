import pytest
from src.card_analyzer import calculate_needs, get_remaining_crafts


class TestGetRemainingCrafts:
    def test_appid_not_in_badges_returns_five(self):
        assert get_remaining_crafts({}, '730') == 5

    def test_level_zero_returns_five(self):
        badges = {'730': {'level': 0, 'cards_remaining': 5}}
        assert get_remaining_crafts(badges, '730') == 5

    def test_level_three_returns_two(self):
        badges = {'730': {'level': 3, 'cards_remaining': 2}}
        assert get_remaining_crafts(badges, '730') == 2

    def test_level_five_returns_zero(self):
        badges = {'730': {'level': 5, 'cards_remaining': 0}}
        assert get_remaining_crafts(badges, '730') == 0

    def test_appid_coerced_to_string(self):
        badges = {'730': {'level': 2, 'cards_remaining': 3}}
        assert get_remaining_crafts(badges, 730) == 3


class TestCalculateNeeds:
    def test_basic_need_calculation(self):
        hash_names = ['730-Card A', '730-Card B']
        badges = {'730': {'level': 3, 'cards_remaining': 2}}   # remaining=2
        inventory = {'730': {'730-Card A': 1}}                  # A owned=1, B owned=0
        needs = calculate_needs(hash_names, badges, inventory, '730')
        assert needs['730-Card A'] == max(0, 2 - 1)  # 1
        assert needs['730-Card B'] == max(0, 2 - 0)  # 2

    def test_need_zero_when_owned_exceeds_remaining(self):
        hash_names = ['730-Card A']
        badges = {'730': {'level': 4, 'cards_remaining': 1}}   # remaining=1
        inventory = {'730': {'730-Card A': 3}}                  # owned=3 > remaining=1
        needs = calculate_needs(hash_names, badges, inventory, '730')
        assert needs['730-Card A'] == 0

    def test_level_five_all_needs_zero(self):
        hash_names = ['730-Card A', '730-Card B', '730-Card C']
        badges = {'730': {'level': 5, 'cards_remaining': 0}}
        inventory = {}
        needs = calculate_needs(hash_names, badges, inventory, '730')
        assert all(n == 0 for n in needs.values())

    def test_no_inventory_for_game(self):
        hash_names = ['730-Card A']
        badges = {'730': {'level': 0, 'cards_remaining': 5}}   # remaining=5
        inventory = {}                                          # no inventory at all
        needs = calculate_needs(hash_names, badges, inventory, '730')
        assert needs['730-Card A'] == 5

    def test_game_not_in_badges(self):
        hash_names = ['999-Card A']
        badges = {}                                             # game never encountered
        inventory = {}
        needs = calculate_needs(hash_names, badges, inventory, '999')
        assert needs['999-Card A'] == 5  # treated as level 0

    def test_empty_hash_names(self):
        needs = calculate_needs([], {}, {}, '730')
        assert needs == {}

    def test_exact_match_owned_equals_remaining(self):
        hash_names = ['730-Card A']
        badges = {'730': {'level': 3}}                         # remaining=2
        inventory = {'730': {'730-Card A': 2}}                 # owned==remaining
        needs = calculate_needs(hash_names, badges, inventory, '730')
        assert needs['730-Card A'] == 0
