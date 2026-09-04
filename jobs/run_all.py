from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_core.api import actions, snapshot_loader
from quant_core.jobs import job_registry
from quant_core.notifications import notification_config


LOGGER = logging.getLogger(__name__)


@dataclass
class Service:
    name: str
    command: list[str]
    cwd: str
    process: subprocess.Popen | None = None


def _slack_ready() -> bool:
    config = notification_config.apply_environment_overrides(notification_config.load_notification_config())
    slack = dict(config.get("slack", {}) or {})
    return bool(slack.get("bot_token") and slack.get("app_token"))


def _wait_api(url="http://127.0.0.1:8710/api/health", timeout=30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def _start(service: Service) -> None:
    service.process = subprocess.Popen(service.command, cwd=service.cwd)
    job_registry.update_job_status(service.name, state="started", detail=" ".join(service.command), pid=service.process.pid, command=service.command, metadata={"stage": "startup", "progress_pct": 100})
    LOGGER.info("已启动 %s，pid=%s", service.name, service.process.pid)


def _parse_hhmm(value: str, default: clock_time) -> clock_time:
    try:
        hour, minute = str(value).split(":", 1)
        return clock_time(int(hour), int(minute))
    except Exception:
        return default


def _inside_window(current: clock_time, start: clock_time, end: clock_time) -> bool:
    return start <= current <= end if start <= end else current >= start or current <= end


def _market_open(now: datetime) -> bool:
    return now.weekday() < 5 and clock_time(9, 30) <= now.time() <= clock_time(16, 0)


def scheduler_loop(stop: threading.Event, *, verbose=False) -> None:
    last_refresh = 0.0
    last_nightly = ""
    last_weekend = ""
    while not stop.is_set():
        schedule = snapshot_loader.load_runtime_schedule()
        timezone = ZoneInfo(str(schedule.get("timezone") or "America/New_York"))
        now = datetime.now(timezone).replace(tzinfo=None)
        monitor = dict(schedule.get("market_monitor", {}) or {})
        interval = max(int(monitor.get("interval_seconds") or 1800), 60)
        if monitor.get("enabled", True) and time.time() - last_refresh >= interval and (not monitor.get("market_hours_only", True) or _market_open(now)):
            actions.run_with_job_status("scheduled-market-refresh", lambda: actions.refresh_market_data_now(force_source_refresh=False), run_async=True)
            last_refresh = time.time()
            if verbose:
                LOGGER.info("自动行情刷新已触发")
        nightly = dict(schedule.get("nightly", {}) or {})
        window = dict(nightly.get("run_window_local", {}) or {})
        if nightly.get("enabled", True) and _inside_window(now.time(), _parse_hhmm(window.get("start"), clock_time(23)), _parse_hhmm(window.get("end"), clock_time(1))):
            research_date = now.date() if now.time() >= clock_time(12) else now.date() - timedelta(days=1)
            key = research_date.isoformat()
            if research_date.weekday() < 5 and last_nightly != key:
                actions.run_with_job_status("scheduled-nightly-run", lambda: __import__("jobs.nightly_research", fromlist=["run_nightly_research"]).run_nightly_research(force=False, notify=True, progress=actions.build_job_progress_callback("scheduled-nightly-run")), run_async=True)
                last_nightly = key
                LOGGER.info("夜间估值流程已触发")
        weekend = dict(schedule.get("weekend_research", {}) or {})
        weekend_window = dict(weekend.get("run_window_local", {}) or {})
        day_name = str(weekend_window.get("day") or "Saturday").lower()
        day_index = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}.get(day_name, 5)
        if weekend.get("enabled", True) and now.weekday() == day_index and _inside_window(now.time(), _parse_hhmm(weekend_window.get("start"), clock_time(10)), _parse_hhmm(weekend_window.get("end"), clock_time(18))):
            key = now.date().isoformat()
            if last_weekend != key:
                actions.run_with_job_status("scheduled-weekend-research", lambda: __import__("jobs.weekend_research", fromlist=["run_weekend_research"]).run_weekend_research(force=False, notify=True, progress=actions.build_job_progress_callback("scheduled-weekend-research")), run_async=True)
                last_weekend = key
                LOGGER.info("周末估值校准已触发")
        if verbose:
            LOGGER.debug("调度心跳：%s", now.isoformat())
        stop.wait(5)


def discover_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        sock.close()
        return address
    except Exception:
        return "127.0.0.1"


def run_supervisor(*, host="127.0.0.1", api_port=8710, frontend_port=5173, verbose=False) -> int:
    root = str(Path(__file__).resolve().parents[1])
    python = sys.executable
    services = [Service("api-server", [python, "-m", "jobs.api_server", "--host", host, "--port", str(api_port)], root)]
    _start(services[0])
    if not _wait_api(f"http://127.0.0.1:{api_port}/api/health"):
        LOGGER.error("API未能在30秒内就绪，前端不会启动")
        return 1
    frontend_host = "0.0.0.0" if host == "0.0.0.0" else host
    frontend = Service("react-frontend", ["npm", "run", "dev", "--", "--host", frontend_host, "--port", str(frontend_port)], str(Path(root) / "frontend"))
    _start(frontend)
    services.append(frontend)
    if _slack_ready():
        slack_config = dict(notification_config.apply_environment_overrides(notification_config.load_notification_config()).get("slack", {}) or {})
        slack_env = {**os.environ, "SLACK_BOT_TOKEN": str(slack_config.get("bot_token")), "SLACK_APP_TOKEN": str(slack_config.get("app_token"))}
        slack = Service("slack-bot", [python, "-m", "integrations.slack.bot"], root)
        slack.process = subprocess.Popen(slack.command, cwd=slack.cwd, env=slack_env)
        job_registry.update_job_status(slack.name, state="started", detail=" ".join(slack.command), pid=slack.process.pid, command=slack.command, metadata={"stage": "startup", "progress_pct": 100})
        LOGGER.info("已启动 %s，pid=%s", slack.name, slack.process.pid)
        services.append(slack)
    else:
        job_registry.update_job_status("slack-bot", state="skipped", detail="未配置SLACK_BOT_TOKEN/SLACK_APP_TOKEN")
    stop = threading.Event()
    scheduler = threading.Thread(target=scheduler_loop, args=(stop,), kwargs={"verbose": verbose}, daemon=True)
    scheduler.start()
    address = discover_lan_ip()
    print("启动状态：")
    for service in services:
        print(f"[OK] {service.name} pid={service.process.pid if service.process else '-'}")
    print(f"本机访问：http://127.0.0.1:{frontend_port}")
    if host == "0.0.0.0":
        print(f"局域网访问：http://{address}:{frontend_port}")
    try:
        while True:
            for service in services:
                if service.process and service.process.poll() is not None:
                    LOGGER.error("%s 已退出，code=%s", service.name, service.process.returncode)
                    return service.process.returncode or 1
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
        for service in reversed(services):
            if service.process and service.process.poll() is None:
                service.process.send_signal(signal.SIGTERM)
        for service in reversed(services):
            if service.process:
                try:
                    service.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    service.process.kill()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start valuation research system")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "0.0.0.0"])
    parser.add_argument("--api-port", type=int, default=8710)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run_supervisor(host=args.host, api_port=args.api_port, frontend_port=args.frontend_port, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
