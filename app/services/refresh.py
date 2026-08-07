"""Refresh job: re-poll stats on observed videos, recompute scores/hooks."""

import logging

from ..adapters.youtube import get_client
from ..patterns import extract_hooks
from ..repositories import Repositories
from ..scoring import engagement_score

logger = logging.getLogger("vidpack.refresh")


def refresh(
    repos: Repositories,
    niche_id: str,
    youtube=None,
) -> dict:
    """Re-pull stats for the stored videos of a niche (1 quota unit each)."""
    niche = repos.get_niche(niche_id)
    if niche is None:
        raise ValueError(f"Niche '{niche_id}' not found.")

    yt = youtube or get_client()
    existing = repos.list_videos(niche_id)
    if not existing:
        raise ValueError("No stored videos for this niche yet.")

    refs = [dict(v) for v in existing]
    details = yt.fetch_details(refs)

    repos.upsert_videos(niche_id, details)

    videos = repos.list_videos(niche_id)
    hooks = extract_hooks(videos)["per_video"]
    repos.replace_hooks(niche_id, [
        {"video_id": h["video_id"], "type": h["type"],
         "text": h["title"], "score": h["score"]}
        for h in hooks
    ])

    scores = [(v["title"], v["engagement_score"]) for v in videos]
    return {"niche_id": niche_id, "refreshed": len(scores),
            "top": sorted(scores, key=lambda x: x[1], reverse=True)[:5]}