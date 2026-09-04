from __future__ import annotations

import argparse
import json

from quant_core.jobs import job_registry
from quant_core.research.service import run_full_valuation_research


def run_nightly_research(*, force: bool = False, notify: bool = True, progress=None):
    progress = progress or (lambda stage, pct, detail, **meta: job_registry.update_job_status("nightly-research", state="running", detail=detail, metadata={"stage": stage, "progress_pct": pct, **meta}))
    return run_full_valuation_research(force=force, progress=progress, notify=notify)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run valuation and dislocation research")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args(argv)
    result = run_nightly_research(force=args.force, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
