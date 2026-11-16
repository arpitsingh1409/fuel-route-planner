"""Choose where to fuel and how much.

By default (stop_cost 0) the plan is the strictly cheapest fuel bill. The API caller may
also set a cost per stop, trading a slightly dearer bill for fewer stops: the plan then
minimises fuel cost plus stop_cost for every stop made.

It is solved exactly as a dynamic programme over the fuel level in whole miles:
cost[f] is the cheapest way to be at the current position holding f miles of fuel.
"""

from collections.abc import Sequence

import numpy as np

from fuel.exceptions import NoFeasiblePlan


def plan_fuel_stops(
    miles: Sequence[int],
    prices: Sequence[float],
    total_miles: int,
    *,
    tank_miles: int,
    start_miles: int,
    mpg: float,
    stop_cost: float,
) -> list[tuple[int, int]]:
    """Return (station index, miles of fuel to buy) for each stop, in route order.

    miles: whole-mile position of each station along the route, ascending.
    prices: dollars per gallon at each station.
    start_miles: fuel in the tank at the start, as miles of range.
    """
    levels = np.arange(tank_miles + 1)
    cost = np.full(tank_miles + 1, np.inf)
    cost[min(start_miles, tank_miles)] = 0.0
    arrived_with = []  # per station: for each level after buying, the level before buying
    position = 0
    for mile, price in zip(miles, prices):
        cost = _drive(cost, mile - position)
        position = mile
        per_mile = price / mpg
        # Buying up from level e to f costs cost[e] + (f - e) * per_mile. The best e for
        # each f is a running minimum of cost[e] - e * per_mile, so a station is O(tank).
        net = cost - levels * per_mile
        best = np.minimum.accumulate(net)
        came_from = np.maximum.accumulate(np.where(net == best, levels, 0))
        bought = best + levels * per_mile + stop_cost
        buy = bought < cost
        arrived_with.append(np.where(buy, came_from, levels))
        cost = np.where(buy, bought, cost)

    last_leg = total_miles - position
    cost = _drive(cost, last_leg)
    if not np.isfinite(cost).any():
        raise NoFeasiblePlan()

    # Walk back from the cheapest finish to recover what was bought where.
    level = int(np.argmin(cost)) + last_leg
    stops = []
    for i in range(len(arrived_with) - 1, -1, -1):
        before = int(arrived_with[i][level])
        if before < level:
            stops.append((i, level - before))
        level = before + miles[i] - (miles[i - 1] if i else 0)
    return stops[::-1]


def _drive(cost: np.ndarray, gap: int) -> np.ndarray:
    """Burn `gap` miles of fuel: level f now is what level f + gap was."""
    after = np.full_like(cost, np.inf)
    if gap < len(cost):
        after[: len(cost) - gap] = cost[gap:]
    return after
