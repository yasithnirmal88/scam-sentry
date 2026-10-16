"""
models/storage.py
-----------------
Storage backends for job listings + scan history.

Two interchangeable backends implement the same private interface:

- ``SQLiteBackend``   : stdlib ``sqlite3`` (local default, file path).
- ``PostgresBackend`` : ``psycopg`` 3 (used when ``DATABASE_URL`` is set —
  Render / Neon / Supabase free Postgres).

``models/job.py`` stays the public facade and picks a backend per call:
an explicit ``db_path`` wins (a ``postgres://`` URL selects Postgres), then
``DATABASE_URL``, then the local SQLite file. Postgres uses short-lived
connections that are always closed; there is no cross-call connection state.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import config
import location

# Columns updated when a scan re-encounters a URL (posting fields are kept).
_UPDATE_COLS = (
    "title", "company", "location", "description", "raw_description",
    "source", "posted_at", "overall_risk_level", "risk_categories",
    "confidence", "key_indicators", "recommended_actions",
    "employer_verification", "summary", "hybrid_score",
    "rule_score", "ml_score", "industry", "job_role", "scanned_at",
    "country", "region",
)

_JOB_COLS = (
    "title", "company", "location", "description", "raw_description",
    "url", "source", "posted_at", "overall_risk_level", "risk_categories",
    "confidence", "key_indicators", "recommended_actions",
    "employer_verification", "summary", "hybrid_score",
    "rule_score", "ml_score", "industry", "job_role", "scanned_at",
    "country", "region",
)

# Lift an older jobs table (created before the industry/role/country features)
# up to the current schema. idempotent on SQLite via the PRAGMA check in init().
_MIGRATE_COLUMNS = (
    ("industry", "ALTER TABLE jobs ADD COLUMN industry TEXT NOT NULL DEFAULT 'Other'"),
    ("job_role", "ALTER TABLE jobs ADD COLUMN job_role TEXT NOT NULL DEFAULT 'Other'"),
    ("country", "ALTER TABLE jobs ADD COLUMN country TEXT NOT NULL DEFAULT ''"),
    ("region", "ALTER TABLE jobs ADD COLUMN region TEXT NOT NULL DEFAULT ''"),
)

_SCAN_COLS = (
    "started_at", "finished_at", "sources", "fetched", "evaluated",
    "stored", "skipped", "duplicates", "status", "errors",
)

_LEVELS = {"low", "medium", "high", "critical"}


def location_backfill_updates(rows: Any) -> list[tuple[str, str, Any]]:
    """``(country, region, id)`` updates for rows missing country/region.

    Rows stored before the country/region columns existed get them defaulted to
    ``''`` on migration, which leaves the dashboard pickers empty until the next
    re-scan. This derives the values from the stored free-text ``location`` so
    old data becomes filterable immediately. A row is skipped when both values
    are already set, and only inferred values are written (never overwritten).
    """
    updates: list[tuple[str, str, Any]] = []
    for row in rows:
        country = (row["country"] or "").strip()
        region = (row["region"] or "").strip()
        if country and region:
            continue
        inferred_country, inferred_region = location.normalize_location(row["location"])
        new_country = country or inferred_country
        new_region = region or inferred_region
        if new_country != country or new_region != region:
            updates.append((new_country, new_region, row["id"]))
    return updates


def normalize_risk_level(risk_level: Optional[str]) -> Optional[str]:
    if not risk_level:
        return None
    return risk_level.capitalize() if risk_level.lower() in _LEVELS else risk_level


def coerce_limit(limit: Any, default: int = 50, hard_max: int = 200) -> int:
    try:
        return max(1, min(int(limit or default), hard_max))
    except (TypeError, ValueError):
        return default


def coerce_offset(offset: Any) -> int:
    try:
        return max(0, int(offset or 0))
    except (TypeError, ValueError):
        return 0


def row_to_job(row: Any) -> dict[str, Any]:
    """Normalize a DB row (sqlite3.Row or dict) into a job dict."""
    d = dict(row)
    for col in ("risk_categories", "key_indicators", "recommended_actions"):
        try:
            d[col] = json.loads(d.get(col) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[col] = []
    try:
        d["employer_verification"] = json.loads(d.get("employer_verification") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["employer_verification"] = {}
    return d


def row_to_scan(row: Any) -> dict[str, Any]:
    d = dict(row)
    for col, default in (("sources", []), ("errors", {})):
        try:
            d[col] = json.loads(d.get(col) or "null") or default
        except (json.JSONDecodeError, TypeError):
            d[col] = default
    return d


class _BaseBackend:
    """Shared query-building; subclasses supply placeholder + LIKE dialect."""

    _ph = ":{}"        # named-parameter template
    _like = "LIKE"     # case sensitivity differs between engines

    def _p(self, name: str) -> str:
        return self._ph.format(name)

    def _filters(self, risk_level: Optional[str], source: Optional[str],
                 query: Optional[str], industry: Optional[str] = None,
                 role: Optional[str] = None, country: Optional[str] = None,
                 region: Optional[str] = None,
                 remote: Optional[bool] = None) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        rl = normalize_risk_level(risk_level)
        if rl:
            clauses.append("overall_risk_level = " + self._p("rl"))
            params["rl"] = rl
        if source:
            clauses.append("source = " + self._p("src"))
            params["src"] = source
        industry = (industry or "").strip()
        if industry:
            clauses.append("industry = " + self._p("ind"))
            params["ind"] = industry
        role = (role or "").strip()
        if role:
            clauses.append("job_role = " + self._p("role"))
            params["role"] = role
        country = (country or "").strip()
        if country:
            # Match the normalized column, and fall back to the raw location
            # text so legacy/unclassified rows ("Berlin, Germany") still match.
            canonical = location.canonical_country(country) or country
            clauses.append(
                f"(country = {self._p('country')} "
                f"OR location {self._like} {self._p('country_like')})")
            params["country"] = canonical
            params["country_like"] = f"%{canonical}%"
        region = (region or "").strip()
        if region:
            canonical = location.canonical_region(region) or region
            clauses.append(
                f"(region = {self._p('region')} OR location {self._like} {self._p('region_like')})")
            params["region"] = canonical
            params["region_like"] = f"%{region}%"
        if remote is not None:
            clauses.append(self._remote_clause(bool(remote), params))
        if query:
            p = self._p("q")
            like = self._like
            clauses.append(
                f"(title {like} {p} OR company {like} {p} OR description {like} {p})"
            )
            params["q"] = f"%{query}%"
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def _remote_clause(self, is_remote: bool, params: dict[str, Any]) -> str:
        """Remote/on-site predicate over the location text (dialect-aware)."""
        parts = ["country = " + self._p("rem_country")]
        params["rem_country"] = location.REMOTE
        for i, token in enumerate(("remote", "worldwide", "anywhere")):
            key = "rem_tok_%d" % i
            parts.append(f"location {self._like} " + self._p(key))
            params[key] = f"%{token}%"
        positive = "(" + " OR ".join(parts) + ")"
        return positive if is_remote else "NOT " + positive

    def _list_sql(self, where: str) -> str:
        return (f"SELECT * FROM jobs {where} "
                f"ORDER BY scanned_at DESC, id DESC "
                f"LIMIT {self._p('limit')} OFFSET {self._p('offset')}")

    def list_all_jobs(self, limit: int = 2000, risk_level=None, source=None,
                      industry=None, role=None, country=None, region=None,
                      remote=None) -> list[dict[str, Any]]:
        """Up to ``limit`` rows matching the filters, newest first.

        Used by the CV matcher as its candidate pool. Unlike ``list_jobs`` this
        allows a much larger window (still hard-capped) so matching sees the
        whole store instead of a dashboard page.
        """
        where, params = self._filters(risk_level, source, None, industry, role,
                                      country, region, remote)
        params["limit"] = coerce_limit(limit, default=2000, hard_max=5000)
        sql = (f"SELECT * FROM jobs {where} "
               f"ORDER BY scanned_at DESC, id DESC LIMIT {self._p('limit')}")
        return [row_to_job(r) for r in self._fetch_all(sql, params)]

    # interface -----------------------------------------------------------
    def init(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def save_job(self, payload: dict[str, Any]) -> int:  # pragma: no cover
        raise NotImplementedError

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def list_jobs(self, risk_level, source, query, limit, offset,
                  industry=None, role=None, country=None, region=None,
                  remote=None) -> list[dict[str, Any]]:
        where, params = self._filters(risk_level, source, query, industry, role,
                                      country, region, remote)
        params["limit"] = coerce_limit(limit)
        params["offset"] = coerce_offset(offset)
        rows = self._fetch_all(self._list_sql(where), params)
        return [row_to_job(r) for r in rows]

    def count_jobs(self, risk_level: Optional[str] = None, source: Optional[str] = None,
                   query: Optional[str] = None, industry: Optional[str] = None,
                   role: Optional[str] = None, country: Optional[str] = None,
                   region: Optional[str] = None, remote: Optional[bool] = None) -> int:
        where, params = self._filters(risk_level, source, query, industry, role,
                                      country, region, remote)
        row = self._fetch_one(f"SELECT COUNT(*) AS n FROM jobs {where}", params)
        return int(row["n"]) if row else 0

    def location_options(self) -> dict[str, list[str]]:
        """Distinct non-empty countries/regions present, alphabetically."""
        try:
            countries = self._fetch_all(
                "SELECT DISTINCT country FROM jobs WHERE country <> '' "
                "ORDER BY country")
            regions = self._fetch_all(
                "SELECT DISTINCT region FROM jobs WHERE region <> '' "
                "ORDER BY region")
        except Exception:
            return {"countries": [], "regions": []}
        return {
            "countries": [str(r["country"]) for r in countries],
            "regions": [str(r["region"]) for r in regions],
        }

    def risk_counts(self) -> dict[str, int]:
        rows = self._fetch_all(
            "SELECT overall_risk_level, COUNT(*) AS n FROM jobs "
            "GROUP BY overall_risk_level")
        out = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        for r in rows:
            out[str(r["overall_risk_level"])] = int(r["n"])
        out["total"] = sum(out.values())
        return out

    def get_last_scan(self) -> Optional[dict[str, Any]]:
        try:
            row = self._fetch_one(
                "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1")
        except Exception:
            return None
        return row_to_scan(row) if row else None

    def list_scan_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent scan runs, newest first (empty on any error)."""
        try:
            rows = self._fetch_all(
                "SELECT * FROM scan_history ORDER BY id DESC "
                "LIMIT " + self._p("limit"),
                {"limit": coerce_limit(limit, default=20, hard_max=100)})
        except Exception:
            return []
        return [row_to_scan(r) for r in rows]


class SQLiteBackend(_BaseBackend):
    _ph = ":{}"
    _like = "LIKE"

    SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    raw_description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    overall_risk_level TEXT NOT NULL DEFAULT 'Low',
    risk_categories TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'Low',
    key_indicators TEXT NOT NULL DEFAULT '[]',
    recommended_actions TEXT NOT NULL DEFAULT '[]',
    employer_verification TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    hybrid_score REAL NOT NULL DEFAULT 0.0,
    rule_score REAL NOT NULL DEFAULT 0.0,
    ml_score REAL NOT NULL DEFAULT 0.0,
    industry TEXT NOT NULL DEFAULT 'Other',
    job_role TEXT NOT NULL DEFAULT 'Other',
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    scanned_at TEXT NOT NULL DEFAULT '',
    UNIQUE(url)
);
CREATE INDEX IF NOT EXISTS idx_jobs_risk ON jobs(overall_risk_level);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_industry ON jobs(industry);
CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(job_role);
CREATE INDEX IF NOT EXISTS idx_jobs_country ON jobs(country);
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    fetched INTEGER NOT NULL DEFAULT 0,
    evaluated INTEGER NOT NULL DEFAULT 0,
    stored INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unknown',
    errors TEXT NOT NULL DEFAULT '{}'
);
"""

    def __init__(self, path: str) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection and always close it.

        sqlite3.Connection's own context manager commits/rolls back but does
        *not* close the file handle, which leaks a connection (and an open fd)
        on every call. This wrapper guarantees closure.

        Note: unlike the raw sqlite3 connection context manager, this wrapper
        does NOT commit. Every write path must call ``conn.commit()``
        explicitly before the connection is closed on exit.
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> str:
        with self._connect() as conn:
            # Lift a pre-existing jobs table up first so the SCHEMA script's
            # new indexes on industry/job_role can be created (SQLite has no
            # ALTER ... ADD COLUMN IF NOT EXISTS, hence the PRAGMA check).
            self._ensure_columns(conn)
            conn.executescript(self.SCHEMA)
            self._backfill_locations(conn)
            conn.commit()
        return self.path

    @staticmethod
    def _backfill_locations(conn: sqlite3.Connection) -> None:
        """Derive country/region for pre-existing rows (idempotent)."""
        rows = conn.execute(
            "SELECT id, location, country, region FROM jobs "
            "WHERE location <> '' AND (country = '' OR region = '')").fetchall()
        updates = location_backfill_updates(rows)
        if updates:
            conn.executemany(
                "UPDATE jobs SET country = ?, region = ? WHERE id = ?", updates)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        """Add industry/job_role to a pre-existing jobs table (older DBs)."""
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not has_table:
            return
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for name, ddl in _MIGRATE_COLUMNS:
            if name not in existing:
                conn.execute(ddl)

    def describe(self) -> str:
        return f"sqlite:{self.path}"

    def _fetch_one(self, sql: str, params: Any = None) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params or {}).fetchone()

    def _fetch_all(self, sql: str, params: Any = None) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params or {}).fetchall()

    def save_job(self, payload: dict[str, Any]) -> int:
        cols = ", ".join(_JOB_COLS)
        placeholders = ", ".join(self._p(c) for c in _JOB_COLS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _UPDATE_COLS)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(url) DO UPDATE SET {updates}",
                payload,
            )
            conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                "SELECT id FROM jobs WHERE url = " + self._p("url"),
                {"url": payload["url"]}).fetchone()
            return int(row["id"]) if row else 0

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:
        row = self._fetch_one(
            "SELECT * FROM jobs WHERE id = " + self._p("id"), {"id": job_id})
        return row_to_job(row) if row else None

    def record_scan_run(self, payload: dict[str, Any]) -> int:
        cols = ", ".join(_SCAN_COLS)
        placeholders = ", ".join(self._p(c) for c in _SCAN_COLS)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO scan_history ({cols}) VALUES ({placeholders})",
                payload,
            )
            conn.commit()
            return int(cur.lastrowid or 0)


class PostgresBackend(_BaseBackend):
    _ph = "%({})s"
    _like = "ILIKE"

    SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    raw_description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    overall_risk_level TEXT NOT NULL DEFAULT 'Low',
    risk_categories TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'Low',
    key_indicators TEXT NOT NULL DEFAULT '[]',
    recommended_actions TEXT NOT NULL DEFAULT '[]',
    employer_verification TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    hybrid_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    rule_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    ml_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    industry TEXT NOT NULL DEFAULT 'Other',
    job_role TEXT NOT NULL DEFAULT 'Other',
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    scanned_at TEXT NOT NULL DEFAULT '',
    UNIQUE (url)
);
CREATE INDEX IF NOT EXISTS idx_jobs_risk ON jobs (overall_risk_level);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source);
CREATE INDEX IF NOT EXISTS idx_jobs_industry ON jobs (industry);
CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs (job_role);
CREATE INDEX IF NOT EXISTS idx_jobs_country ON jobs (country);
CREATE TABLE IF NOT EXISTS scan_history (
    id BIGSERIAL PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    fetched INTEGER NOT NULL DEFAULT 0,
    evaluated INTEGER NOT NULL DEFAULT 0,
    stored INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unknown',
    errors TEXT NOT NULL DEFAULT '{}'
);
"""

    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        """Yield a short-lived psycopg connection, always closed."""
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(self.url, row_factory=dict_row)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.SCHEMA)
                # Lift older databases to the current schema (idempotent in
                # Postgres via ADD COLUMN IF NOT EXISTS).
                for _, ddl in _MIGRATE_COLUMNS:
                    cur.execute(ddl.replace(
                        "ALTER TABLE jobs ADD COLUMN",
                        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS"))
                cur.execute(
                    "SELECT id, location, country, region FROM jobs "
                    "WHERE location <> '' AND (country = '' OR region = '')")
                updates = location_backfill_updates(cur.fetchall())
                if updates:
                    cur.executemany(
                        "UPDATE jobs SET country = %(country)s, "
                        "region = %(region)s WHERE id = %(id)s",
                        [{"country": c, "region": r, "id": i}
                         for c, r, i in updates])
            conn.commit()
        return self.url

    def describe(self) -> str:
        return "postgres"

    def reset(self) -> str:
        """Drop and recreate the schema (tests / re-migration)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS jobs; "
                            "DROP TABLE IF EXISTS scan_history;")
            conn.commit()
        return self.init()

    def _fetch_one(self, sql: str, params: Any = None) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                return cur.fetchone()

    def _fetch_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                return cur.fetchall()

    def save_job(self, payload: dict[str, Any]) -> int:
        cols = ", ".join(_JOB_COLS)
        placeholders = ", ".join(self._p(c) for c in _JOB_COLS)
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _UPDATE_COLS)
        sql = (f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
               f"ON CONFLICT (url) DO UPDATE SET {updates} RETURNING id")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
                row = cur.fetchone()
            conn.commit()
        return int(row["id"]) if row else 0

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:
        row = self._fetch_one(
            "SELECT * FROM jobs WHERE id = " + self._p("id"), {"id": job_id})
        return row_to_job(row) if row else None

    def record_scan_run(self, payload: dict[str, Any]) -> int:
        cols = ", ".join(_SCAN_COLS)
        placeholders = ", ".join(self._p(c) for c in _SCAN_COLS)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO scan_history ({cols}) VALUES ({placeholders}) "
                    f"RETURNING id", payload)
                row = cur.fetchone()
            conn.commit()
        return int(row["id"]) if row else 0


def select_backend(db_path: Optional[str] = None) -> _BaseBackend:
    """Pick a backend: explicit db_path wins, then DATABASE_URL, then SQLite."""
    locator = (db_path or "").strip()
    if locator:
        if locator.startswith(("postgres://", "postgresql://")):
            return PostgresBackend(locator)
        return SQLiteBackend(locator)
    url = (getattr(config, "DATABASE_URL", "") or "").strip()
    if url:
        return PostgresBackend(url)
    return SQLiteBackend(config.DATABASE_PATH)
