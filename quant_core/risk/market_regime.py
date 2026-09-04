from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths


def _close(frame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["Close"], errors="coerce").dropna()


def _ret(series: pd.Series, days: int):
    if len(series) <= days:
        return None
    return float(series.iloc[-1] / series.iloc[-days - 1] - 1.0)


def build_market_risk_snapshot(histories: Mapping[str, pd.DataFrame], *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    histories = {str(key).upper(): value for key, value in dict(histories or {}).items()}
    spy, qqq, vix = _close(histories.get("SPY")), _close(histories.get("QQQ")), _close(histories.get("^VIX"))
    risk = 25.0
    drivers = []
    spy_20, spy_60 = _ret(spy, 20), _ret(spy, 60)
    if spy_20 is not None and spy_20 < -0.06:
        risk += 22
        drivers.append(f"标普500近20日下跌 {spy_20:.1%}")
    if spy_60 is not None and spy_60 < -0.1:
        risk += 18
        drivers.append(f"标普500近60日趋势偏弱 {spy_60:.1%}")
    if len(spy) >= 200 and float(spy.iloc[-1]) < float(spy.tail(200).mean()):
        risk += 15
        drivers.append("标普500位于200日均线下方")
    latest_vix = float(vix.iloc[-1]) if len(vix) else None
    if latest_vix is not None:
        if latest_vix >= 30:
            risk += 25
            drivers.append(f"VIX处于高压区间 {latest_vix:.1f}")
        elif latest_vix >= 22:
            risk += 12
            drivers.append(f"VIX偏高 {latest_vix:.1f}")
    qqq_20 = _ret(qqq, 20)
    if qqq_20 is not None and spy_20 is not None and qqq_20 - spy_20 < -0.05:
        risk += 8
        drivers.append("成长股相对大盘明显走弱")
    risk = round(max(0.0, min(risk, 100.0)), 1)
    regime = "HIGH_RISK" if risk >= 70 else "CAUTION" if risk >= 48 else "NORMAL"
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY" if len(spy) else "PARTIAL",
        "risk_score": risk,
        "regime": regime,
        "drivers": drivers,
        "metrics": {"spy_return_20d": spy_20, "spy_return_60d": spy_60, "qqq_return_20d": qqq_20, "vix": latest_vix},
    }


def save_market_risk_snapshot(snapshot: Mapping, path: str = qpaths.MARKET_RISK_SNAPSHOT_FILE) -> str:
    import json

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
