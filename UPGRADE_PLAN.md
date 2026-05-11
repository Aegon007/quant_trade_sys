# Quant System Upgrade Plan (Single-User, File-Backed, TDD)

## Scope and constraints
- Single-user system, local-first.
- Keep `run_all.py` as unified runtime entrypoint.
- Keep file-backed persistence (no SQLite/cron in this phase).
- Prioritize stability, auditability, and decision quality.

## Target architecture (current direction)
- `main.py`: UI orchestration only.
- `portfolio_actions.py`: all state-changing actions.
- `data_utils.py`: file IO, sync, normalization, price refresh.
- `transactions.py`: action/trade/event ledger.
- `system_snapshot.py`: normalized snapshot output.
- `jobs/run_all.py`: unified service supervisor.
- `jobs/nightly_alerts.py`: nightly batch task.

## Code organization upgrade (new)
Goal: move root-level modules into functional packages and keep `main.py` as orchestration-only.

### Target package layout
```text
app/
  ui/
    pages.py
    dialogs.py
    components.py
  orchestration/
    runtime.py

quant_core/
  data/
    storage.py
    market_data.py
    positions.py
  actions/
    portfolio_actions.py
  signals/
    strategy_registry.py
    strategy_ui.py
    deep_tcn.py
  risk/
    risk_gate.py
    position_advisor.py
    capital_allocator.py
  analytics/
    quant_analysis.py
    monte_carlo.py
    portfolio_metrics.py
    portfolio_advisor.py
  events/
    event_news.py
    event_fetcher.py
    analyst_consensus.py
    news_summary.py
    finbert_sentiment.py
  notifications/
    notification_channels.py
    notification_config.py
    alert_engine.py
  snapshots/
    system_snapshot.py
  ledger/
    transactions.py

integrations/
  slack/
    command_parser.py
    command_service.py
    bot.py

jobs/
  run_all.py
  nightly_alerts.py
```

### Migration strategy (safe, incremental)
1. Phase A: package scaffolding + compatibility wrappers.
   - Create package directories and `__init__.py`.
   - Move one module at a time to package path.
   - Keep root-level compatibility wrappers temporarily:
     - Example wrapper `portfolio_actions.py` (alias style):
       - `from quant_core.actions import portfolio_actions as _impl`
       - `sys.modules[__name__] = _impl`
   - Purpose: avoid breaking existing imports in `main.py`, tests, and jobs.

2. Phase B: import path migration.
   - Update `main.py`, jobs, and tests to import package paths directly.
   - Remove wildcard usage from wrappers where possible.
   - Keep wrappers only for transitional support.

3. Phase C: main split and orchestration cleanup.
   - Split `main.py` into:
     - `app/ui/pages.py` (tab/page rendering)
     - `app/ui/dialogs.py` (sell/edit/move dialogs)
     - `app/orchestration/runtime.py` (load/refresh/cache/runflow)
   - Keep `main.py` as thin bootstrap:
     - page config
     - runtime init
     - call render entrypoints

4. Phase D: wrapper removal.
   - After all tests pass with package imports, remove root wrappers.
   - Update README and dev docs to new import paths.

### File-level migration map (first wave)
- `data_utils.py` -> `quant_core/data/storage.py`
- `portfolio_actions.py` -> `quant_core/actions/portfolio_actions.py`
- `transactions.py` -> `quant_core/ledger/transactions.py`
- `quant_analysis.py` -> `quant_core/analytics/quant_analysis.py`
- `risk_gate.py` -> `quant_core/risk/risk_gate.py`
- `capital_allocator.py` -> `quant_core/risk/capital_allocator.py`
- `position_advisor.py` -> `quant_core/risk/position_advisor.py`
- `event_news.py` -> `quant_core/events/event_news.py`
- `event_fetcher.py` -> `quant_core/events/event_fetcher.py`
- `analyst_consensus.py` -> `quant_core/events/analyst_consensus.py`
- `news_summary.py` -> `quant_core/events/news_summary.py`
- `finbert_sentiment.py` -> `quant_core/events/finbert_sentiment.py`
- `notification_config.py` -> `quant_core/notifications/notification_config.py`
- `notification_channels.py` -> `quant_core/notifications/notification_channels.py`
- `alert_engine.py` -> `quant_core/notifications/alert_engine.py`
- `system_snapshot.py` -> `quant_core/snapshots/system_snapshot.py`
- `monte_carlo.py` -> `quant_core/analytics/monte_carlo.py`
- `portfolio_metrics.py` -> `quant_core/analytics/portfolio_metrics.py`
- `portfolio_advisor.py` -> `quant_core/analytics/portfolio_advisor.py`
- `slack_command_parser.py` -> `integrations/slack/command_parser.py`
- `slack_command_service.py` -> `integrations/slack/command_service.py`
- `jobs/slack_bot.py` -> `integrations/slack/bot.py`

### Validation criteria per migration step
- No behavior change in user-facing flows.
- `python -m jobs.run_all` still works.
- Full tests stay green.
- Transaction/event ledger remains compatible with legacy records.
- Import errors must be zero in both app run and tests.

## Phase 1 (completed in this round)
- [x] Add portfolio action event records for move operations.
  - Files:
    - `transactions.py`
    - `portfolio_actions.py`
    - `slack_command_service.py`
    - `main.py`
- [x] Add transfer-to-holding dialog to input shares (min `0.001`).
  - Files:
    - `main.py`
    - `ui_components.py`
- [x] Upgrade transactions tab to show both trade records and portfolio event records.
  - Files:
    - `main.py`
- [x] Add tests for move event recording.
  - Files:
    - `tests/test_portfolio_actions.py`

## Phase 2 (completed)
- [x] Caching boundary hardening (`cache-first` optimization).
  - `main.py`
    - Wrap repeated data/feature/report computations with cache helpers.
  - `quant_analysis.py`, `deep_learning_strategy.py`
    - Expose cache-friendly pure functions.
  - Tests:
    - Add cache behavior smoke tests (no behavior regression on rerun).

- [x] Unified action schema and export helpers.
  - `transactions.py`
    - Normalize event taxonomy (`SELL`, `SELL_ALL`, `MOVE_TO_WATCH`, `MOVE_TO_HOLDING`, etc.).
    - Add lightweight serializer for report/export.
  - `main.py`
    - Add filter controls in transactions tab by event type/side/symbol.
  - Tests:
    - New unit tests for schema compatibility with legacy records.

- [x] Snapshot journaling for nightly review.
  - `system_snapshot.py`
    - Keep snapshot structure stable for downstream use.
  - `jobs/nightly_alerts.py`
    - Append nightly snapshot/report files.
  - Tests:
    - Validate snapshot file write and key section presence.

- [x] Code organization migration: Wave 1.
  - Move canonical implementation into package paths:
    - `quant_core/data/storage.py`
    - `quant_core/actions/portfolio_actions.py`
    - `quant_core/ledger/transactions.py`
    - `integrations/slack/command_parser.py`
    - `integrations/slack/command_service.py`
    - `integrations/slack/bot.py`
  - Keep root compatibility aliases:
    - `data_utils.py`, `portfolio_actions.py`, `transactions.py`
    - `slack_command_parser.py`, `slack_command_service.py`
    - `jobs/slack_bot.py`
  - Package scaffolding:
    - `quant_core/data`, `quant_core/actions`, `quant_core/ledger`, `integrations/slack`
  - Tests:
    - import compatibility + shared module-state checks + full regression.

## Phase 3 (after Phase 2 is stable)
- [x] Signal scoreboard and attribution.
  - New module: `signal_scoreboard.py`
  - Inputs:
    - signal outputs + subsequent realized returns
  - Outputs:
    - win rate, payoff ratio, drawdown contribution, regime breakdown
  - UI:
    - new backtest block in `main.py` (Signal Scoreboard)
  - Tests:
    - deterministic attribution tests (`tests/test_signal_scoreboard.py`).

- [x] `Raw signal -> Approved signal` risk pipeline.
  - New module: `signal_approval.py`
  - Integrated with `position_advisor.py`, `capital_allocator.py`, `ui_components.py`, `main.py`
  - Add explicit approved-signal object and reason trace.
  - UI:
    - show risk-gate interception reasons in holdings/watchlist and single-symbol signal panel.
  - Tests:
    - gate override and reason consistency (`tests/test_signal_approval.py`).

- [ ] Code organization migration: Wave 2 (main orchestration split).
  - Split `main.py` into orchestration + UI modules.
  - Reduce `main.py` to bootstrap only.
  - Remove temporary root wrappers when all imports are migrated.
  - Progress (completed in this round):
    - Added `app/orchestration/runtime.py` and moved runtime helpers:
      - `bootstrap_app_data`
      - `ensure_dialog_state_defaults`
      - `apply_runtime_strategy_params`
      - `normalize_symbols`
      - `collect_tracked_symbols`
      - `fetch_news_events_with_cache`
      - `enable_auto_news_rerun`
      - `evaluate_market_risk_for_portfolio`
    - Updated `main.py` to delegate data/session bootstrapping and news cache orchestration to runtime module.
    - Added/expanded unit tests: `tests/test_runtime_orchestration.py`.
    - Added `app/ui/panels.py` and moved UI panel renderers:
      - `render_account_snapshot_panel`
      - `render_market_risk_gate_banner`
      - `render_active_events_panel`
    - Added `app/ui/notification_page.py` and moved `render_notification_config_page`.
    - Added `app/ui/dialogs.py` and moved `render_dialogs` implementation.
    - Added `app/ui/pages.py` for shared tab-level formatting/render helpers:
      - `build_holdings_markdown`
      - `build_transaction_display_dataframe`
      - `summarize_trade_records`
      - `build_snapshot_alerts`
      - `render_transactions_tab`
    - Removed thin wrapper helpers from `main.py` and switched call sites to direct `rt/up/unp/ud` module calls.
    - Replaced duplicated symbol collection logic in sidebar actions with `rt.collect_tracked_symbols(...)`.
    - Moved holdings Markdown export generation and transaction table rendering in `main.py` to `app/ui/pages.py`.
    - Moved snapshot alert projection in `main.py` to `app/ui/pages.py`.
    - Updated `main.py` panel rendering calls to delegate to `app/ui/panels.py`.
    - Added unit tests: `tests/test_ui_panels.py`, `tests/test_ui_notification_page.py`, `tests/test_ui_dialogs.py`, `tests/test_ui_pages.py`.
    - Added package scaffolding and migrated additional root modules into functional packages:
      - `quant_core/analytics`: `quant_analysis.py`, `monte_carlo.py`, `portfolio_metrics.py`, `portfolio_advisor.py`
      - `quant_core/risk`: `risk_gate.py`, `capital_allocator.py`, `position_advisor.py`
      - `quant_core/events`: `event_news.py`, `event_fetcher.py`, `news_summary.py`, `analyst_consensus.py`, `finbert_sentiment.py`
      - `quant_core/notifications`: `notification_config.py`, `notification_channels.py`, `alert_engine.py`
      - `quant_core/snapshots`: `system_snapshot.py`
    - Kept root compatibility wrappers for migrated modules to avoid breaking existing imports.
    - Switched high-level imports to package paths in:
      - `main.py`
      - `jobs/nightly_alerts.py`
      - `jobs/run_all.py`
      - `ui_components.py`
      - `app/ui/panels.py`
      - `strategies/classic_strategies.py`
      - `integrations/slack/command_service.py`
      - internal package modules (`quant_core/events/event_fetcher.py`, `quant_core/notifications/alert_engine.py`, `quant_core/snapshots/system_snapshot.py`)
    - Hardened test module isolation for compatibility wrappers by extending `tests/support.py::clear_modules` to clear mapped package modules and parent package attributes.
    - Expanded package import compatibility coverage in `tests/test_package_imports.py`.
    - Consolidated portfolio domain modules into a dedicated package:
      - Added `quant_core/portfolio/{actions.py,metrics.py,risk.py,allocation.py,position.py,__init__.py}`
      - Re-pointed compatibility modules:
        - `quant_core/actions/portfolio_actions.py` -> `quant_core.portfolio.actions`
        - `quant_core/analytics/portfolio_metrics.py` -> `quant_core.portfolio.metrics`
        - `quant_core/analytics/portfolio_advisor.py` -> `quant_core.portfolio.risk`
        - `quant_core/risk/capital_allocator.py` -> `quant_core.portfolio.allocation`
        - `quant_core/risk/position_advisor.py` -> `quant_core.portfolio.position`
      - Updated high-level imports to use `quant_core.portfolio.*` directly in `main.py`, `ui_components.py`, `jobs/nightly_alerts.py`, and `quant_core/snapshots/system_snapshot.py`.
      - Extended import compatibility tests and module cleanup mapping to include `quant_core.portfolio.*`.

## Run and verification
- Unified startup:
  - `python -m jobs.run_all`
- Full tests:
  - `python -m unittest discover -s tests -v`
