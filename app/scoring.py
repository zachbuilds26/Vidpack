"""Engagement scoring. Pure math so it can be unit-tested in isolation."""

import math
from datetime import datetime, timezone


def parse_iso(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def age_days(iso: str | None, now: datetime | None = None) -> int:
    """Days since publish, floored at 1."""
    now = now or datetime.now(timezone.utc)
    dt = parse_iso(iso)
    if dt is None:
        return 1
    return max(int((now - dt).total_seconds() // 86400), 1)


def engagement_score(views: int, likes: int, comments: int, published_at: str | None) -> float:
    """0.5 * views/day + 0.3 * like-rate + 0.2 * comment-rate (per-1k)."""
    age = age_days(published_at)
    views = max(views, 0)
    likes = max(likes, 0)
    comments = max(comments, 0)
    views_rate = views / age
    like_ratio = likes / views if views else 0.0
    comment_ratio = (comments / views * 1000) if views else 0.0
    return round(
        0.5 * math.log1p(views_rate)
        + 0.3 * like_ratio * 10
        + 0.2 * comment_ratio,
        4,
    )


def percentile_rank(value: float, cohort: list[float]) -> float:
    """Share of cohort values <= value, 0..1."""
    if not cohort:
        return 0.0
    return sum(1 for v in cohort if v <= value) / len(cohort)