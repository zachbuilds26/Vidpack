"""Research orchestration: YouTube fetch -> store -> pattern extraction."""

import logging

from ..adapters.youtube import YouTubeClient, get_client
from ..config import get_settings
from ..patterns import build_research_summary, extract_hooks
from ..repositories import Repositories

logger = logging.getLogger("vidpack.research")


def run_research(
    repos: Repositories,
    niche_id: str,
    youtube: YouTubeClient | None = None,
) -> dict:
    """Run a full research pass for a niche and return {videos, summary, runs}."""
    niche = repos.get_niche(niche_id)
    if niche is None:
        raise ValueError(f"Niche '{niche_id}' not found.")

    yt = youtube or get_client()

    name = niche["name"]
    max_videos = get_settings().research_max_videos
    window_days = int(niche.get("window_days") or 90)
    quota_before = float(getattr(yt, "used_quota", 0) or 0)
    refs = yt.search_top(name, max_results=max_videos, window_days=window_days)
    if not refs:
        raise ValueError(
            f"No results for '{name}' in the last {window_days} days. "
            f"Try a broader niche term."
        )
    videos = yt.fetch_details(refs)

    repos.upsert_videos(niche_id, videos)
    repos.prune_videos(niche_id, window_days)

    units = int((float(getattr(yt, "used_quota", 0) or 0) - quota_before) or 0)
    if not units:
        units = 100 + (1 if videos else 0)
    run_id = repos.create_run(niche_id, len(videos), units)
    repos.touch_research(niche_id, int(niche.get("total_runs") or 0))

    summary = build_research_summary(name, rehydrate(repos, niche_id))
    _persist_patterns_and_hooks(repos, niche_id, run_id, summary)

    return {
        "niche": niche_id,
        "run_id": run_id,
        "video_count": len(videos),
        "summary": summary,
        "videos": repos.list_videos(niche_id),
    }


def rehydrate(repos: Repositories, niche_id: str) -> list[dict]:
    """Videos as stored (with tags parsed and engagement scores recomputed)."""
    return repos.list_videos(niche_id)


def _persist_patterns_and_hooks(
    repos: Repositories, niche_id: str, run_id: int, summary: dict
) -> None:
    pattern_rows = []
    for h in summary.get("hook_types", []):
        pattern_rows.append({
            "kind": "hook_type", "value": h["type"],
            "occurrences": h["count"], "avg_score": h["share"],
        })
    for k in summary.get("keywords", []):
        pattern_rows.append({
            "kind": "keyword", "value": k["term"],
            "occurrences": k["freq"], "avg_score": k["weight"],
        })
    for b, c in summary.get("features", {}).get("duration_buckets", {}).items():
        pattern_rows.append({"kind": "duration", "value": b, "occurrences": c})
    repos.replace_patterns(niche_id, run_id, pattern_rows)

    videos = repos.list_videos(niche_id)
    hooks = extract_hooks(videos)["per_video"]
    repos.replace_hooks(niche_id, [
        {"video_id": h["video_id"], "type": h["type"],
         "text": h["title"], "score": h["score"]}
        for h in hooks
    ])