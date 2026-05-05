from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class PortfolioSummary:
    total_cost: float = 0.0
    priced_cost: float = 0.0
    total_value: float = 0.0
    total_pl: float = 0.0
    total_pl_pct: float = 0.0
    missing_price_count: int = 0
    priced_positions: int = 0


def summarize_holdings(holdings: Iterable[Mapping[str, Any]]) -> PortfolioSummary:
    total_cost = 0.0
    priced_cost = 0.0
    total_value = 0.0
    missing_price_count = 0
    priced_positions = 0

    for holding in holdings:
        shares = float(holding["shares"])
        cost = float(holding["cost"])
        current_price = holding.get("current_price")

        total_cost += shares * cost

        if current_price is None:
            missing_price_count += 1
            continue

        priced_positions += 1
        priced_cost += shares * cost
        total_value += shares * float(current_price)

    total_pl = total_value - priced_cost
    total_pl_pct = (total_pl / priced_cost * 100.0) if priced_cost else 0.0

    return PortfolioSummary(
        total_cost=total_cost,
        priced_cost=priced_cost,
        total_value=total_value,
        total_pl=total_pl,
        total_pl_pct=total_pl_pct,
        missing_price_count=missing_price_count,
        priced_positions=priced_positions,
    )

