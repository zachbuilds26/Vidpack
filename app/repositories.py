"""Data access layer. All SQLite I/O lives here (single source of truth)."""

import json
import sqlite3
import time

from .db import DB, row_to_dict
from .scoring import engagement_score


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_before(days: int) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400)
    )


def slugify(name: str) -> str:
    out = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in name.lower())
    return "-".join(p for p in out.split("-") if p)


class Repositories:
    def __init__(self, db: DB | None = None) -> None:
        self._db = db or DB()

    # ---- niches ----------------------------------------------------------

    def create_niche(self, name: str, window_days: int = 90) -> dict:
        base = slugify(name)
        nid = base
        n = 2
        with self._db.connect() as conn:
            while True:
                row = conn.execute(
                    "SELECT id, name FROM niches WHERE id=?", (nid,)
                ).fetchone()
                if row is None or row["name"] == name:
                    break
                # slug taken by a different niche ("African Tales" vs
                # "african tales") — suffix instead of overwriting the name.
                nid = f"{base}-{n}"
                n += 1
            conn.execute(
                "INSERT INTO niches (id, name, window_days, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
                "window_days=excluded.window_days",
                (nid, name, window_days, _now()),
            )
        return self.get_niche(nid)

    def get_niche(self, niche_id: str) -> dict | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM niches WHERE id=?", (niche_id,)
            ).fetchone()
        return row_to_dict(row)

    def list_niches(self) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM niches ORDER BY last_research_at IS NULL, "
                "created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def touch_research(self, niche_id: str, total_runs: int) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE niches SET last_research_at=?, total_runs=? "
                "WHERE id=?",
                (_now(), total_runs + 1, niche_id),
            )

    # ---- research runs ---------------------------------------------------

    def create_run(self, niche_id: str, video_count: int, units: int) -> int:
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO research_runs (niche_id, started_at, video_count, "
                "api_units_used) VALUES (?, ?, ?, ?)",
                (niche_id, _now(), video_count, units),
            )
            return cur.lastrowid

    # ---- videos ----------------------------------------------------------

    def upsert_videos(self, niche_id: str, videos: list[dict]) -> None:
        scored = [
            {**v, "engagement_score": engagement_score(v.get("views", 0),
                                                        v.get("likes", 0),
                                                        v.get("comments", 0),
                                                        v.get("published_at"))}
            for v in videos
        ]
        now = _now()
        with self._db.connect() as conn:
            for v in scored:
                conn.execute(
                    """
                    INSERT INTO videos (youtube_id, niche_id, title,
                        channel_title, thumbnail_url, published_at,
                        duration_sec, views, likes, comments, tags_json,
                        description_txt, engagement_score, collected_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(youtube_id) DO UPDATE SET
                        views=excluded.views, likes=excluded.likes,
                        comments=excluded.comments,
                        tags_json=excluded.tags_json,
                        description_txt=excluded.description_txt,
                        engagement_score=excluded.engagement_score,
                        refreshed_at=excluded.refreshed_at
                    """,
                    (
                        v["youtube_id"], niche_id,
                        v.get("title", ""), v.get("channel_title", ""),
                        v.get("thumbnail_url"), v.get("published_at"),
                        v.get("duration_sec"), v.get("views", 0),
                        v.get("likes", 0), v.get("comments", 0),
                        json.dumps(v.get("tags", []), ensure_ascii=False),
                        v.get("description_txt") or "",
                        v["engagement_score"], now,
                    ),
                )

    def list_videos(self, niche_id: str, limit: int = 100) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE niche_id=? ORDER BY "
                "engagement_score DESC LIMIT ?",
                (niche_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.pop("tags_json") or "[]")
            out.append(d)
        return out

    def video_ids(self, niche_id: str) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT youtube_id FROM videos WHERE niche_id=?",
                (niche_id,),
            ).fetchall()
        return [r["youtube_id"] for r in rows]

    def prune_videos(self, niche_id: str, window_days: int) -> None:
        """Drop stored videos published before the niche's search window so the
        cohort keeps reflecting recent content. Hooks referencing pruned videos
        go with them (they are rebuilt on every research run anyway)."""
        cutoff = _iso_before(window_days)
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM hooks WHERE niche_id=? AND source_video_id IN ("
                "SELECT youtube_id FROM videos WHERE niche_id=? "
                "AND published_at IS NOT NULL AND published_at < ?)",
                (niche_id, niche_id, cutoff),
            )
            conn.execute(
                "DELETE FROM videos WHERE niche_id=? "
                "AND published_at IS NOT NULL AND published_at < ?",
                (niche_id, cutoff),
            )

    # ---- patterns --------------------------------------------------------

    def replace_patterns(self, niche_id: str, run_id: int, rows: list[dict]) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM patterns WHERE niche_id=?", (niche_id,))
            conn.executemany(
                "INSERT INTO patterns (niche_id, run_id, kind, value, "
                "occurrences, avg_score) VALUES (?,?,?,?,?,?)",
                [(niche_id, run_id, p["kind"], p["value"],
                  p["occurrences"], p.get("avg_score", 0.0)) for p in rows],
            )

    def list_patterns(self, niche_id: str) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM patterns WHERE niche_id=? "
                "ORDER BY occurrences DESC",
                (niche_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- packages ---------------------------------------------------------

    def save_package(self, niche_id: str, ai_source: str, package: dict) -> dict:
        with self._db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO packages (niche_id, created_at, ai_source,
                    titles_json, summary, tags_json, script, thumbnails_json)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    niche_id, _now(), ai_source,
                    json.dumps(package["titles"], ensure_ascii=False),
                    package["summary"],
                    json.dumps(package["tags"], ensure_ascii=False),
                    package["script"],
                    json.dumps(package["thumbnails"], ensure_ascii=False),
                ),
            )
            pid = cur.lastrowid
        return self.get_package(pid)

    def get_package(self, pid: int) -> dict | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM packages WHERE id=?", (pid,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["titles"] = json.loads(d.pop("titles_json"))
        d["tags"] = json.loads(d.pop("tags_json"))
        d["thumbnails"] = json.loads(d.pop("thumbnails_json"))
        return d

    def list_packages(self, niche_id: str) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM packages WHERE niche_id=? ORDER BY id DESC",
                (niche_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["titles"] = json.loads(d.pop("titles_json"))
            d["tags"] = json.loads(d.pop("tags_json"))
            d["thumbnails"] = json.loads(d.pop("thumbnails_json"))
            out.append(d)
        return out

    # ---- hooks ------------------------------------------------------------

    def replace_hooks(self, niche_id: str, hooks: list[dict]) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM hooks WHERE niche_id=?", (niche_id,))
            conn.executemany(
                """
                INSERT INTO hooks (source_video_id, niche_id, hook_type,
                    hook_text, score, updated_at) VALUES (?,?,?,?,?,?)
                """,
                [(h["video_id"], niche_id, h["type"], h["text"],
                  h["score"], _now()) for h in hooks],
            )

    def list_hooks(self, niche_id: str, limit: int = 100) -> list[dict]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hooks WHERE niche_id=? ORDER BY score DESC "
                "LIMIT ?",
                (niche_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_repos(db: DB | None = None) -> Repositories:
    return Repositories(db)