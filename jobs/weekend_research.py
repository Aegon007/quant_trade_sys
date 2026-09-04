from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.data.prices import get_history
from quant_core.notifications import notification_config
from quant_core.notifications.delivery_router import deliver_message
from quant_core.research.calibration import calibrate_recommendations, load_recommendation_journal, save_calibration


def _read_json(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _peer_distributions(valuations: Mapping) -> dict:
    groups = {}
    for row in list(dict(valuations or {}).get("valuations", []) or []):
        archetype = str(row.get("archetype") or "unknown")
        value = row.get("margin_of_safety")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        groups.setdefault(archetype, []).append(value)
    return {
        key: {"count": len(values), "median_margin_of_safety": round(median(values), 4), "min": round(min(values), 4), "max": round(max(values), 4)}
        for key, values in groups.items()
    }


def run_weekend_research(*, force=False, progress=None, notify=True, now: Optional[datetime] = None):
    now = now or datetime.now()
    progress = progress or (lambda *_args, **_kwargs: None)
    progress("load_history", 5, "读取推荐历史")
    journal = load_recommendation_journal()
    progress("calibrate", 20, "校准3、6、12和24个月推荐表现")
    calibration = calibrate_recommendations(journal, history_loader=get_history, now=now)
    progress("peer_statistics", 78, "更新估值类型横截面分布")
    valuations = _read_json(qpaths.VALUATION_SNAPSHOT_FILE)
    calibration["peer_distributions"] = _peer_distributions(valuations)
    calibration["methodology"] = {
        "market_benchmark": "SPY",
        "risk_free_benchmark": "SGOV",
        "horizons_days": [63, 126, 252, 504],
        "note": "只使用系统当时已记录的推荐，同时衡量是否超过无风险收益和是否取得市场超额。",
    }
    save_calibration(calibration)
    lines = [
        "# 周末估值策略校准",
        "",
        f"生成时间：{now.isoformat()}",
        f"成熟观察数：{calibration['summary']['matured_observation_count']}",
        "",
    ]
    for horizon, row in calibration["horizons"].items():
        lines.append(
            f"- {horizon}交易日：样本{row['count']}，跑赢短债比例{row['risk_free_win_rate']}，"
            f"跑赢SPY比例{row['market_win_rate']}，对短债中位超额{row['median_excess_over_risk_free']}，"
            f"对SPY中位超额{row['median_excess_over_market']}"
        )
    report = "\n".join(lines) + "\n"
    report_path = qpaths.PROJECT_ROOT / "reports" / "weekend_valuation_latest.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    delivery = []
    if notify:
        delivery = deliver_message("weekend_calibration", subject="周末估值策略校准", body=report, config=notification_config.load_notification_config())
    progress("completed", 100, "周末校准完成")
    return {"ran": True, "status": calibration["status"], "summary": calibration["summary"], "delivery": delivery}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run_weekend_research(force=args.force, notify=not args.no_notify), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
