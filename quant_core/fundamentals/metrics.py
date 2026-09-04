from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping, Optional


TAG_ALIASES = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
}

DEBT_TAG_PAIRS = (
    ("LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
    ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
)


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _facts(payload: Mapping, namespace: str, tag: str) -> list[dict]:
    record = dict(dict(dict(payload.get("facts", {}) or {}).get(namespace, {}) or {}).get(tag, {}) or {})
    units = dict(record.get("units", {}) or {})
    preferred = ("USD", "shares", "USD/shares", "pure")
    for unit in preferred:
        rows = units.get(unit)
        if isinstance(rows, list):
            return [dict(row or {}) for row in rows]
    for rows in units.values():
        if isinstance(rows, list):
            return [dict(row or {}) for row in rows]
    return []


def _available_rows(payload: Mapping, tags, *, as_of: datetime, namespace="us-gaap") -> list[dict]:
    for tag in tags:
        rows = []
        for row in _facts(payload, namespace, tag):
            filed = _date(row.get("filed"))
            value = _finite(row.get("val"))
            if value is None or filed is None or filed > as_of:
                continue
            rows.append({**row, "val": value, "tag": tag, "filed_dt": filed})
        if rows:
            return rows
    return []


def _duration_days(row: Mapping):
    start, end = _date(row.get("start")), _date(row.get("end"))
    return (end - start).days if start and end else None


def _duration_metric(payload: Mapping, tags, *, as_of: datetime):
    rows = _available_rows(payload, tags, as_of=as_of)
    annual = [row for row in rows if str(row.get("form") or "").upper() in {"10-K", "20-F", "40-F"} and (_duration_days(row) or 0) >= 300]
    annual.sort(key=lambda row: (_date(row.get("end")) or datetime.min, row.get("filed_dt") or datetime.min))
    unique = []
    seen = set()
    for row in reversed(annual):
        key = str(row.get("end") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    quarterly = [row for row in rows if 60 <= (_duration_days(row) or 0) <= 120]
    quarterly.sort(key=lambda row: (_date(row.get("end")) or datetime.min, row.get("filed_dt") or datetime.min))
    deduped = []
    seen = set()
    for row in reversed(quarterly):
        key = str(row.get("end") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    if len(deduped) >= 4 and (not unique or _date(deduped[0].get("end")) > _date(unique[0].get("end"))):
        latest_rows = deduped[:4]
        prior_rows = deduped[4:8]
        return (
            sum(row["val"] for row in latest_rows),
            sum(row["val"] for row in prior_rows) if len(prior_rows) == 4 else None,
            latest_rows[0],
        )
    if unique:
        latest = unique[0]
        previous = unique[1] if len(unique) > 1 else None
        return latest["val"], previous["val"] if previous else None, latest
    return (None, None, None)


def _instant_metric(payload: Mapping, tags, *, as_of: datetime, namespace="us-gaap"):
    rows = _available_rows(payload, tags, as_of=as_of, namespace=namespace)
    rows.sort(key=lambda row: (_date(row.get("end")) or datetime.min, row.get("filed_dt") or datetime.min))
    return (rows[-1]["val"], rows[-1]) if rows else (None, None)


def _debt_metric(payload: Mapping, *, as_of: datetime):
    for current_tag, noncurrent_tag in DEBT_TAG_PAIRS:
        current, current_row = _instant_metric(payload, (current_tag,), as_of=as_of)
        noncurrent, noncurrent_row = _instant_metric(payload, (noncurrent_tag,), as_of=as_of)
        if current is not None or noncurrent is not None:
            return float(current or 0.0) + float(noncurrent or 0.0), [row for row in (current_row, noncurrent_row) if row]
    value, row = _instant_metric(payload, ("LongTermDebt",), as_of=as_of)
    return value, [row] if row else []


def _growth(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / abs(float(previous))


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _scores(metrics: Mapping) -> tuple[float, float, float, list[str]]:
    quality = 45.0
    damage = 10.0
    drivers = []
    fcf = _finite(metrics.get("free_cash_flow"))
    revenue = _finite(metrics.get("revenue"))
    net_income = _finite(metrics.get("net_income"))
    cash = _finite(metrics.get("cash"), 0.0)
    debt = _finite(metrics.get("total_debt"), 0.0)
    revenue_growth = _finite(metrics.get("revenue_growth"))
    fcf_growth = _finite(metrics.get("free_cash_flow_growth"))
    margin = _finite(metrics.get("operating_margin"))
    if fcf is not None and fcf > 0:
        quality += 16
    elif fcf is not None:
        damage += 25
        drivers.append("free_cash_flow_negative")
    if net_income is not None and net_income > 0:
        quality += 8
    if margin is not None and margin >= 0.15:
        quality += 12
    elif margin is not None and margin < 0:
        damage += 18
        drivers.append("operating_margin_negative")
    if revenue_growth is not None:
        if revenue_growth >= 0.05:
            quality += 10
        elif revenue_growth < -0.05:
            damage += 20
            drivers.append("revenue_contracting")
    if fcf_growth is not None and fcf_growth < -0.25:
        damage += 18
        drivers.append("free_cash_flow_deteriorating")
    debt_to_fcf = debt / max(fcf or 0.0, 1.0) if debt > 0 else 0.0
    if cash >= debt:
        quality += 7
    elif debt_to_fcf > 5:
        damage += 15
        drivers.append("debt_burden_high")
    distress = 0.03 + max(damage - 20, 0) / 125
    if revenue in (None, 0):
        distress += 0.08
    return min(quality, 100.0), min(damage, 100.0), min(distress, 0.95), drivers


def normalize_sec_company_facts(payload: Mapping, *, symbol: str, as_of: Optional[datetime] = None) -> dict:
    as_of = (as_of or datetime.now()).replace(tzinfo=None)
    metrics = {}
    evidence = []
    latest_row = None
    for name in ("revenue", "operating_income", "net_income", "operating_cash_flow", "capital_expenditure"):
        current, previous, row = _duration_metric(payload, TAG_ALIASES[name], as_of=as_of)
        metrics[name] = abs(current) if name == "capital_expenditure" and current is not None else current
        metrics[f"{name}_previous"] = abs(previous) if name == "capital_expenditure" and previous is not None else previous
        if row:
            latest_row = row if latest_row is None or str(row.get("end")) > str(latest_row.get("end")) else latest_row
            evidence.append({"metric": name, "tag": row.get("tag"), "period_end": row.get("end"), "filed": row.get("filed"), "form": row.get("form")})
    for name in ("cash", "equity"):
        value, row = _instant_metric(payload, TAG_ALIASES[name], as_of=as_of)
        metrics[name] = value
        if row:
            evidence.append({"metric": name, "tag": row.get("tag"), "period_end": row.get("end"), "filed": row.get("filed"), "form": row.get("form")})
    metrics["total_debt"], debt_rows = _debt_metric(payload, as_of=as_of)
    for row in debt_rows:
        evidence.append({"metric": "total_debt", "tag": row.get("tag"), "period_end": row.get("end"), "filed": row.get("filed"), "form": row.get("form")})
    shares, share_row = _instant_metric(
        payload,
        ("EntityCommonStockSharesOutstanding",),
        as_of=as_of,
        namespace="dei",
    )
    metrics["shares_outstanding"] = shares
    if share_row:
        evidence.append({"metric": "shares_outstanding", "tag": share_row.get("tag"), "period_end": share_row.get("end"), "filed": share_row.get("filed"), "form": share_row.get("form")})
    ocf, capex = metrics.get("operating_cash_flow"), metrics.get("capital_expenditure")
    metrics["free_cash_flow"] = ocf - capex if ocf is not None and capex is not None else None
    previous_ocf, previous_capex = metrics.get("operating_cash_flow_previous"), metrics.get("capital_expenditure_previous")
    previous_fcf = previous_ocf - previous_capex if previous_ocf is not None and previous_capex is not None else None
    metrics["revenue_growth"] = _growth(metrics.get("revenue"), metrics.get("revenue_previous"))
    metrics["net_income_growth"] = _growth(metrics.get("net_income"), metrics.get("net_income_previous"))
    metrics["free_cash_flow_growth"] = _growth(metrics.get("free_cash_flow"), previous_fcf)
    metrics["operating_margin"] = _ratio(metrics.get("operating_income"), metrics.get("revenue"))
    metrics["free_cash_flow_margin"] = _ratio(metrics.get("free_cash_flow"), metrics.get("revenue"))
    quality, damage, distress, drivers = _scores(metrics)
    return {
        "symbol": str(symbol or "").strip().upper(),
        "company_name": str(payload.get("entityName") or symbol),
        "asset_type": "equity",
        "status": "READY" if metrics.get("revenue") is not None else "PARTIAL",
        "source": "sec_companyfacts",
        "retrieved_at": as_of.isoformat(),
        "fiscal_period": str((latest_row or {}).get("end") or ""),
        **{key: value for key, value in metrics.items() if not key.endswith("_previous")},
        "quality_score": round(quality, 1),
        "damage_score": round(damage, 1),
        "distress_probability": round(distress, 3),
        "damage_drivers": drivers,
        "evidence": evidence,
    }
