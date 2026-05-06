from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class SectorExposure:
    sector: str
    value: float
    weight_pct: float


@dataclass(frozen=True)
class CorrelationAlert:
    symbols: Tuple[str, str]
    correlation: float
    combined_weight_pct: float


@dataclass(frozen=True)
class PortfolioRiskAdvice:
    total_value: float
    sector_exposures: List[SectorExposure] = field(default_factory=list)
    sector_alerts: List[SectorExposure] = field(default_factory=list)
    correlation_alerts: List[CorrelationAlert] = field(default_factory=list)
    unpriced_symbols: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


def _holding_value(holding: Mapping) -> Optional[float]:
    price = holding.get("current_price")
    if price is None:
        return None
    return float(holding.get("shares", 0.0)) * float(price)


def _holding_sector(holding: Mapping) -> str:
    return str(holding.get("sector") or holding.get("industry") or "Unknown").strip() or "Unknown"


def analyze_portfolio_risk(
    holdings: Iterable[Mapping],
    correlation_matrix: Optional[pd.DataFrame] = None,
    sector_limit: float = 0.35,
    correlation_threshold: float = 0.75,
) -> PortfolioRiskAdvice:
    sector_values = {}
    symbol_values = {}
    unpriced_symbols = []

    for holding in holdings:
        symbol = holding.get("symbol", "")
        value = _holding_value(holding)
        if value is None:
            if symbol:
                unpriced_symbols.append(symbol)
            continue

        sector = _holding_sector(holding)
        sector_values[sector] = sector_values.get(sector, 0.0) + value
        symbol_values[symbol] = symbol_values.get(symbol, 0.0) + value

    total_value = sum(symbol_values.values())
    if total_value <= 0:
        return PortfolioRiskAdvice(total_value=0.0, unpriced_symbols=unpriced_symbols)

    sector_exposures = [
        SectorExposure(sector=sector, value=value, weight_pct=value / total_value * 100.0)
        for sector, value in sorted(sector_values.items(), key=lambda item: item[1], reverse=True)
    ]
    sector_alerts = [
        exposure
        for exposure in sector_exposures
        if exposure.sector != "Unknown" and exposure.weight_pct > sector_limit * 100.0
    ]

    correlation_alerts = []
    if correlation_matrix is not None and not correlation_matrix.empty:
        symbols = [symbol for symbol in correlation_matrix.columns if symbol in symbol_values]
        for left_index, left_symbol in enumerate(symbols):
            for right_symbol in symbols[left_index + 1:]:
                corr_value = correlation_matrix.loc[left_symbol, right_symbol]
                if pd.isna(corr_value):
                    continue
                corr_value = float(corr_value)
                if corr_value >= correlation_threshold:
                    combined_weight = (symbol_values[left_symbol] + symbol_values[right_symbol]) / total_value * 100.0
                    correlation_alerts.append(
                        CorrelationAlert(
                            symbols=(left_symbol, right_symbol),
                            correlation=corr_value,
                            combined_weight_pct=combined_weight,
                        )
                    )

    recommendations = []
    for alert in sector_alerts:
        recommendations.append(
            f"{alert.sector} 板块占已定价组合市值 {alert.weight_pct:.1f}%，集中度偏高，可考虑减仓或增加其他板块暴露。"
        )
    for alert in correlation_alerts:
        left_symbol, right_symbol = alert.symbols
        recommendations.append(
            f"{left_symbol}/{right_symbol} 相关性 {alert.correlation:.2f}，合计仓位 {alert.combined_weight_pct:.1f}%，避免同时继续加仓。"
        )
    if unpriced_symbols:
        recommendations.append(
            f"{', '.join(unpriced_symbols)} 缺少现价，组合级建议暂未纳入这些标的。"
        )

    return PortfolioRiskAdvice(
        total_value=total_value,
        sector_exposures=sector_exposures,
        sector_alerts=sector_alerts,
        correlation_alerts=correlation_alerts,
        unpriced_symbols=unpriced_symbols,
        recommendations=recommendations,
    )
