"""Fundamental-data intelligence adapters.

This package turns financial statements and earnings metadata into structured
signals. The data layer is intentionally source-aware: missing ETF/company data
is marked as missing instead of being treated as a bearish signal.
"""

from quant_core.fundamentals.financials import (
    build_financials_intelligence,
    load_financials_config,
    load_financials_intelligence,
    save_financials_config,
    save_financials_intelligence,
)

__all__ = [
    "build_financials_intelligence",
    "load_financials_config",
    "load_financials_intelligence",
    "save_financials_config",
    "save_financials_intelligence",
]
