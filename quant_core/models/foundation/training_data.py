from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from quant_core import paths as qpaths


DEFAULT_TRAINING_OBSERVATIONS_FILE = qpaths.FOUNDATION_TRAINING_OBSERVATIONS_FILE


def _history_rows(
    histories: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    captured_at: datetime,
    model_name: str = "",
) -> list[dict]:
    rows: list[dict] = []
    captured_iso = captured_at.isoformat()
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        frame = histories.get(symbol)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        working = frame.copy()
        if not isinstance(working.index, pd.DatetimeIndex):
            working.index = pd.to_datetime(working.index, errors="coerce")
        working = working[~working.index.isna()].sort_index()
        for timestamp, row in working.iterrows():
            close = pd.to_numeric(pd.Series([row.get("Close")]), errors="coerce").iloc[0]
            if pd.isna(close):
                continue
            rows.append(
                {
                    "captured_at": captured_iso,
                    "symbol": symbol,
                    "timestamp": pd.Timestamp(timestamp).normalize(),
                    "open": pd.to_numeric(pd.Series([row.get("Open")]), errors="coerce").iloc[0],
                    "high": pd.to_numeric(pd.Series([row.get("High")]), errors="coerce").iloc[0],
                    "low": pd.to_numeric(pd.Series([row.get("Low")]), errors="coerce").iloc[0],
                    "close": float(close),
                    "volume": pd.to_numeric(pd.Series([row.get("Volume")]), errors="coerce").iloc[0],
                    "model_name": str(model_name or ""),
                    "source": "foundation_history",
                }
            )
    return rows


def append_training_observations(
    histories: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    captured_at: datetime | None = None,
    model_name: str = "",
    retention_days: int = 1825,
    path: str = DEFAULT_TRAINING_OBSERVATIONS_FILE,
) -> dict:
    captured_at = captured_at or datetime.now()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    new_frame = pd.DataFrame(
        _history_rows(histories, symbols=symbols, captured_at=captured_at, model_name=model_name)
    )
    if new_frame.empty:
        return {
            "status": "NO_DATA",
            "path": str(target),
            "rows": 0,
            "symbol_count": 0,
            "retention_days": int(retention_days),
        }

    frames = [new_frame]
    if target.exists():
        try:
            existing = pd.read_parquet(target)
            if isinstance(existing, pd.DataFrame) and not existing.empty:
                frames.insert(0, existing)
        except Exception:
            pass
    combined = pd.concat(frames, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], errors="coerce")
    combined = combined.dropna(subset=["symbol", "timestamp", "close"])
    cutoff = pd.Timestamp(captured_at - timedelta(days=max(int(retention_days or 0), 1))).normalize()
    combined = combined[combined["timestamp"] >= cutoff]
    combined = combined.sort_values(["symbol", "timestamp", "captured_at"])
    combined = combined.drop_duplicates(subset=["symbol", "timestamp"], keep="last")
    combined.to_parquet(target, index=False)
    return {
        "status": "READY",
        "path": str(target),
        "rows": int(len(combined)),
        "new_rows": int(len(new_frame)),
        "symbol_count": int(combined["symbol"].nunique()),
        "retention_days": int(retention_days),
        "oldest_timestamp": combined["timestamp"].min().date().isoformat() if not combined.empty else None,
        "latest_timestamp": combined["timestamp"].max().date().isoformat() if not combined.empty else None,
    }
