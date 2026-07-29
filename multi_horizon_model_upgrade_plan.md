# Foundation-Model Quant Engine Upgrade Plan

Status: Draft for implementation.

This document supersedes the previous multi-horizon model plan. The old
self-trained neural model is no longer treated as the product direction. It may
remain only as a benchmark, regression test, or shadow comparator until the new
engine proves better out of sample.

The plan is organized by functional goals, not implementation phases. The
system is personal-use software and can tolerate downtime during a major
migration, so the preferred implementation style is one coherent replacement
rather than many compatibility layers.

## 1. Product Goal

The model layer must help answer four practical trading questions:

1. Should I add, hold, reduce, or avoid a core ETF position tomorrow?
2. Which satellite stocks, if any, are worth attention for medium-to-long-term
   upside?
3. Is the current market environment safe enough to deploy more capital?
4. Are there early signs of systemic risk, especially from AI capex, leverage,
   cash-flow deterioration, market concentration, policy shock, or credit
   stress?

The system should not claim to predict the future exactly. It should produce a
risk-adjusted decision profile:

```text
forecast distribution
    + market sentiment
    + financial stress
    + event risk
    + portfolio discipline
    + validation confidence
    = action, target exposure, invalidation condition, explanation
```

The output must remain actionable:

- No strong signal means no trade.
- A buy signal must include a suggested buy range and invalidation condition.
- A sell or reduce signal must explain whether it is trend deterioration,
  valuation/risk pressure, event risk, or portfolio discipline.
- A risk-off signal must reduce position-size budgets before it tries to pick
  better stocks.

## 2. Functional Goal: Retire The Old Production Model

The current self-trained multi-horizon model has shown weak and unstable
validation quality. It is not enough to keep tuning epochs or continue using it
as the default decision engine.

Required product stance:

- The old model is removed from production decision authority.
- The old model can remain as a benchmark only if it is cheap to run and helps
  compare whether a new model is actually better.
- Any old-model output displayed in the UI must be labeled `LEGACY BENCHMARK`,
  not `PRODUCTION`.
- Promotion logic must not block the new engine simply because the old model is
  already deployed.

Success criteria:

- The UI and reports make it obvious which model family generated a signal.
- No old-model artifact can silently overwrite a new production forecast.
- Model governance compares economic utility, not just validation accuracy.

## 3. Functional Goal: Time-Series Foundation Model Engine

The new core forecasting layer should evaluate modern time-series foundation
models rather than relying on a small model trained only on our local dataset.

Primary candidates:

- TimesFM: preferred first candidate because it is a pretrained time-series
  foundation model with quantile forecasting and newer versions support longer
  context and covariates.
- Chronos: candidate for zero-shot or fine-tuned probabilistic forecasting
  using tokenized time series.
- MOMENT: candidate for research tasks such as representation learning,
  classification, imputation, and anomaly detection.

The model engine must support a plugin-style backend:

```text
FoundationModelBackend
    name
    supported_horizons
    supports_covariates
    supports_quantiles
    load()
    forecast(panel, covariates, horizons)
    summarize_capabilities()
```

Initial production output should include:

- `symbol`
- `asset_type`: core_etf, satellite_stock, tactical_etf, benchmark
- `forecast_horizon`: 63d, 126d, 252d
- `p10_return`, `p50_return`, `p90_return`
- `p10_price`, `p50_price`, `p90_price`
- `positive_return_probability`
- `risk_free_outperformance_probability`
- `spy_outperformance_probability`
- `qqq_outperformance_probability`
- `forecast_confidence`
- `model_family`
- `model_version`
- `generated_at`
- `input_freshness`

Important design rule:

The foundation model forecasts distributions. It does not directly decide final
portfolio action. Action comes from the decision fusion layer after risk and
discipline checks.

## 4. Functional Goal: Market Sentiment And Breadth Factors

The model must see more than OHLCV. Market mood and internal breadth often
change before long-horizon price models fully react.

Required market sentiment factor groups:

- Volatility and fear:
  - VIX level
  - VIX change
  - VIX moving average deviation
  - VIX term-structure proxy when available
- Market breadth:
  - percentage of tracked universe above 50d moving average
  - percentage above 200d moving average
  - new-high/new-low proxy
  - equal-weight vs cap-weight index divergence
- Risk appetite:
  - QQQ vs VOO relative strength
  - XLK/SMH vs VOO relative strength
  - defensive sectors vs growth sectors
  - high beta vs low volatility proxy
- Liquidity and macro pressure:
  - Treasury yield trend
  - short-Treasury benchmark return proxy
  - dollar strength proxy
  - credit-spread proxy when a free source is available
- News and event sentiment:
  - LLM/FinBERT-derived event direction
  - event severity
  - source confidence
  - event freshness

Outputs:

- `market_sentiment_score`
- `risk_appetite_state`: risk_on, neutral, risk_off
- `breadth_state`: broad_participation, narrow_leadership, deteriorating
- `sentiment_confidence`
- `main_sentiment_drivers`

Usage:

- These features can enter the foundation model as covariates when supported.
- They must also feed the risk overlay even when the selected model backend is
  univariate.

## 5. Functional Goal: AI Capex And Systemic Risk Early Warning

The system should explicitly monitor whether the AI infrastructure cycle is
turning into a systemic stress source.

This is not a "financial crisis predictor". It is an early warning overlay that
reduces capital deployment when risk accumulates.

Risk themes:

- Hyperscaler AI capex growing faster than operating cash flow.
- Free cash flow margin deterioration.
- Debt issuance or interest expense growth.
- Supplier/customer circularity and cross-investment.
- Extreme market concentration in AI mega-cap names.
- Semiconductor and data-center infrastructure correlation spike.
- Credit stress and equity drawdown appearing together.
- Valuation expansion unsupported by cash-flow growth.

Required structured metrics when data is available:

- `capex_to_operating_cash_flow`
- `capex_growth_yoy`
- `free_cash_flow_margin`
- `free_cash_flow_growth_yoy`
- `debt_growth_yoy`
- `net_debt_to_cash_flow`
- `interest_expense_growth_yoy`
- `share_of_index_return_from_top_ai_names`
- `mega_cap_concentration`
- `ai_supply_chain_correlation`
- `credit_stress_proxy`
- `earnings_revision_breadth`

Required qualitative/LLM-assisted metrics:

- `ai_capex_narrative_intensity`
- `circular_financing_risk`
- `management_guidance_stress`
- `analyst_cash_flow_concern`
- `policy_or_export_control_risk`

Systemic risk output:

```text
AI_CAPEX_STRESS = LOW | CAUTION | STRESS | CRISIS_WATCH
```

Each output must include:

- top drivers
- affected symbols and ETFs
- confidence
- data freshness
- whether the signal comes from hard financial data, market data, or LLM text
  extraction

Portfolio effects:

- `LOW`: no restriction.
- `CAUTION`: reduce satellite max weight and avoid chasing overextended names.
- `STRESS`: pause new satellite buys unless signal is exceptional and planned.
- `CRISIS_WATCH`: stop new satellite buys, reduce leverage/tactical risk, focus
  on core ETF discipline and cash preservation.

## 6. Functional Goal: Financial Statement And Analyst Data Layer

The system needs better fundamentals, but it must not pretend free data has the
same quality as Bloomberg, FactSet, or Refinitiv.

Required data classification:

- `hard_financial_data`: reported financial statements.
- `derived_financial_metrics`: ratios computed from reported data.
- `analyst_consensus`: recommendation counts or estimate revisions if
  available.
- `llm_extracted_claims`: statements extracted from news, filings, transcripts,
  or reports.
- `manual_override`: user-entered facts or corrections.

Every fundamental field must carry:

- source
- retrieval time
- fiscal period
- freshness state: fresh, stale, missing
- confidence state: high, medium, low

Important scoring rule:

Missing or stale fundamentals should reduce confidence, not automatically
punish a stock's score as if the data were negative.

## 7. Functional Goal: Event And News Intelligence Layer

News and policy are noisy, but ignoring them makes the model blind during
regime shifts.

The event layer must not directly create trades. It modifies risk, confidence,
and invalidation conditions.

Required event types:

- FOMC / CPI / inflation / rate shock
- export controls and geopolitical restrictions
- earnings surprise and guidance revision
- major capex announcement
- debt issuance or credit-rating change
- analyst upgrade/downgrade cluster
- regulatory action
- large customer/supplier disruption
- macro shock

Outputs:

- `event_risk_score`
- `event_direction`: positive, negative, mixed, neutral
- `event_horizon`: intraday, short, medium, long
- `affected_symbols`
- `affected_etfs`
- `confidence`
- `evidence`
- `llm_summary`

LLM role:

- Summarize and cluster news.
- Extract structured claims.
- Explain why events matter.
- Never turn text directly into buy/sell action.

## 8. Functional Goal: Decision Fusion Engine

The final decision engine combines model forecasts, sentiment, systemic risk,
portfolio state, and discipline rules.

Inputs:

- foundation model forecast distribution
- market sentiment state
- AI capex/systemic risk state
- event risk state
- current holdings and cash
- core ETF universe
- satellite universe
- account-level exposure limits
- recent plan-quality scoreboard
- data health

Outputs:

- `final_action`: BUY, ACCUMULATE, PROBE, HOLD, PAUSE_BUY, TRIM, EXIT, AVOID
- `action_strength`: weak, moderate, strong
- `target_weight_range`
- `suggested_trade_size`
- `buy_price_range`
- `sell_or_trim_price_range`
- `invalidation_condition`
- `expected_return_range`
- `downside_range`
- `risk_reward_grade`
- `confidence`
- `primary_reason`
- `risk_overrides`
- `model_inputs_freshness`

Decision rule principles:

- Forecasts must clear the short-Treasury benchmark hurdle.
- Core ETF signals can be more patient and allocation-oriented.
- Satellite stock signals require stronger upside and lower event/systemic
  risk.
- Tactical inverse/leveraged ETF signals are separate intraday overlays, never
  long-term holdings.
- If data health is poor, final action must degrade to HOLD/REVIEW.

## 9. Functional Goal: Core ETF Engine Upgrade

Core ETFs are the long-term base. The system should answer whether to add,
pause, hold, or rebalance, not just rank ETFs.

Required ETF fields:

- `symbol`
- `role`: broad_market, growth, dividend, defensive, bond, gold, tactical
- `current_weight`
- `target_weight_range`
- `forecast_return_range`
- `risk_free_outperformance_probability`
- `drawdown_risk`
- `market_sentiment_adjustment`
- `systemic_risk_adjustment`
- `buy_range`
- `pause_buy_above`
- `trim_or_rebalance_condition`
- `invalidation_condition`
- `rotation_score`
- `final_action`

Core ETF discipline:

- Do not create action noise for tiny weight changes.
- Require minimum target-weight delta before recommending rebalance.
- Respect cash availability and total portfolio exposure.
- Prefer planned accumulation over chasing.

## 10. Functional Goal: Satellite Radar Upgrade

Satellite stocks exist to capture medium-to-long-term upside that is not fully
captured by core ETFs.

The radar should find candidates, not force trades.

Candidate universe:

- Capacity target: up to 100 active candidates.
- Inputs can include Nasdaq 100, S&P 500 leaders, sector watchlists, manual
  includes, and current holdings.
- Leveraged/inverse tactical ETFs are excluded from satellite ranking.

Required candidate fields:

- `symbol`
- `sector`
- `theme`
- `current_position`
- `forecast_return_range`
- `upside_probability`
- `risk_free_outperformance_probability`
- `spy_or_qqq_outperformance_probability`
- `momentum_quality`
- `fundamental_acceleration_state`
- `sentiment_state`
- `event_risk_state`
- `ai_capex_exposure`
- `valuation_or_cashflow_risk`
- `top3_score`
- `top3_rank`
- `top3_state`: new, retained, dropped, watch
- `suggested_weight_range`
- `entry_range`
- `invalidation_condition`
- `final_action`

Top 3 logic:

- A Top 3 recommendation requires both upside and confidence.
- A stock with strong model upside but high systemic/event risk can remain
  WATCH instead of PROBE/ACCUMULATE.
- The radar should explain whether a candidate is early trend, confirmed
  trend, overextended, fundamental acceleration, or event-driven.

## 11. Functional Goal: Model Governance And Validation

The system must judge models by trading usefulness, not only by statistical
fit.

Validation metrics:

- directional accuracy by horizon
- Brier score for positive return
- Brier score for risk-free outperformance
- quantile calibration
- median return error
- rank IC
- Top-K forward return
- Top-K excess return vs BIL
- Top-K excess return vs VOO/SPY/QQQ
- drawdown of selected basket
- turnover implied by recommendations
- signal persistence
- regime-specific performance

Required comparisons:

- foundation model candidate
- old neural model benchmark
- simple core ETF DCA baseline
- momentum baseline
- cash/BIL baseline
- VOO/QQQ baseline

Promotion rule:

A model can become production only if it improves decision utility after risk
adjustment. It does not need to beat every baseline every day, but it must show
that following its signals is better than ignoring them across multiple
walk-forward windows.

Manual promotion remains required.

## 12. Functional Goal: UI And User Experience

The UI should make model uncertainty and risk obvious without turning into a
research notebook.

Dashboard:

- One sentence: trade tomorrow or do nothing.
- Current capital deployment state.
- Top risk reason.
- Top core ETF action.
- Top satellite action.
- AI capex/systemic risk badge.
- LLM plain-language summary.

Core ETF page:

- Focus on allocation, buy ranges, and pause conditions.
- Show forecast range and confidence.
- Show risk overlays that changed the recommendation.

Satellite Radar page:

- Show Top 3 first.
- Show candidate pool only as a compact sortable list.
- Separate "worth researching" from "worth buying".

Risk & Discipline page:

- Market sentiment.
- Breadth.
- AI capex/systemic risk.
- Event risk.
- Exposure limits.
- Why the system is heavy/light/paused.

Research & Models page:

- Model family comparison.
- Validation charts.
- Promotion status.
- Model input coverage.
- Data freshness and missing-factor warnings.

Settings:

- Model backend selection.
- Foundation model cache path.
- Universe configuration.
- Sentiment/event/fundamental source controls.
- LLM settings.
- Risk thresholds.

## 13. Functional Goal: Slack And Email Output

Slack and email should not copy UI tables.

Slack style:

- Short conversational summary.
- No markdown tables.
- No wide columns.
- Use bullets only for the few most important actions or risks.
- If there is no strong signal, say that clearly.

Nightly message must include:

- Tomorrow action: yes/no.
- Core ETF recommendation.
- Satellite Top 3 changes.
- Risk state.
- AI capex/systemic risk state.
- News/event summary.
- Whether model/data confidence is high enough.

Urgent intraday message must include:

- What changed.
- Affected holding or ETF.
- Whether this is a risk warning or opportunity trigger.
- Suggested review action.
- Whether the signal invalidates a previous plan.

## 14. Functional Goal: Data Storage And Reproducibility

Preferred storage:

- Parquet for panels, features, forecasts, validation, and historical signals.
- JSON for config, manifests, and small summaries.
- HTML/Markdown for human-readable reports.
- PyTorch/safetensors for model artifacts.

Every generated forecast must be reproducible from:

- model version
- data snapshot timestamp
- feature config hash
- universe hash
- risk config hash
- source freshness metadata

## 15. Functional Goal: Failure Modes And Safety

The model must degrade gracefully.

Required fallbacks:

- If foundation model cannot load: no new model-driven buys.
- If market data is stale: HOLD/REVIEW only.
- If fundamentals are stale: reduce confidence, do not fake values.
- If LLM fails: use structured summaries.
- If event sources fail: mark event risk confidence low.
- If systemic risk data is incomplete: show missing-data warning.

The system is not connected to a broker, but bad advice is still harmful. Risk
warnings should be conservative when confidence is low.

## 16. Implementation Boundary

This plan intentionally avoids a fine-grained migration checklist. The intended
implementation is a coherent replacement of the model decision layer:

```text
data panel
    -> foundation forecast engine
    -> sentiment and systemic-risk feature layer
    -> decision fusion
    -> governance validation
    -> UI / Slack / Email outputs
```

Existing modules should be modified or deleted based on whether they still
serve this architecture. Compatibility code should not be preserved for its own
sake.

## 17. References

- TimesFM, Google Research:
  https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
- TimesFM GitHub:
  https://github.com/google-research/timesfm
- Chronos, Amazon Science:
  https://www.amazon.science/blog/adapting-language-model-architectures-for-time-series-forecasting/
- MOMENT:
  https://moment-timeseries-foundation-model.github.io/
