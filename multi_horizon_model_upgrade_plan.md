# Multi-Horizon Quant Engine Upgrade Plan

Status: Target-schema V2 implementation is complete. The model must now be
retrained because checkpoints from the retired relative-ranking target schema
are rejected. After walk-forward validation, the new version enters shadow
observation and still requires explicit manual promotion.

## 1. Product Objective

The system should not ask one model to answer every trading question.

The upgraded decision engine will separate:

1. Long-horizon opportunity: what absolute return and price distribution is
   plausible over the next quarter, half year, or year, and is the expected
   return sufficient to beat short-Treasury exposure?
2. Entry timing: is now a reasonable time to add, or should the system wait?
3. Portfolio discipline: how much exposure is appropriate under current
   account and market risk?

```text
Absolute-return distribution
    + positive-return probability
    + short-Treasury outperformance probability
    + auxiliary SPY-relative rank
    + short-term timing evidence
    + risk and portfolio constraints
    = final target-weight action
```

The system is a personal decision assistant. It may be taken offline during an
upgrade, so the implementation should favor a small number of complete
migrations rather than many compatibility layers.

LLMs and SLMs remain explanation tools. They may not create or override trading
actions.

## 2. Model Research Conclusions

### 2.1 The primary task is probabilistic return forecasting

The primary questions for this system are:

> What is the probability that an asset produces a positive return over the
> next 3, 6, and 12 months, what return and price range is plausible, and is
> that expected return sufficient to beat short-term Treasury exposure?

The model forecasts a distribution rather than one exact future price.
Cross-sectional ranking remains useful, but it is an auxiliary task:

- Primary targets: absolute return, positive-return probability, absolute
  return quantiles, and probability of outperforming a short-Treasury proxy.
- Auxiliary targets: probability of outperforming SPY and cross-sectional
  relative-return rank.
- The default short-Treasury total-return proxy is BIL and is configurable.
- P10/P50/P90 absolute-return forecasts are converted into price ranges from
  the latest observed price.

### 2.2 Production candidate: Finance-Native Multi-Asset Transformer

The production candidate will be a neural architecture trained across the
entire stock universe rather than one model per symbol.

Core architecture:

```text
daily / weekly / monthly market sequences
    -> PatchTST-style multi-scale temporal encoder
    -> MASTER-style intra-stock and inter-stock attention
    -> market, sector, and regime tokens
    -> sparse regime Mixture-of-Experts
    -> TFT-style variable selection and multi-horizon decoder
    -> absolute-return quantiles and upside-probability heads
    -> short-Treasury and SPY outperformance heads
    -> auxiliary ranking, downside-risk, and timing heads
```

The model must learn jointly from:

- Each stock's temporal history.
- Relationships among stocks at the same and different times.
- Sector and industry structure.
- Broad-market and macro-risk context.
- Multiple market regimes.

The primary horizons are:

- 63 trading days
- 126 trading days
- 252 trading days

The main outputs are trained jointly:

- Probability of a positive absolute return.
- Probability of outperforming the configured short-Treasury benchmark.
- P10, P50, and P90 absolute-return and price ranges.
- Probability of outperforming SPY.
- Cross-sectional relative-return score and rank.
- Maximum favorable and adverse excursion.
- Long-horizon state.
- Short-term timing state.

### 2.3 What PatchTST contributes

PatchTST is a Transformer architecture for long time-series contexts.

Instead of treating every daily observation as one token, it divides the
history into local patches. This:

- Preserves local temporal patterns.
- Reduces attention cost.
- Allows the model to inspect a much longer lookback.
- Supports masked self-supervised pretraining before supervised fine-tuning.

In this system, PatchTST is not used alone. Its role is the temporal encoder for
daily, weekly, and monthly sequences.

The original PatchTST is channel-independent and therefore does not fully model
relationships among different stocks or features. The production architecture
must add cross-sectional attention and market context after temporal encoding.

### 2.4 What TFT contributes

Temporal Fusion Transformer is a multi-horizon probabilistic forecasting
architecture.

Its useful components are:

- Variable-selection networks that learn which inputs matter in each context.
- Gating layers that suppress unhelpful components.
- Support for static attributes, historical observations, and known future
  inputs.
- Attention across longer temporal dependencies.
- Direct quantile outputs for multiple future horizons.

In this system, TFT is not adopted unchanged. Its variable selection, gating,
static enrichment, and quantile decoder are integrated into the multi-asset
architecture.

TFT alone is insufficient because it does not directly solve the
cross-sectional stock-ranking and dynamic stock-correlation problem.

### 2.5 Cross-sectional and market-guided representation

Use a MASTER-style structure to alternate between:

- Intra-stock temporal aggregation.
- Inter-stock cross-sectional aggregation.

Market and sector tokens provide context for dynamic feature selection. The
model should be able to learn that a feature or relationship matters in one
market regime but not another.

The primary supervised losses learn absolute-return quantiles, positive-return
probability, and short-Treasury outperformance. The auxiliary ranking loss is
grouped by observation date so the model can also compare alternatives without
replacing the primary forecasting objective.

### 2.6 Regime Mixture-of-Experts

A sparse MoE layer allows different experts to specialize in patterns such as:

- Secular growth.
- Cyclical recovery.
- Risk-off and liquidity contraction.
- Range-bound markets.
- High-volatility event regimes.
- Sector rotation.

The router uses market, sector, volatility, breadth, and asset-state tokens.
Expert usage and routing concentration must be logged to prevent expert
collapse.

### 2.7 Financial pretraining

The model should not start only from a small supervised return dataset.

Pretraining tasks:

- Masked patch reconstruction.
- Next-patch prediction.
- Cross-asset contrastive learning.
- Market-regime classification.
- Relative-strength ordering.
- Volatility and drawdown reconstruction.

Possible starting checkpoints or teacher models include MOMENT, Moirai,
Moirai-MoE, and finance-specific foundation models. Off-the-shelf zero-shot
predictions must not be trusted as production signals. The preferred path is
finance-domain pretraining or substantial domain adaptation.

### 2.8 Traditional ML exclusion rule

Traditional ML models are not part of the default production architecture.

They may be used only as:

- Offline sanity-check baselines.
- Ablation controls.

A traditional model may enter the production ensemble only if adding it
produces statistically and economically meaningful incremental value after
costs across multiple walk-forward periods.

Required evidence:

- Higher out-of-sample net return or Top-K excess return.
- No material deterioration in drawdown and turnover.
- Stable contribution across regimes.
- Positive ensemble ablation: removing the traditional branch worsens results.

If these conditions are not met, the model and its production dependency must
be removed.

### 2.9 Retired short-horizon branch

The former per-symbol short-horizon convolution branch has been removed. Its
five-day target and lagging technical features did not provide useful
incremental value and conflicted with the system's long-horizon objective.

Entry timing now comes from the multi-asset model's jointly trained timing
head, while deterministic breakout, volatility, relative-strength, and trend
deterioration measures remain available as validation controls.

## 3. Data and Label Design

### 3.1 Panel dataset

Build a weekly cross-sectional panel:

```text
observation_date | symbol | benchmark | features... | forward labels...
```

Recommended initial universe:

- Core ETF candidates.
- S&P 500 and Nasdaq 100 constituents when available.
- Existing satellite universe and manual includes.
- Historical membership should be used when a reliable source exists;
  otherwise survivorship limitations must be disclosed.

History:

- Minimum usable target: 5 years.
- Preferred: 10 years.
- Weekly observations reduce overlap and noise while keeping enough samples.

Storage:

- Parquet for panel data, predictions, and validation results.
- JSON for configuration, manifests, and model metadata.
- PyTorch checkpoints or `safetensors` for neural model artifacts.
- Traditional-model artifacts are not retained in production unless the
  incremental-value rule is satisfied.

### 3.2 Targets

Primary horizons:

- 63 days
- 126 days
- 252 days

For each horizon calculate:

- Forward absolute return.
- Forward short-Treasury proxy return.
- Forward excess return over the short-Treasury proxy.
- Forward SPY return and SPY-relative return.
- Cross-sectional relevance bucket.
- Maximum favorable excursion.
- Maximum adverse excursion.

Benchmark mapping:

- Capital opportunity-cost benchmark: configurable short-Treasury total-return
  proxy, default `BIL`.
- Broad-market ETFs: configurable peer or SPY.
- Growth ETFs: QQQ or configured peer group.
- Individual stocks: sector ETF as primary and SPY as secondary.
- ADRs or symbols without a reliable sector benchmark: SPY with an explicit
  fallback flag.

The model must not use `future_return > 0` as its only label.

### 3.3 Initial feature set

Phase-one features should favor reliable data:

Price and relative strength:

- 1, 3, 6, and 12-month returns.
- Excess returns versus SPY, QQQ, and sector benchmark.
- 52-week-high proximity.
- Trend slope and trend consistency.
- Drawdown depth and recovery speed.

Accumulation and regime:

- Volume trend and accumulation.
- Volatility contraction and expansion.
- Breakout distance and follow-through.
- Benchmark and sector regime.
- Cross-sectional momentum and volatility ranks.

Fundamental fields when point-in-time data is reliable:

- Revenue and EPS growth.
- Margin and free-cash-flow direction.
- Valuation level and historical percentile.
- Data age and missingness flags.

Fundamental data must improve the model when present, but its absence must not
block the first implementation.

### 3.4 Leakage controls

Tests must prevent:

- Future prices entering features.
- Fundamental values appearing before their publication date.
- Random train/test splitting.
- Standardization or imputation fitted on future periods.
- Candidate universe construction using future membership.
- Overlapping validation folds without an embargo.

Use purged, chronological walk-forward validation.

## 4. Unified Model Output

Each symbol should produce one stable DTO:

```json
{
  "symbol": "MSFT",
  "as_of": "2026-06-18",
  "long_horizon": {
    "state": "ATTRACTIVE",
    "expected_return": 0.14,
    "positive_return_probability": 0.68,
    "risk_free_outperformance_probability": 0.64,
    "blended_rank": 0.83,
    "horizons": {
      "252": {
        "positive_return_probability": 0.68,
        "risk_free_outperformance_probability": 0.64,
        "market_outperformance_probability": 0.57,
        "rank": 0.86,
        "return_range": {"p10": -0.12, "p50": 0.14, "p90": 0.38},
        "price_range": {"p10": 355.0, "p50": 459.0, "p90": 555.0}
      }
    }
  },
  "timing": {
    "state": "WAIT_FOR_ENTRY",
    "confidence": 0.46,
    "breakout_state": "NEUTRAL"
  },
  "risk": {
    "maximum_adverse_excursion": -0.18,
    "data_quality": "OK"
  },
  "decision": {
    "action": "HOLD",
    "target_weight_range_pct": [4.0, 7.0],
    "reason_codes": [
      "LONG_TERM_ATTRACTIVE",
      "SHORT_TERM_TIMING_WEAK"
    ]
  }
}
```

This permits a conclusion such as:

> Long-term attractive, but short-term timing is weak. Hold the current
> position and wait for a better entry instead of selling.

## 5. Decision Fusion

| Long-term state | Timing state | Default action |
| --- | --- | --- |
| Attractive | Buy now / confirmed | `ACCUMULATE` |
| Attractive | Wait / deteriorating | `HOLD` or `WAIT_TO_ADD` |
| Neutral | Buy now | `PROBE` |
| Weak | Short-term strong | `WATCH_TACTICAL` |
| Weak | Weak / failed | `TRIM` or `EXIT` |

An `EXIT` should normally require at least one of:

- Absolute expected return and upside probability have materially
  deteriorated relative to short-Treasury exposure.
- Fundamental or structural evidence has failed.
- Risk-break level is violated.
- Portfolio risk limits require reduction.

The risk and discipline layer retains final veto authority.

## 6. Validation and Governance

Primary metrics:

- Absolute-return median MAE.
- Positive-return directional accuracy and Brier score.
- Short-Treasury-outperformance directional accuracy and Brier score.
- Top 3 excess return over the configured short-Treasury proxy.
- Precision@3 and Precision@10.
- Mean 63/126/252-day benchmark-relative return by rank decile.
- Rank IC and rank stability.
- P10/P50/P90 empirical coverage.
- Maximum adverse excursion.
- Turnover and transaction-cost sensitivity.
- Performance by market regime.

Lifecycle:

- `RESEARCH`
- `CANDIDATE`
- `SHADOW`
- `PRODUCTION`
- `RETIRED`

Promotion rules:

- No automatic promotion.
- At least three purged walk-forward folds.
- 252-day positive-return direction accuracy must exceed chance.
- Positive-return and short-Treasury-outperformance Brier scores must be below
  `0.25`.
- Median absolute-return MAE must remain below the governance threshold,
  initially `20%`.
- Top 3 short-Treasury excess return must be positive.
- Rank IC and Top 3 SPY-relative return remain auxiliary checks.
- The pretrained candidate must improve short-Treasury-relative economic
  performance over the same architecture trained from scratch.
- MoE routing must not collapse.
- Results must not depend on one market regime or a small number of symbols.
- UI and reports must show which model version produced the recommendation.
- Passing validation only yields `ELIGIBLE_FOR_MANUAL_PROMOTION`; it does not
  authorize trade-plan actions.
- Promotion is tied to the exact checkpoint version. Retraining automatically
  returns the new version to shadow status.

## 7. UI Research and Redesign

### 7.1 Current UI issues

The current React UI is functional but not ready for multi-horizon decisions:

- `frontend/src/main.tsx` contains all pages and shared components in one large
  file, making future model-specific UI difficult to maintain.
- Tables use `table-layout: fixed`, causing important explanations and ranges
  to become cramped.
- Mobile CSS hides every column after the fourth, which can silently remove
  decision-critical information.
- Dashboard metrics emphasize system state, but do not answer the first user
  question: "Do I need to act?"
- Portfolio holdings do not show long-term potential, timing disagreement, or
  target-weight gap.
- Core ETF and Satellite pages lack progressive disclosure. Too many columns
  would make them worse, not better.
- Model validation and shadow results are buried in operational snapshots.

### 7.2 Information architecture

Keep the existing major pages, but change their responsibilities.

#### Dashboard: Decision Brief

The first screen should show:

1. Tomorrow's conclusion: `NO ACTION`, `ACTION REQUIRED`, or `RISK REVIEW`.
2. Approved actions only.
3. Model disagreements requiring attention.
4. Portfolio exposure and risk regime.
5. Snapshot freshness.

System-health details should move lower or to Operations.

#### Portfolio: Position Decision Table

Default columns:

- Symbol
- Current weight
- Target-weight range
- Long-term state
- Timing state
- Final action
- Weight gap
- P/L

Each row should expand or open a detail drawer containing:

- 63/126/252-day positive-return probabilities.
- Probability of beating the configured short-Treasury benchmark and SPY.
- P10/P50/P90 absolute-return and price ranges.
- Auxiliary cross-sectional ranks.
- Top structured reasons.
- Risk-break level.
- Model version and freshness.
- Optional "Explain with LLM" button.

#### Core ETFs: Allocation Comparison

Use one full-width comparison table rather than placing it in a narrow
two-column dashboard panel.

Default columns:

- ETF
- Portfolio role
- Current weight
- Target range
- 63/126/252-day outlook
- Rotation state
- Final action

Detailed backtest and evidence should be expandable, not a permanent wide
column.

#### Satellite Radar: Ranked Funnel

Separate three layers:

1. Top 3 approved candidates.
2. Pending candidates with promotion status.
3. Full ranked pool with filters.

Default ranking columns:

- Rank
- Symbol
- Expected absolute return
- Probability of beating short Treasuries
- Timing state
- Risk
- Final state

Reason text, quantile ranges, and backtest details belong in an expandable row
or side drawer.

#### Risk & Discipline

Add:

- Model disagreement count.
- Long-horizon data-quality failures.
- Positions where short-term and long-term signals conflict.
- Portfolio impact of executing all approved actions.

#### Research & Models

Add a focused model-governance view, either as a new page or as a clear
Operations section:

- Production and shadow model versions.
- Latest walk-forward absolute-return MAE, direction accuracy, Brier scores,
  short-Treasury excess return, and auxiliary rank metrics.
- Baseline comparison.
- Rank-decile chart.
- Quantile calibration.
- Last weekend research result.
- Manual promotion controls only when validation passes.

### 7.3 Interaction rules

- Use progressive disclosure rather than adding more columns.
- Keep decision tables full width.
- Make symbol and final action visually dominant.
- Add sorting and filtering to candidate tables.
- Keep the first column sticky on wide tables.
- On mobile, render a compact decision row with an expandable detail section;
  do not hide columns based only on column number.
- Display timestamps and model versions near the decision, not in a remote
  settings page.
- Use color for action and risk only. Do not color every score.

### 7.4 Frontend organization

Refactor during the UI migration:

```text
frontend/src/
  app/
  components/
    DecisionTable
    HorizonStrip
    ReturnRange
    DetailDrawer
    FreshnessBadge
  pages/
    Dashboard
    Portfolio
    CoreEtfs
    SatelliteRadar
    RiskDiscipline
    MarketMonitor
    ResearchModels
    Operations
    Settings
```

Do not perform this refactor as a separate cosmetic project. Do it while the
new snapshot DTOs are integrated, so old UI paths can be removed immediately.

## 8. Compressed Implementation Plan

### Stage 1: Build and validate the new engine offline

The application may be taken offline while this stage is completed.

Deliver as one coherent model package:

- Weekly panel dataset and benchmark mapping.
- 63/126/252-day labels and leakage tests.
- Multi-scale patch dataset for daily, weekly, and monthly inputs.
- Finance-domain self-supervised pretraining pipeline.
- Patch-based temporal encoder.
- Cross-sectional and market-guided Transformer.
- Regime Mixture-of-Experts.
- Multi-task absolute-return quantile, upside-probability,
  short-Treasury/SPY-outperformance, auxiliary ranking, downside-risk, and
  timing heads.
- Traditional and rule-based models only as offline evaluation controls.
- Walk-forward evaluation and model-governance report.
- Unified multi-horizon prediction DTO.

The retired short-horizon branch is excluded from production and evaluation.

Stage exit:

- Reproducible walk-forward report exists.
- The neural candidate demonstrates useful out-of-sample absolute-return
  forecasting and short-Treasury-relative economic value, while auxiliary
  ranking metrics remain stable.
- Pretraining demonstrates incremental value over training the same
  architecture from scratch.
- MoE routing remains stable and does not collapse to one expert.
- No unresolved leakage issue remains.

### Stage 2: Replace the decision engine and UI in one migration

Take the system offline, migrate once, and remove obsolete paths.

Deliver:

- Long-horizon, timing, and risk fusion layer.
- The retired short-horizon branch and its artifacts are removed.
- New Portfolio, Core ETF, Satellite Radar, Dashboard, and Research/Models UI.
- Updated nightly and weekend snapshots.
- Updated Slack, Email, and report output.
- Model version, freshness, and reason codes throughout the system.
- Removal of old short-horizon BUY/SELL authority and obsolete UI fields.

Stage exit:

- UI, reports, and notifications use the same fused decision.
- A weak short-term signal cannot independently sell a strong long-term asset.
- All existing portfolio actions still flow through the risk and discipline
  layer.

### Stage 3: Shadow comparison, selection, and cleanup

Run the new engine in shadow mode for an agreed observation period.

Deliver:

- Production-versus-candidate attribution.
- Absolute-return error and probability-calibration tracking.
- Short-Treasury and SPY outperformance tracking.
- Rank-decile and Top 3 outcome tracking as auxiliary diagnostics.
- Return-quantile calibration tracking.
- Manual model promotion decision.
- Retirement of failed candidates and stale artifacts.
- Final code, configuration, model, and report cleanup.

The personal nature of the system means the shadow period can be shortened or
the system can remain offline while historical walk-forward testing is
expanded. Promotion must still be explicit.

## 9. Final Recommended Model Stack

```text
Temporal representation:
  PatchTST-style daily / weekly / monthly patch encoders

Cross-asset representation:
  MASTER-style intra-stock / inter-stock attention

Context and specialization:
  market + sector + regime tokens
  sparse regime Mixture-of-Experts

Multi-horizon output:
  TFT-style variable selection, gating, and quantile decoder
  absolute-return quantiles + upside probability
  short-Treasury and SPY outperformance probabilities
  auxiliary neural ranking + downside-risk heads

Pretraining:
  finance-domain masked modeling
  cross-asset contrastive learning
  optional MOMENT / Moirai / FinCast initialization or distillation

Timing:
  jointly trained neural timing head

Decision:
  Deterministic fusion + risk gate + discipline layer

Explanation:
  Structured reasons -> local SLM narration
  Remote LLM for on-demand complex explanation

Offline controls only:
  relative-strength rules and traditional ML baselines
```

## 10. Decisions to Confirm

1. Use 63/126/252 trading days as the production long-horizon targets.
2. Use a finance-native multi-asset Transformer as the primary candidate.
3. Use PatchTST-style temporal patch encoders.
4. Use MASTER-style cross-sectional attention and market-guided feature
   selection.
5. Use a sparse regime MoE and TFT-style multi-horizon quantile decoder.
6. Keep traditional ML outside production unless ensemble ablation proves
   incremental economic value.
7. Remove the failed short-horizon branch and use the joint timing head.
8. Perform the upgrade in three complete stages, allowing system downtime.
9. Redesign decision tables around expandable details instead of adding more
   visible columns.

## 11. Research References

- Temporal Fusion Transformers:
  https://arxiv.org/abs/1912.09363
- PatchTST:
  https://arxiv.org/abs/2211.14730
- MASTER market-guided stock Transformer:
  https://arxiv.org/abs/2312.15235
- TRA temporal routing:
  https://arxiv.org/abs/2106.12950
- Moirai-MoE:
  https://arxiv.org/abs/2410.10469
- MOMENT time-series foundation model:
  https://arxiv.org/abs/2402.03885
- FinCast finance-specific foundation model:
  https://arxiv.org/abs/2508.19609
- Carbon data-table guidance, including expandable tables and progressive
  disclosure:
  https://carbondesignsystem.com/components/data-table/usage/
