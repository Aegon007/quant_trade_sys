"""Market dislocation detection and opportunity scoring."""

from quant_core.opportunities.dislocation import measure_dislocation
from quant_core.opportunities.scoring import score_opportunity

__all__ = ["measure_dislocation", "score_opportunity"]
