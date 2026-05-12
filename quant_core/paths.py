import os
import shutil
from pathlib import Path
from typing import Iterable, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = PROJECT_ROOT / "storage"
STATE_DIR = STORAGE_DIR / "state"
CONFIG_DIR = STORAGE_DIR / "config"

PORTFOLIO_DATA_FILE = str(STATE_DIR / "portfolio_data.json")
PORTFOLIO_INPUT_FILE = str(STATE_DIR / "portfolio_input.json")
PRICE_CACHE_FILE = str(STATE_DIR / "price_cache.json")
TRANSACTIONS_FILE = str(STATE_DIR / "transactions.json")
MARKET_EVENTS_FILE = str(STATE_DIR / "market_events.json")
ANALYST_CONSENSUS_CACHE_FILE = str(STATE_DIR / "analyst_consensus_cache.json")
ALERT_STATE_FILE = str(STATE_DIR / "alert_state.json")
NOTIFICATION_CONFIG_FILE = str(STATE_DIR / "notification_config.json")
COMMAND_AUDIT_FILE = str(STATE_DIR / "command_audit.jsonl")
QUANT_ANALYSIS_SNAPSHOT_FILE = str(STATE_DIR / "quant_analysis_snapshot.json")

MARKET_EVENTS_EXAMPLE_FILE = str(CONFIG_DIR / "market_events.example.json")
NOTIFICATION_CONFIG_EXAMPLE_FILE = str(CONFIG_DIR / "notification_config.example.json")
PORTFOLIO_INPUT_EXAMPLE_FILE = str(CONFIG_DIR / "portfolio_input.example.json")

EVENT_SOURCES_CONFIG_FILE = str(PROJECT_ROOT / "config" / "event_sources.json")
STRATEGY_CONFIG_FILE = str(PROJECT_ROOT / "config" / "strategies.json")

LEGACY_TO_NEW_FILE_MAP = (
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
