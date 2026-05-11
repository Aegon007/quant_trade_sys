"""Unified supervisor that starts the UI, Slack bot, and nightly scheduler."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from quant_core.data import storage as data_storage
from quant_core.events.analyst_consensus import should_run_nightly_consensus_update
from jobs.nightly_alerts import run_nightly_alerts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MONITOR_SECONDS = 10
DEFAULT_NIGHTLY_POLL_SECONDS = 300
DEFAULT_MARKET_REFRESH_POLL_SECONDS = 300
DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    command: List[str]
    cwd: str


@dataclass(frozen=True)
class ServiceStartupStatus:
    name: str
    state: str
    detail: str
    pid: Optional[int] = None

    def format_line(self) -> str:
        state_label = {
            "started": "OK",
            "skipped": "SKIP",
            "failed": "FAIL",
        }.get(self.state.lower(), self.state.upper())
        pid_fragment = f" pid={self.pid}" if self.pid is not None else ""
        return f"[{state_label}] {self.name}{pid_fragment} - {self.detail}"


def _has_slack_credentials(environ=None) -> bool:
    environ = environ or os.environ
    return bool(str(environ.get("SLACK_BOT_TOKEN") or "").strip() and str(environ.get("SLACK_APP_TOKEN") or "").strip())


def build_service_specs(
    *,
    with_ui: bool = True,
    with_slack: bool = True,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> List[ServiceSpec]:
    project_root = Path(project_root or PROJECT_ROOT)
    python_executable = python_executable or sys.executable
    specs: List[ServiceSpec] = []

    if with_slack:
        specs.append(
            ServiceSpec(
                name="slack-bot",
                command=[python_executable, "-m", "jobs.slack_bot"],
                cwd=str(project_root),
            )
        )

    if with_ui:
        specs.append(
            ServiceSpec(
                name="streamlit-ui",
                command=[python_executable, "-m", "streamlit", "run", str(project_root / "main.py")],
                cwd=str(project_root),
            )
        )

    return specs


def start_service_process(spec: ServiceSpec, *, popen=subprocess.Popen):
    return popen(spec.command, cwd=spec.cwd)


def emit_startup_summary(statuses, *, printer=print):
    statuses = list(statuses)
    if not statuses:
        return
    printer("Startup status:")
    for status in statuses:
        printer(status.format_line())


def maybe_run_nightly_alerts(
    *,
    now: Optional[datetime] = None,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    logger: Optional[logging.Logger] = None,
) -> bool:
    logger = logger or logging.getLogger(__name__)
    now = now or datetime.now()
    if not should_run(now=now):
        return False
    logger.info("Nightly alerts are due; running scheduled job.")
    runner(force=False, dry_run=False, now=now)
    return True


def maybe_run_market_refresh(
    *,
    now: Optional[datetime] = None,
    loader: Callable[[], dict] = data_storage.load_data,
    refresher: Callable[..., tuple] = data_storage.auto_refresh_market_data,
    saver: Callable[[dict], None] = data_storage.save_data,
    refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    logger: Optional[logging.Logger] = None,
) -> bool:
    logger = logger or logging.getLogger(__name__)
    now = now or datetime.now()
    data = loader()
    refreshed_data, refreshed = refresher(
        data,
        refresh_interval_seconds=refresh_interval_seconds,
        now=now,
        force=False,
    )
    if not refreshed:
        return False
    saver(refreshed_data)
    logger.info("Market cache refresh completed.")
    return True


def nightly_scheduler_loop(
    stop_event: threading.Event,
    *,
    poll_seconds: int = DEFAULT_NIGHTLY_POLL_SECONDS,
    now_func: Callable[[], datetime] = datetime.now,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    logger: Optional[logging.Logger] = None,
):
    logger = logger or logging.getLogger(__name__)
    while not stop_event.is_set():
        try:
            maybe_run_nightly_alerts(now=now_func(), should_run=should_run, runner=runner, logger=logger)
        except Exception:
            logger.exception("Nightly scheduler tick failed.")
        if stop_event.wait(poll_seconds):
            break


def market_refresh_loop(
    stop_event: threading.Event,
    *,
    poll_seconds: int = DEFAULT_MARKET_REFRESH_POLL_SECONDS,
    refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    now_func: Callable[[], datetime] = datetime.now,
    loader: Callable[[], dict] = data_storage.load_data,
    refresher: Callable[..., tuple] = data_storage.auto_refresh_market_data,
    saver: Callable[[dict], None] = data_storage.save_data,
    logger: Optional[logging.Logger] = None,
):
    logger = logger or logging.getLogger(__name__)
    while not stop_event.is_set():
        try:
            maybe_run_market_refresh(
                now=now_func(),
                loader=loader,
                refresher=refresher,
                saver=saver,
                refresh_interval_seconds=refresh_interval_seconds,
                logger=logger,
            )
        except Exception:
            logger.exception("Market refresh tick failed.")
        if stop_event.wait(poll_seconds):
            break


def _terminate_process(process, *, timeout_seconds: float = 10.0):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except Exception:
        process.kill()


def run_supervisor(
    *,
    with_ui: bool = True,
    with_slack: bool = True,
    with_nightly: bool = True,
    with_market_refresh: bool = True,
    monitor_seconds: int = DEFAULT_MONITOR_SECONDS,
    nightly_poll_seconds: int = DEFAULT_NIGHTLY_POLL_SECONDS,
    market_refresh_poll_seconds: int = DEFAULT_MARKET_REFRESH_POLL_SECONDS,
    market_refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
    popen=subprocess.Popen,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    now_func: Callable[[], datetime] = datetime.now,
    status_printer: Callable[[str], None] = print,
):
    logger = logging.getLogger(__name__)
    stop_event = threading.Event()
    services = []
    launched_processes = []
    startup_statuses = []
    install_signal_handlers = threading.current_thread() is threading.main_thread()
    previous_sigterm = previous_sigint = None

    def _signal_handler(signum, frame):  # noqa: ARG001
        stop_event.set()

    if install_signal_handlers:
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    scheduler_thread = None
    market_refresh_thread = None
    reported_exits = set()
    try:
        effective_with_slack = with_slack and _has_slack_credentials()
        if with_slack and not effective_with_slack:
            logger.warning("Slack bot skipped because SLACK_BOT_TOKEN or SLACK_APP_TOKEN is missing.")
            startup_statuses.append(
                ServiceStartupStatus(
                    name="slack-bot",
                    state="skipped",
                    detail="SLACK_BOT_TOKEN or SLACK_APP_TOKEN is missing.",
                )
            )

        service_specs = build_service_specs(
            with_ui=with_ui,
            with_slack=effective_with_slack,
            python_executable=python_executable,
            project_root=project_root,
        )
        if with_nightly:
            scheduler_thread = threading.Thread(
                target=nightly_scheduler_loop,
                args=(stop_event,),
                kwargs={
                    "poll_seconds": nightly_poll_seconds,
                    "now_func": now_func,
                    "should_run": should_run,
                    "runner": runner,
                    "logger": logger,
                },
                daemon=True,
                name="nightly-scheduler",
            )
            scheduler_thread.start()
            startup_statuses.append(
                ServiceStartupStatus(
                    name="nightly-scheduler",
                    state="started",
                    detail=f"running in-process; poll={nightly_poll_seconds}s.",
                )
            )

        if with_market_refresh:
            market_refresh_thread = threading.Thread(
                target=market_refresh_loop,
                args=(stop_event,),
                kwargs={
                    "poll_seconds": market_refresh_poll_seconds,
                    "refresh_interval_seconds": market_refresh_interval_seconds,
                    "now_func": now_func,
                    "loader": data_storage.load_data,
                    "refresher": data_storage.auto_refresh_market_data,
                    "saver": data_storage.save_data,
                    "logger": logger,
                },
                daemon=True,
                name="market-refresh",
            )
            market_refresh_thread.start()
            startup_statuses.append(
                ServiceStartupStatus(
                    name="market-refresh",
                    state="started",
                    detail=f"running in-process; poll={market_refresh_poll_seconds}s interval={market_refresh_interval_seconds}s.",
                )
            )

        if not with_nightly and not with_market_refresh and not service_specs:
            logger.warning("No services were requested; nothing to start.")
            emit_startup_summary(startup_statuses, printer=status_printer)
            return {
                "services": [],
                "launch_count": 0,
                "startup_statuses": [asdict(status) for status in startup_statuses],
            }

        for spec in service_specs:
            try:
                process = start_service_process(spec, popen=popen)
            except Exception as exc:
                logger.exception("Failed to start %s", spec.name)
                startup_statuses.append(
                    ServiceStartupStatus(
                        name=spec.name,
                        state="failed",
                        detail=str(exc),
                    )
                )
                continue
            services.append(spec)
            launched_processes.append((spec, process))
            logger.info("Started %s: %s", spec.name, " ".join(spec.command))
            startup_statuses.append(
                ServiceStartupStatus(
                    name=spec.name,
                    state="started",
                    detail=" ".join(spec.command),
                    pid=getattr(process, "pid", None),
                )
            )

        emit_startup_summary(startup_statuses, printer=status_printer)
        if not launched_processes and scheduler_thread is None and market_refresh_thread is None:
            return {
                "services": [],
                "launch_count": 0,
                "startup_statuses": [asdict(status) for status in startup_statuses],
            }

        while not stop_event.is_set():
            for spec, process in launched_processes:
                code = process.poll()
                if code is not None and spec.name not in reported_exits:
                    reported_exits.add(spec.name)
                    logger.warning("%s exited with code %s", spec.name, code)
            if stop_event.wait(monitor_seconds):
                break
    finally:
        stop_event.set()
        for spec, process in launched_processes:
            _terminate_process(process)
        if scheduler_thread is not None and scheduler_thread.is_alive():
            scheduler_thread.join(timeout=2.0)
        if market_refresh_thread is not None and market_refresh_thread.is_alive():
            market_refresh_thread.join(timeout=2.0)
        if install_signal_handlers:
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)

    return {
        "services": [spec.name for spec in services],
        "launch_count": len(launched_processes),
        "startup_statuses": [asdict(status) for status in startup_statuses],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the Streamlit UI, Slack bot, and nightly scheduler together.")
    parser.add_argument("--no-ui", action="store_true", help="Do not start Streamlit UI.")
    parser.add_argument("--no-slack", action="store_true", help="Do not start the Slack bot.")
    parser.add_argument("--no-nightly", action="store_true", help="Do not start the nightly scheduler.")
    parser.add_argument("--no-market-refresh", action="store_true", help="Do not start the hourly market cache refresher.")
    parser.add_argument("--monitor-seconds", type=int, default=DEFAULT_MONITOR_SECONDS, help="How often to check child processes.")
    parser.add_argument("--nightly-poll-seconds", type=int, default=DEFAULT_NIGHTLY_POLL_SECONDS, help="How often to check whether nightly alerts are due.")
    parser.add_argument("--market-refresh-poll-seconds", type=int, default=DEFAULT_MARKET_REFRESH_POLL_SECONDS, help="How often to check whether market cache refresh is due.")
    parser.add_argument("--market-refresh-interval-seconds", type=int, default=DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS, help="Minimum interval between market cache refreshes.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    result = run_supervisor(
        with_ui=not args.no_ui,
        with_slack=not args.no_slack,
        with_nightly=not args.no_nightly,
        with_market_refresh=not args.no_market_refresh,
        monitor_seconds=args.monitor_seconds,
        nightly_poll_seconds=args.nightly_poll_seconds,
        market_refresh_poll_seconds=args.market_refresh_poll_seconds,
        market_refresh_interval_seconds=args.market_refresh_interval_seconds,
    )
    print(f"Supervisor exited. services={result['services']} launch_count={result['launch_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
