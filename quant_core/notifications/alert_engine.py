import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from quant_core import paths as qpaths
from quant_core.events import analyst_consensus as ac
from quant_core.llm import explainer
from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg

qpaths.bootstrap_storage_paths()

ALERT_STATE_FILE = qpaths.ALERT_STATE_FILE
_REGIME_RANK = {"NORMAL": 0, "CAUTION": 1, "RISK_OFF": 2}


@dataclass(frozen=True)
class Alert:
    alert_id: str
    alert_type: str
    severity: str
    title: str
    body: str
    source: str
    dedupe_key: str
    signature: str
    created_at: str
    symbol: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


def _now_iso(now=None):
    return (now or datetime.now()).isoformat()


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_symbols(symbols):
    if symbols is None:
        return None
    return {
        str(symbol).strip().upper()
        for symbol in symbols
        if symbol and str(symbol).strip()
    }


def load_alert_state(path=ALERT_STATE_FILE):
    if not path or not os.path.exists(path):
        return {"sent_alerts": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return {"sent_alerts": {}}
    if not isinstance(state, dict):
        return {"sent_alerts": {}}
    state.setdefault("sent_alerts", {})
    return state


def save_alert_state(state, path=ALERT_STATE_FILE):
    state = state if isinstance(state, dict) else {"sent_alerts": {}}
    state.setdefault("sent_alerts", {})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def format_alert_message(alert: Alert):
    symbol_line = f"\n标的: {alert.symbol}" if alert.symbol else ""
    return (
        f"[{alert.severity.upper()}] {alert.title}"
        f"{symbol_line}\n"
        f"来源: {alert.source}\n"
        f"类型: {alert.alert_type}\n\n"
        f"{alert.body}\n\n"
        f"时间: {alert.created_at}"
    )


def build_analyst_signal_alerts(analyst_cache, symbols=None, now=None) -> List[Alert]:
    now = now or datetime.now()
    created_at = now.isoformat()
    symbol_filter = _normalize_symbols(symbols)
    recommendations = analyst_cache.get("recommendations", {}) if isinstance(analyst_cache, dict) else {}
    alerts = []

    for symbol, record in sorted(recommendations.items()):
        normalized_symbol = str(symbol or "").strip().upper()
        if symbol_filter is not None and normalized_symbol not in symbol_filter:
            continue
        if not ac.is_cached_consensus_fresh(record, now=now):
            continue
        signal = str(record.get("signal") or "").upper()
        if signal not in ("STRONG_BUY", "STRONG_SELL"):
            continue

        bullish_ratio = float(record.get("bullish_ratio") or 0.0)
        bearish_ratio = float(record.get("bearish_ratio") or 0.0)
        total = int(record.get("total") or 0)
        sample_display = str(record.get("sample_display") or total)
        source = str(record.get("source") or "analyst_consensus")
        title_signal = "强烈买入" if signal == "STRONG_BUY" else "强烈卖出"
        alert_type = "ANALYST_STRONG_BUY" if signal == "STRONG_BUY" else "ANALYST_STRONG_SELL"
        severity = "info" if signal == "STRONG_BUY" else "warning"
        body = (
            f"分析师共识触发 {title_signal}。\n"
            f"看多比例: {bullish_ratio:.1%}\n"
            f"看空比例: {bearish_ratio:.1%}\n"
            f"样本数: {sample_display}\n"
            f"原因: {record.get('reason') or '无'}"
        )
        alerts.append(
            Alert(
                alert_id=f"{alert_type}:{normalized_symbol}:{created_at}",
                alert_type=alert_type,
                severity=severity,
                title=f"{normalized_symbol} {title_signal}",
                body=body,
                source=source,
                dedupe_key=f"analyst:{normalized_symbol}",
                signature=signal,
                created_at=created_at,
                symbol=normalized_symbol,
                metadata={"repeat_after_hours": None},
            )
        )
    return alerts


def build_risk_alerts(risk_decision, now=None, min_regime="RISK_OFF") -> List[Alert]:
    if risk_decision is None:
        return []
    regime = str(getattr(risk_decision, "regime", "NORMAL") or "NORMAL").upper()
    if _REGIME_RANK.get(regime, 0) < _REGIME_RANK.get(str(min_regime).upper(), 2):
        return []

    now = now or datetime.now()
    created_at = now.isoformat()
    risk_score = int(getattr(risk_decision, "risk_score", 0) or 0)
    reasons = list(getattr(risk_decision, "reasons", []) or [])
    body = (
        f"风险级别: {regime}\n"
        f"风险评分: {risk_score}\n"
        f"暂停新增仓位: {'是' if getattr(risk_decision, 'block_new_buys', False) else '否'}\n"
        f"单标的仓位上限: {float(getattr(risk_decision, 'max_position_weight', 0.0)):.1%}\n"
        f"原因: {'; '.join(reasons) if reasons else '风险闸门触发'}"
    )
    return [
        Alert(
            alert_id=f"MARKET_{regime}:{created_at}",
            alert_type=f"MARKET_{regime}",
            severity="critical" if regime == "RISK_OFF" else "warning",
            title=f"市场风险进入 {regime}",
            body=body,
            source="risk_gate",
            dedupe_key="market_risk_gate",
            signature=f"{regime}:{risk_score}:{'|'.join(reasons)}",
            created_at=created_at,
            metadata={"repeat_after_hours": 6},
        )
    ]


def collect_alerts(analyst_cache=None, risk_decision=None, symbols=None, now=None) -> List[Alert]:
    alerts = []
    alerts.extend(build_analyst_signal_alerts(analyst_cache or {}, symbols=symbols, now=now))
    alerts.extend(build_risk_alerts(risk_decision, now=now))
    return alerts


def should_send_alert(alert: Alert, state, now=None, default_cooldown_hours=6):
    state = state if isinstance(state, dict) else {"sent_alerts": {}}
    sent_alerts = state.setdefault("sent_alerts", {})
    record = sent_alerts.get(alert.dedupe_key)
    if not record:
        return True
    if record.get("signature") != alert.signature:
        return True

    repeat_after = alert.metadata.get("repeat_after_hours", default_cooldown_hours)
    if repeat_after is None:
        return False
    sent_at = _parse_iso_datetime(record.get("sent_at"))
    if sent_at is None:
        return True
    now = now or datetime.now()
    return (now - sent_at).total_seconds() >= float(repeat_after) * 3600.0


def filter_new_alerts(alerts: Iterable[Alert], state, now=None, default_cooldown_hours=6) -> List[Alert]:
    return [
        alert
        for alert in alerts
        if should_send_alert(alert, state, now=now, default_cooldown_hours=default_cooldown_hours)
    ]


def record_sent_alerts(alerts: Iterable[Alert], state, now=None):
    state = state if isinstance(state, dict) else {"sent_alerts": {}}
    sent_alerts = state.setdefault("sent_alerts", {})
    sent_at = _now_iso(now)
    for alert in alerts:
        sent_alerts[alert.dedupe_key] = {
            "signature": alert.signature,
            "sent_at": sent_at,
            "alert_type": alert.alert_type,
            "title": alert.title,
            "symbol": alert.symbol,
        }
    return state


def _effective_notification_config(config=None, environ=None):
    base = config if config is not None else ncfg.load_notification_config()
    return ncfg.apply_environment_overrides(base, environ=environ)


def _format_alert_for_delivery(alert: Alert, config) -> tuple[str, dict]:
    text = format_alert_message(alert)
    if not bool(dict(config.get("alert_settings", {}) or {}).get("enable_llm_notification_digest", True)):
        return text, {"status": "DISABLED"}
    ok, digest, meta = explainer.summarize_notification_message(
        delivery_type=f"alert:{alert.alert_type}",
        subject=alert.title,
        body=text,
        notification_config=config,
    )
    if ok and str(digest or "").strip():
        return str(digest).strip(), {"status": "READY", **dict(meta or {})}
    return text, {
        "status": "STRUCTURED_FALLBACK",
        "error": str(digest or "").strip(),
        **dict(meta or {}),
    }


def send_alert(alert: Alert, config=None, slack_sender=None, email_sender=None):
    config = _effective_notification_config(config)
    slack_sender = slack_sender or nch.send_slack_message
    email_sender = email_sender or nch.send_email_message
    text, digest_meta = _format_alert_for_delivery(alert, config)
    results = []

    if config["slack"].get("enabled"):
        ok, message = slack_sender(text, config["slack"].get("webhook_url"))
        results.append({"channel": "slack", "ok": ok, "message": message, "alert_id": alert.alert_id, "digest": digest_meta})

    if config["email"].get("enabled"):
        ok, message = email_sender(alert.title, text, config["email"])
        results.append({"channel": "email", "ok": ok, "message": message, "alert_id": alert.alert_id, "digest": digest_meta})

    if not results:
        results.append({"channel": "none", "ok": False, "message": "未启用通知通道", "alert_id": alert.alert_id})
    return results


def send_new_alerts(
    alerts: Iterable[Alert],
    *,
    config=None,
    state_path=ALERT_STATE_FILE,
    now=None,
    slack_sender=None,
    email_sender=None,
):
    config = _effective_notification_config(config)
    cooldown_hours = config.get("alert_settings", {}).get("cooldown_hours", 6)
    state = load_alert_state(state_path)
    new_alerts = filter_new_alerts(alerts, state, now=now, default_cooldown_hours=cooldown_hours)
    results = []
    sent_alerts = []

    for alert in new_alerts:
        alert_results = send_alert(
            alert,
            config=config,
            slack_sender=slack_sender,
            email_sender=email_sender,
        )
        results.extend(alert_results)
        if any(result.get("ok") for result in alert_results):
            sent_alerts.append(alert)

    if sent_alerts:
        record_sent_alerts(sent_alerts, state, now=now)
        save_alert_state(state, state_path)
    return results


def alerts_to_dicts(alerts: Iterable[Alert]):
    return [asdict(alert) for alert in alerts]
