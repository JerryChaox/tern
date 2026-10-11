import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY,            -- arXiv id without version, e.g. 2610.05630
  title TEXT NOT NULL,
  abstract TEXT NOT NULL,
  authors TEXT NOT NULL,          -- JSON list
  categories TEXT NOT NULL,       -- space separated
  primary_cat TEXT NOT NULL,
  published TEXT NOT NULL,        -- ISO timestamp of v1
  week TEXT NOT NULL,             -- Monday (YYYY-MM-DD) of published
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS papers_week ON papers(week);

-- Which category query brought a paper in. Per-category shares are computed
-- over this membership, so sampled weeks stay unbiased per category.
CREATE TABLE IF NOT EXISTS fetched (
  paper_id TEXT NOT NULL,
  cat TEXT NOT NULL,
  PRIMARY KEY (paper_id, cat)
);
CREATE INDEX IF NOT EXISTS fetched_cat ON fetched(cat);

-- True weekly submission totals per category (arXiv opensearch:totalResults).
CREATE TABLE IF NOT EXISTS volume (
  cat TEXT NOT NULL,
  week TEXT NOT NULL,
  total INTEGER NOT NULL,
  sampled INTEGER NOT NULL,       -- 1 if papers for this week are a sample
  updated_at TEXT NOT NULL,
  PRIMARY KEY (cat, week)
);

CREATE TABLE IF NOT EXISTS signals (
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  grp TEXT NOT NULL,
  pattern TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  custom INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_signal (
  paper_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  PRIMARY KEY (paper_id, slug)
);
CREATE INDEX IF NOT EXISTS paper_signal_slug ON paper_signal(slug);

-- Insights are keyed by (kind, subject, week): re-running the analysis within
-- a week refreshes the card; a new week yields a new card, so the feed is a
-- running research log.
CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  subject TEXT NOT NULL,
  week TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  score REAL NOT NULL,
  evidence TEXT NOT NULL,         -- JSON
  status TEXT NOT NULL DEFAULT 'new',  -- new | starred | dismissed
  first_seen TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (kind, subject, week)
);

CREATE TABLE IF NOT EXISTS theses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  slugs TEXT NOT NULL,            -- JSON list of signal slugs
  stance TEXT NOT NULL,           -- up | down
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,           -- running | ok | error
  detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
"""

_lock = threading.RLock()
_conn = None


def conn():
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def backup(dest):
    """Consistent copy of the live database (safe while other threads write)."""
    with _lock:
        out = sqlite3.connect(dest)
        try:
            conn().backup(out)
        finally:
            out.close()


def replace_with(path):
    """Read-only instance: swap the database file for a newly published copy."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        for suffix in ("-wal", "-shm"):
            Path(f"{config.DB_PATH}{suffix}").unlink(missing_ok=True)
        os.replace(path, config.DB_PATH)
        conn()


@contextmanager
def tx():
    """Serialized write transaction (one process, many threads)."""
    with _lock:
        c = conn()
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def kv_get(k, default=None):
    row = q1("SELECT v FROM kv WHERE k=?", (k,))
    return json.loads(row["v"]) if row else default


def kv_set(k, v):
    with tx() as c:
        c.execute("INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (k, json.dumps(v, ensure_ascii=False)))
