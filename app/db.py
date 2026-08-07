"""SQLite connection management and schema migration (WAL mode)."""

import sqlite3
from pathlib import Path

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS niches (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    window_days        INTEGER NOT NULL DEFAULT 90,
    created_at         TEXT NOT NULL,
    last_research_at   TEXT,
    total_runs         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS research_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    niche_id       TEXT NOT NULL REFERENCES niches(id),
    started_at     TEXT NOT NULL,
    video_count    INTEGER NOT NULL DEFAULT 0,
    api_units_used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS videos (
    youtube_id       TEXT PRIMARY KEY,
    niche_id         TEXT NOT NULL REFERENCES niches(id),
    title            TEXT NOT NULL,
    channel_title    TEXT,
    thumbnail_url    TEXT,
    published_at     TEXT,
    duration_sec     INTEGER,
    views            INTEGER DEFAULT 0,
    likes            INTEGER DEFAULT 0,
    comments         INTEGER DEFAULT 0,
    tags_json        TEXT,
    description_txt  TEXT,
    engagement_score REAL DEFAULT 0,
    collected_at     TEXT NOT NULL,
    refreshed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_niche_score
    ON videos(niche_id, engagement_score DESC);

CREATE TABLE IF NOT EXISTS patterns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    niche_id    TEXT NOT NULL REFERENCES niches(id),
    run_id      INTEGER REFERENCES research_runs(id),
    kind        TEXT NOT NULL,
    value       TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 0,
    avg_score   REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_patterns_niche ON patterns(niche_id, kind);

CREATE TABLE IF NOT EXISTS packages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    niche_id      TEXT NOT NULL REFERENCES niches(id),
    created_at    TEXT NOT NULL,
    ai_source     TEXT NOT NULL,
    titles_json   TEXT NOT NULL,
    summary       TEXT NOT NULL,
    tags_json     TEXT NOT NULL,
    script        TEXT NOT NULL,
    thumbnails_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hooks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id  TEXT NOT NULL REFERENCES videos(youtube_id),
    niche_id         TEXT NOT NULL REFERENCES niches(id),
    hook_type        TEXT NOT NULL,
    hook_text        TEXT NOT NULL,
    score            REAL NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hooks_score ON hooks(niche_id, score DESC);
"""


class DB:
    """Thin connection helper. Each call gets a fresh connection; the app is
    low-traffic so we trade pooling for correctness."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or get_settings().db_path

    def connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=20000")
        return conn

    def init_schema(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None