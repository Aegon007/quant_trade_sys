# Competitive System Review 2026

## Purpose

This note benchmarks the current Quant Trade System against a small set of representative open-source and commercial quant / decision-support platforms, then turns the comparison into concrete product and engineering priorities.

## Reference Systems Reviewed

### Open-source / hybrid research platforms

1. [QuantConnect / LEAN](https://www.quantconnect.com/docs/)
- Modular framework with explicit layers for universe selection, alpha creation, portfolio construction, execution, and risk management.
- Research notebooks, backtesting, and live/paper deployment share one core engine.
- Strong emphasis on consistent transition from research to deployment and on explicit portfolio/risk modules.

2. [Freqtrade / FreqAI](https://docs.freqtrade.io/en/stable/freqai/)
- Strong operational loop: dry-run, live-run, web UI, backtesting, hyperopt, protections.
- FreqAI supports background retraining, realistic historical retraining emulation, and model artifacts on disk.
- Emphasis on protections, reproducibility, and operational controls over “pure model novelty”.

3. [Microsoft Qlib](https://github.com/microsoft/qlib/blob/main/docs/index.rst)
- Explicit workflow and experiment-management concepts.
- Separate recorder / experiment layer, portfolio/backtest layer, online serving layer.
- Strong lesson: research outputs should be traceable and comparable over time, not just generated ad hoc.

4. [FinRL](https://finrl.readthedocs.io/en/latest/start/three_layer.html)
- Clear layered architecture around data, environment, and agent/application logic.
- Good for RL workflows, but the most transferable idea for our system is modular separation and benchmark-oriented evaluation.

### Commercial / productized decision-support platforms

5. [TrendSpider](https://trendspider.com/)
- Tight integration of scans, backtests, alerts, and no-code strategy tooling.
- “Write once, use everywhere” style logic across scanner, tester, and alerts is especially notable.
- Strong signal surfacing and market-monitoring UX.

6. [TradingView](https://www.tradingview.com/features/)
- Excellent alerting model, strategy tester, replay, and watchlist-wide monitoring.
- Very strong at intraday monitoring and fast information flow, even when it is not a full portfolio decision engine.

7. [Koyfin](https://www.koyfin.com/features/)
- Strong portfolio, dashboard, alerts, analyst estimates, and research presentation layer.
- Not a trading engine, but a very good benchmark for clarity, custom dashboards, and portfolio-level information density.

8. [Composer](https://www.composer.trade/)
- Productizes strategy logic as portfolio automation with explicit trading periods and prebuilt strategy ideas.
- Useful benchmark for turning strategy logic into clear, user-facing execution plans instead of research artifacts.

## Current System Strengths

Compared with the systems above, our current system is already unusually strong in a few areas for a single-user stack:

- Unified nightly planner, post-close review, Robinhood CSV reconciliation, and Slack / Email delivery.
- A real distinction between:
  - core ETF engine
  - satellite radar
  - discipline / risk layer
- Strong portfolio-centric workflow rather than isolated single-symbol signals.
- Integrated local SLM + remote LLM routing for narration and deeper explanation.
- Intraday tactical overlay groundwork and event journaling are already in place.

## Main Gaps vs. Best-in-Class Systems

### 1. Strategy validation and experiment tracking

This is the clearest current gap.

- Qlib emphasizes workflow and experiment recording.
- Freqtrade emphasizes artifacts, protections, and reproducible backtesting.
- QuantConnect emphasizes explicit module boundaries and research-to-deployment consistency.

Our system already compares strategies in places, but before this update it did not yet have a dedicated, persistent “is the default strategy still trustworthy?” layer.

### 2. Reusable research outputs

TrendSpider and TradingView are strong because scanner, tester, and alert layers reinforce each other.

Our system has many strong subsystems, but several research outputs were still more “report-like” than “first-class reusable state”. The more outputs become stable snapshots, the better the UI, alerts, and reviews stay consistent.

### 3. Portfolio-grade explanation hierarchy

Koyfin and Composer both show a useful product lesson:

- users do not want raw model internals first
- they want clear portfolio implications first

Our cockpit has improved a lot, but explanation still needs to keep moving toward:
- decision summary first
- detailed mechanics second

### 4. Validation-aware decision confidence

We already had risk, discipline, and plan generation.
What was missing was a formal bridge between:
- “the system can produce a plan”
- and
- “the system has recent evidence that the default strategy is still competitive on current focus symbols”

## Improvement Priorities Derived from the Review

### Priority A: Strategy Validation + Experiment Journal

This is the single highest-value improvement inspired by Qlib / Freqtrade / QuantConnect.

Needed outcome:
- a persistent validation snapshot
- a rolling experiment journal
- explicit readiness states like `READY / CAUTION / REVIEW / NO_DATA`

Why it matters:
- prevents blind trust in the current default strategy
- creates an audit trail for strategy drift
- makes weekend research more actionable

### Priority B: Make research outputs reusable state, not just reports

Needed outcome:
- all high-value research outputs should be snapshot-backed and reusable by:
  - Dashboard
  - Operations
  - Slack / Email summaries
  - post-close review

### Priority C: Keep the product decision-first

Needed outcome:
- continue shaping the UI and summaries toward:
  - what should I do?
  - why?
  - what invalidates this?

instead of pushing raw technical output to the surface too early.

### Priority D: Improve signal trust through feedback loops

Needed outcome:
- track not only whether a signal exists
- but whether:
  - it was executable
  - it stayed valid
  - it outperformed alternatives

## Improvements Implemented in This Round

This round implements Priority A directly:

1. `strategy_validation_snapshot.json`
- stores validation state for the current default strategy across current focus symbols

2. `strategy_experiment_journal.jsonl`
- stores rolling validation outcomes over time

3. Weekend research now produces strategy validation
- not just strategy comparison highlights
- but a persistent “should we still trust the default strategy?” result

4. Dashboard / Operations / nightly report now surface strategy validation
- so research credibility is visible, not buried

## What Still Belongs in V2

These are still worthwhile, but are better treated as next-phase work:

- stronger intraday tactical sampling for benchmark / tactical ETF monitoring
- richer execution-failure tracking for plans that become invalid intraday
- deeper “yesterday to today” explanation flow for Change Feed
- more unified research / experiment board across weekend and nightly runs

## Final View

The biggest lesson from the systems above is not “add more models”.

It is:

`turn research into a repeatable, validated, portfolio-aware workflow with explicit confidence and traceability.`

That is the direction this system should keep following.
