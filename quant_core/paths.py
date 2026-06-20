import os
import shutil
from pathlib import Path
from typing import Iterable, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = PROJECT_ROOT / "storage"
STATE_DIR = STORAGE_DIR / "state"
CONFIG_DIR = STORAGE_DIR / "config"
JOURNALS_DIR = STORAGE_DIR / "journals"
TRAINED_MODELS_DIR = PROJECT_ROOT / "trained_models"
MODEL_ARTIFACTS_DIR = PROJECT_ROOT / "model_artifacts"
BOOTSTRAP_MODELS_DIR = MODEL_ARTIFACTS_DIR / "bootstrap"

PORTFOLIO_DATA_FILE = str(STATE_DIR / "portfolio_data.json")
PORTFOLIO_INPUT_FILE = str(STATE_DIR / "portfolio_input.json")
PRICE_CACHE_FILE = str(STATE_DIR / "price_cache.json")
TRANSACTIONS_FILE = str(STATE_DIR / "transactions.json")
MARKET_EVENTS_FILE = str(STATE_DIR / "market_events.json")
ANALYST_CONSENSUS_CACHE_FILE = str(STATE_DIR / "analyst_consensus_cache.json")
ALERT_STATE_FILE = str(STATE_DIR / "alert_state.json")
NOTIFICATION_CONFIG_FILE = str(CONFIG_DIR / "notification_config.json")
NOTIFICATION_SECRETS_FILE = str(CONFIG_DIR / "notification_secrets.local.json")
COMMAND_AUDIT_FILE = str(STATE_DIR / "command_audit.jsonl")
NEXT_DAY_TRADE_PLAN_FILE = str(STATE_DIR / "next_day_trade_plan.json")
POST_CLOSE_REVIEW_FILE = str(STATE_DIR / "post_close_review.json")
CORE_ETF_SNAPSHOT_FILE = str(STATE_DIR / "core_etf_snapshot.json")
SATELLITE_CANDIDATE_POOL_FILE = str(STATE_DIR / "satellite_candidate_pool.json")
DISCIPLINE_SNAPSHOT_FILE = str(STATE_DIR / "discipline_snapshot.json")
LLM_SUMMARY_CACHE_FILE = str(STATE_DIR / "llm_summary_cache.json")
NIGHTLY_RUN_MANIFEST_FILE = str(STATE_DIR / "nightly_run_manifest.json")
CHANGE_FEED_FILE = str(STATE_DIR / "change_feed_latest.json")
INTRADAY_ALERT_STATE_FILE = str(STATE_DIR / "intraday_alert_state.json")
INTRADAY_EVENT_JOURNAL_FILE = str(STATE_DIR / "intraday_event_journal.jsonl")
INTRADAY_EVENT_ALERT_STATE_FILE = str(STATE_DIR / "intraday_event_alert_state.json")
INTRADAY_TACTICAL_SNAPSHOT_FILE = str(STATE_DIR / "intraday_tactical_snapshot.json")
WEEKEND_RESEARCH_SNAPSHOT_FILE = str(STATE_DIR / "weekend_research_snapshot.json")
WEEKEND_RESEARCH_STATE_FILE = str(STATE_DIR / "weekend_research_state.json")
STRATEGY_VALIDATION_SNAPSHOT_FILE = str(STATE_DIR / "strategy_validation_snapshot.json")
STRATEGY_EXPERIMENT_JOURNAL_FILE = str(STATE_DIR / "strategy_experiment_journal.jsonl")
NIGHTLY_DECISION_JOURNAL_FILE = str(STATE_DIR / "nightly_decision_journal.jsonl")
DATA_HEALTH_SNAPSHOT_FILE = str(STATE_DIR / "data_health_snapshot.json")
PLAN_QUALITY_SNAPSHOT_FILE = str(STATE_DIR / "plan_quality_snapshot.json")
MARKET_MONITOR_SNAPSHOT_FILE = str(STATE_DIR / "market_monitor_snapshot.json")
STRATEGY_REGISTRY_STATE_FILE = str(STATE_DIR / "strategy_registry_state.json")
MULTI_HORIZON_SNAPSHOT_FILE = str(STATE_DIR / "multi_horizon_snapshot.json")
MULTI_HORIZON_VALIDATION_FILE = str(STATE_DIR / "multi_horizon_validation.json")
MULTI_HORIZON_PANEL_FILE = str(STATE_DIR / "multi_horizon_panel.parquet")
MULTI_HORIZON_GOVERNANCE_FILE = str(STATE_DIR / "multi_horizon_governance.json")
MULTI_HORIZON_PREDICTION_JOURNAL_FILE = str(JOURNALS_DIR / "multi_horizon_predictions.jsonl")
WEEKEND_RESEARCH_JOURNAL_FILE = str(JOURNALS_DIR / "weekend_research_journal.jsonl")

MARKET_EVENTS_EXAMPLE_FILE = str(CONFIG_DIR / "market_events.example.json")
NOTIFICATION_CONFIG_EXAMPLE_FILE = str(CONFIG_DIR / "notification_config.example.json")
PORTFOLIO_INPUT_EXAMPLE_FILE = str(CONFIG_DIR / "portfolio_input.example.json")
CORE_ETF_UNIVERSE_FILE = str(CONFIG_DIR / "core_etf_universe.json")
SATELLITE_UNIVERSE_FILE = str(CONFIG_DIR / "satellite_universe.json")
ENGINE_POLICY_FILE = str(CONFIG_DIR / "engine_policy.json")
INTRADAY_TACTICAL_CONFIG_FILE = str(CONFIG_DIR / "intraday_tactical_overlay.json")
RUNTIME_SCHEDULE_CONFIG_FILE = str(CONFIG_DIR / "runtime_schedule.json")
MODEL_REGISTRY_CONFIG_FILE = str(CONFIG_DIR / "model_registry.json")
MULTI_HORIZON_MODEL_CONFIG_FILE = str(CONFIG_DIR / "multi_horizon_model.json")
MULTI_HORIZON_CHECKPOINT_FILE = str(TRAINED_MODELS_DIR / "finance_multi_asset_transformer.pt")
MULTI_HORIZON_PRETRAIN_CHECKPOINT_FILE = str(TRAINED_MODELS_DIR / "finance_multi_asset_transformer_pretrain.pt")
MULTI_HORIZON_BOOTSTRAP_CHECKPOINT_FILE = str(BOOTSTRAP_MODELS_DIR / "finance_multi_asset_transformer.pt")
MULTI_HORIZON_BOOTSTRAP_MANIFEST_FILE = str(BOOTSTRAP_MODELS_DIR / "manifest.json")
JOB_STATUS_FILE = str(STATE_DIR / "job_status.json")

EVENT_SOURCES_CONFIG_FILE = str(PROJECT_ROOT / "config" / "event_sources.json")
STRATEGY_CONFIG_FILE = str(PROJECT_ROOT / "config" / "strategies.json")

LEGACY_TO_NEW_FILE_MAP = (
    (str(STATE_DIR / "notification_config.json"), NOTIFICATION_CONFIG_FILE),
    ("portfolio_data.json", PORTFOLIO_DATA_FILE),
    ("portfolio_input.json", PORTFOLIO_INPUT_FILE),
    ("price_cache.json", PRICE_CACHE_FILE),
    ("transactions.json", TRANSACTIONS_FILE),
    ("market_events.json", MARKET_EVENTS_FILE),
    ("analyst_consensus_cache.json", ANALYST_CONSENSUS_CACHE_FILE),
    ("alert_state.json", ALERT_STATE_FILE),
    ("notification_config.json", NOTIFICATION_CONFIG_FILE),
    ("command_audit.jsonl", COMMAND_AUDIT_FILE),
    ("market_events.example.json", MARKET_EVENTS_EXAMPLE_FILE),
    ("notification_config.example.json", NOTIFICATION_CONFIG_EXAMPLE_FILE),
    ("portfolio_input.example.json", PORTFOLIO_INPUT_EXAMPLE_FILE),
)


_BOOTSTRAPPED = False


def _ensure_parent(path: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def ensure_storage_layout():
    os.makedirs(str(STATE_DIR), exist_ok=True)
    os.makedirs(str(CONFIG_DIR), exist_ok=True)
    os.makedirs(str(JOURNALS_DIR), exist_ok=True)
    os.makedirs(str(TRAINED_MODELS_DIR), exist_ok=True)


def migrate_legacy_files(file_map: Iterable[Tuple[str, str]] = LEGACY_TO_NEW_FILE_MAP):
    for legacy_path, new_path in file_map:
        if os.path.isabs(legacy_path):
            src = legacy_path
        else:
            src = str(PROJECT_ROOT / legacy_path)
        dst = str(new_path)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            continue
        _ensure_parent(dst)
        shutil.move(src, dst)


def bootstrap_storage_paths():
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    ensure_storage_layout()
    migrate_legacy_files()
    _BOOTSTRAPPED = True
