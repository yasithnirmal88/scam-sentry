"""Public job-source scanners. Each source subclasses BaseScanner."""

from .base import BaseScanner, NormalizedJob, SCANNERS, get_scanner, list_sources
from .remoteok import RemoteOKScanner
from .remotive import RemotiveScanner

__all__ = ["BaseScanner", "NormalizedJob", "SCANNERS", "get_scanner",
           "list_sources", "RemoteOKScanner", "RemotiveScanner"]
