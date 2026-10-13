"""
scan.py
-------
CLI for Job Risk Scanner — for cron jobs and manual runs without the web app.

  python scan.py                        # one scan, all sources
  python scan.py --sources remotive jobicy --limit 10
  python scan.py --daemon               # interval loop (same as in-app scheduler)
  python scan.py --list-sources

Cron example (every 6 hours):
  0 */6 * * * cd /path/to/fakejob_app && python scan.py >> scan.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import sys

import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                    format=config.LOG_FORMAT)
logger = logging.getLogger("scam_sentry.scan_cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scam Sentry job scanner")
    parser.add_argument("--sources", nargs="*", default=None,
                        help="Sources to scan (default: all registered)")
    parser.add_argument("--limit", type=int, default=config.SCAN_LIMIT,
                        help="Jobs per source (1-100)")
    parser.add_argument("--list-sources", action="store_true",
                        help="List available sources and exit")
    parser.add_argument("--daemon", action="store_true",
                        help="Run forever on SCAN_INTERVAL_HOURS loop")
    parser.add_argument("--interval-hours", type=float, default=config.SCAN_INTERVAL_HOURS,
                        help="Daemon loop interval in hours")
    args = parser.parse_args(argv)

    from scanner import list_sources
    if args.list_sources:
        print("\n".join(list_sources()))
        return 0

    limit = max(1, min(args.limit, 100))
    if args.daemon:
        import time
        from services.scanner_service import run_scan
        logger.info("Daemon mode: scan every %.2fh", args.interval_hours)
        try:
            while True:
                summary = run_scan(sources=args.sources, limit_per_source=limit)
                logger.info("Daemon scan done: status=%s stored=%d",
                            summary.get("status"), summary.get("stored"))
                time.sleep(args.interval_hours * 3600)
        except KeyboardInterrupt:
            logger.info("Daemon stopped")
            return 0

    from services.scanner_service import run_scan
    summary = run_scan(sources=args.sources, limit_per_source=limit)
    print("status=%s fetched=%d evaluated=%d stored=%d skipped=%d duplicates=%d" % (
        summary.get("status"), summary.get("fetched"), summary.get("evaluated"),
        summary.get("stored"), summary.get("skipped"), summary.get("duplicates")))
    if summary.get("errors"):
        print("errors: %s" % summary["errors"])
    # "empty" means the scan completed cleanly but found nothing to store, so it
    # is not treated as a failure for exit-code purposes.
    return 0 if summary.get("status") in ("success", "partial", "empty") else 1


if __name__ == "__main__":
    sys.exit(main())
