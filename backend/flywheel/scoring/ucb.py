from __future__ import annotations

import math


def ucb_bonus(n_obs: int, total_rounds: int, c: float = 1.0) -> float:
    if total_rounds <= 0:
        return 0.5
    return c * math.sqrt(math.log(total_rounds + 1) / (n_obs + 1))

