"""
services/scheduler.py
---------------------
Simple, dependency-free scheduling for scans.

- Manual/API scans run in a background daemon thread (never block Flask).
- Optional interval loop runs scans automatically every N hours.
- Only one scan runs at a time; concurrent triggers are rejected.
- Every run is recorded in scan_history by run_scan itself.

Use from app.py (auto-start when SCAN_ENABLED=true) or scan.py (CLI/cron).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import config
from models.job import get_last_scan
from scanner import list_sources

logger = logging.getLogger("scam_sentry.scheduler")

_lock = threading.Lock()
_running = False
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_sched_thread: Optional[threading.Thread] = None


def is_running() -> bool:
    with _lock:
        return _running


def _set_running(value: bool) -> None:
    global _running
    with _lock:
        _running = value


def _default_sources() -> list[str]:
    if config.SCAN_SOURCES:
        known = set(list_sources())
        valid = [s for s in config.SCAN_SOURCES if s in known]
        if valid:
            return valid
        logger.warning("SCAN_SOURCES has no known sources; using all sources")
    return list_sources()


def trigger_async(sources: Optional[list[str]] = None, limit: int | None = None,
                  db_path: Optional[str] = None) -> dict[str, Any]:
    """Start a scan in a background thread. Returns accepted/queued status."""
    from services.scanner_service import run_scan

    with _lock:
        if _running:
            return {"accepted": False, "reason": "a scan is already running",
                    "status": "running"}
        global _thread
        _set_running_locked(True)
        wanted = sources or _default_sources()
        per_source = max(1, min(int(limit or config.SCAN_LIMIT), 100))

        def _work() -> None:
            try:
                logger.info("Background scan starting: sources=%s limit=%d", wanted, per_source)
                run_scan(sources=wanted, limit_per_source=per_source, db_path=db_path)
                logger.info("Background scan finished")
            except Exception:
                logger.exception("Background scan crashed")
            finally:
                _set_running(False)

        _thread = threading.Thread(target=_work, name="scam-sentry-scan", daemon=True)
        _thread.start()
        return {"accepted": True, "status": "running", "sources": wanted, "limit": per_source}


def _set_running_locked(value: bool) -> None:
    global _running
    _running = value


def _loop(interval_hours: float, limit: int, db_path: Optional[str]) -> None:
    logger.info("Scheduler loop started: every %.2fh", interval_hours)
    if config.SCAN_RUN_ON_STARTUP:
        time.sleep(5)  # let the web app finish booting first
        if not _stop_event.is_set():
            trigger_async(limit=limit, db_path=db_path)
            _wait_for_idle()
    while not _stop_event.wait(interval_hours * 3600):
        trigger_async(limit=limit, db_path=db_path)
        _wait_for_idle()
    logger.info("Scheduler loop stopped")


def _wait_for_idle() -> None:
    while is_running() and not _stop_event.is_set():
        time.sleep(2)


def start_background(interval_hours: float | None = None, limit: int | None = None,
                     db_path: Optional[str] = None) -> bool:
    """Start the interval scheduler thread. Returns False if already running.

    The stop flag is cleared here so a scheduler that was stopped can be
    started again (start -> stop -> start)."""
    global _sched_thread
    with _lock:
        if _sched_thread is not None and _sched_thread.is_alive():
            return False
        _stop_event.clear()
        hours = interval_hours or config.SCAN_INTERVAL_HOURS
        _sched_thread = threading.Thread(
            target=_loop, args=(hours, limit or config.SCAN_LIMIT, db_path),
            name="scam-sentry-scheduler", daemon=True)
        _sched_thread.start()
    logger.info("Scheduler enabled: every %.2fh (run-on-startup=%s)", hours, config.SCAN_RUN_ON_STARTUP)
    return True


def stop_background() -> None:
    """Signal the interval loop to stop. Safe to call when it isn't running."""
    _stop_event.set()


def get_status(db_path: Optional[str] = None) -> dict[str, Any]:
    """Current scan state + last recorded run (for API + dashboard)."""
    return {
        "running": is_running(),
        "status": "running" if is_running() else "idle",
        "scheduler_enabled": config.SCAN_ENABLED,
        "interval_hours": config.SCAN_INTERVAL_HOURS,
        "sources": _default_sources(),
        "last_scan": get_last_scan(db_path),
    }
