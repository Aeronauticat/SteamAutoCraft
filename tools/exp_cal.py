"""
Steam 等级经验计算工具

规则：第 k 段（第 10k-9 至 10k 级）每升一级需 k*100 XP。
每个徽章提供 100 XP。
"""


def _total_xp(level: int) -> int:
    """从 0 升到指定等级所需的累计 XP（level 需为 10 的倍数）。"""
    k = level // 10
    return 500 * k * (k + 1)


def _xp_for_next_level(level: int) -> int:
    """从当前等级升到下一级所需 XP（level 从 0 开始计）。"""
    k = (level // 10) + 1
    return k * 100


def calc_exp(current_level: int, target_level: int) -> dict:
    """
    计算从当前等级升到目标等级所需的经验和徽章数量。

    :param current_level: 当前等级（>=0）
    :param target_level:  目标等级（> current_level）
    :return: {"xp": int, "badges": int}
    """
    if current_level < 0:
        raise ValueError("当前等级不能为负数")
    if target_level <= current_level:
        raise ValueError("目标等级必须大于当前等级")

    xp = 0
    for lvl in range(current_level, target_level):
        xp += _xp_for_next_level(lvl)

    return {
        "xp": xp,
        "badges": xp // 100,
    }


def calc_target_level(current_level: int, badges: int) -> dict:
    """
    根据当前等级和可合成的徽章数量，计算能升到的目标等级。

    :param current_level: 当前等级（>=0）
    :param badges:        可合成徽章数量（每个 100 XP）
    :return: {"target_level": int, "xp_used": int, "xp_remaining": int}
    """
    if current_level < 0:
        raise ValueError("当前等级不能为负数")
    if badges < 0:
        raise ValueError("徽章数量不能为负数")

    remaining_xp = badges * 100
    level = current_level

    while True:
        needed = _xp_for_next_level(level)
        if remaining_xp < needed:
            break
        remaining_xp -= needed
        level += 1

    return {
        "target_level": level,
        "xp_used": badges * 100 - remaining_xp,
        "xp_remaining": remaining_xp,
    }


if __name__ == "__main__":
    # 示例：300 升 600
    result = calc_exp(300, 600)
    print(f"300 → 600: {result['xp']:,} XP，需 {result['badges']:,} 个徽章")

    # 示例：当前 300 级，有 13650 个徽章
    result2 = calc_target_level(300, 13650)
    print(f"300 级 + 13650 徽章 → {result2['target_level']} 级，"
          f"剩余 {result2['xp_remaining']} XP")
