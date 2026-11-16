"""Choose where to fuel and how much, for the lowest fuel bill.

For a fixed route this has a simple exact answer. At each station:
  - if a cheaper station is within range, buy just enough to reach it;
  - otherwise fill the tank.
Fuel is only ever bought where nothing cheaper could have supplied it, which is why the
rule is optimal. The tests check it against trying every possible purchase.
"""

from collections.abc import Sequence

from fuel.exceptions import NoFeasiblePlan

_TOLERANCE = 1e-9  # miles; absorbs floating-point noise


def plan_fuel_stops(
    miles: Sequence[float],
    prices: Sequence[float],
    total_miles: float,
    *,
    tank_miles: float,
    start_miles: float,
) -> list[tuple[int, float]]:
    """Return (station index, miles of fuel to buy) for each stop, in route order.

    miles: position of each station along the route, ascending.
    prices: dollars per gallon at each station.
    start_miles: fuel in the tank at the start, as miles of range.
    """
    # The destination acts as a free station: being "cheaper" than everything, it makes
    # the last purchases just enough to arrive rather than a full tank.
    stop_miles, stop_prices = [*miles, total_miles], [*prices, 0.0]
    cheaper = _next_cheaper(stop_prices)

    fuel, position, stops = start_miles, 0.0, []
    for i, mile in enumerate(miles):
        fuel -= mile - position
        position = mile
        if fuel < -_TOLERANCE:
            raise NoFeasiblePlan()
        reach = stop_miles[cheaper[i]] - mile
        buy = min(reach, tank_miles) - fuel  # beyond range means there is nothing cheaper: fill up
        if buy > _TOLERANCE:
            stops.append((i, buy))
            fuel += buy
    if fuel - (total_miles - position) < -_TOLERANCE:
        raise NoFeasiblePlan()
    return stops


def _next_cheaper(prices: Sequence[float]) -> list[int]:
    """For each index, the next index with a strictly lower price (the last index if none)."""
    result, waiting = [len(prices) - 1] * len(prices), []
    for j, price in enumerate(prices):
        while waiting and price < prices[waiting[-1]]:
            result[waiting.pop()] = j
        waiting.append(j)
    return result
