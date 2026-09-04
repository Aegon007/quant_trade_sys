"""Canonical paths for the single-user valuation research system."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = PROJECT_ROOT / "storage"
STATE_DIR = STORAGE_DIR / "state"
CONFIG_DIR = STORAGE_DIR / "config"
JOURNALS_DIR = STORAGE_DIR / "journals"
REPORTS_DIR = PROJECT_ROOT / "reports"
RESEARCH_STATE_DIR = STATE_DIR / "valuation_radar"
RESEARCH_JOURNALS_DIR = JOURNALS_DIR / "valuation_radar"
RESEARCH_CACHE_DIR = STORAGE_DIR / "cache" / "valuation_radar"

NOTIFICATION_CONFIG_FILE = str(CONFIG_DIR / "notification_config.json")
NOTIFICATION_SECRETS_FILE = str(CONFIG_DIR / "notification_secrets.local.json")
RUNTIME_SCHEDULE_CONFIG_FILE = str(CONFIG_DIR / "runtime_schedule.json")
RESEARCH_UNIVERSE_FILE = str(CONFIG_DIR / "research_universe.json")
VALUATION_POLICY_FILE = str(CONFIG_DIR / "valuation_policy.json")
WATCHLIST_FILE = str(CONFIG_DIR / "watchlist.json")
NOTIFICATION_CONFIG_EXAMPLE_FILE = str(CONFIG_DIR / "notification_config.example.json")
RUNTIME_SCHEDULE_EXAMPLE_FILE = str(CONFIG_DIR / "runtime_schedule.example.json")
RESEARCH_UNIVERSE_EXAMPLE_FILE = str(CONFIG_DIR / "research_universe.example.json")
VALUATION_POLICY_EXAMPLE_FILE = str(CONFIG_DIR / "valuation_policy.example.json")
WATCHLIST_EXAMPLE_FILE = str(CONFIG_DIR / "watchlist.example.json")

OPPORTUNITY_SNAPSHOT_FILE = str(RESEARCH_STATE_DIR / "opportunity_snapshot.json")
VALUATION_SNAPSHOT_FILE = str(RESEARCH_STATE_DIR / "valuation_snapshot.json")
RECOMMENDATION_SNAPSHOT_FILE = str(RESEARCH_STATE_DIR / "recommendation_snapshot.json")
MARKET_RISK_SNAPSHOT_FILE = str(RESEARCH_STATE_DIR / "market_risk_snapshot.json")
DATA_HEALTH_SNAPSHOT_FILE = str(RESEARCH_STATE_DIR / "data_health_snapshot.json")
CHANGE_FEED_FILE = str(RESEARCH_STATE_DIR / "change_feed_latest.json")
DECISION_BRIEF_FILE = str(RESEARCH_STATE_DIR / "decision_brief.json")
VALUATION_CALIBRATION_FILE = str(RESEARCH_STATE_DIR / "valuation_calibration_snapshot.json")
RESEARCH_MANIFEST_FILE = str(RESEARCH_STATE_DIR / "valuation_research_manifest.json")
JOB_STATUS_FILE = str(RESEARCH_STATE_DIR / "job_status.json")
RECOMMENDATION_JOURNAL_FILE = str(RESEARCH_JOURNALS_DIR / "recommendation_history.jsonl")

VALUATION_REPORT_LATEST_JSON = str(REPORTS_DIR / "valuation_research_latest.json")
VALUATION_REPORT_LATEST_MD = str(REPORTS_DIR / "valuation_research_latest.md")


def ensure_storage_layout() -> None:
    for directory in (STATE_DIR, CONFIG_DIR, JOURNALS_DIR, REPORTS_DIR, RESEARCH_STATE_DIR, RESEARCH_JOURNALS_DIR, RESEARCH_CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def bootstrap_storage_paths() -> None:
    ensure_storage_layout()
