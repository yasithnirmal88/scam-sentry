"""Public job-source scanners. Each source subclasses BaseScanner."""

from .base import (BaseScanner, NormalizedJob, SCANNERS, get_scanner,
                   http_get, list_sources, normalize_url)
from .remoteok import RemoteOKScanner
from .remotive import RemotiveScanner
from .arbeitnow import ArbeitnowScanner
from .jobicy import JobicyScanner

__all__ = ["BaseScanner", "NormalizedJob", "SCANNERS", "get_scanner",
           "http_get", "list_sources", "normalize_url",
           "RemoteOKScanner", "RemotiveScanner",
           "ArbeitnowScanner", "JobicyScanner"]
