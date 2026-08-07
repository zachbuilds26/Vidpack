"""YouTube Data API v3 adapter. Quota-aware, retry-capable, ToS-compliant."""

import logging
import random
import re
import time
from typing import Iterator

import httpx

from ..config import get_settings

logger = logging.getLogger("vidpack.youtube")

API_BASE = "https://www.googleapis.com/youtube/v3"

# cost in quota units
SEARCH_COST = 100
VIDEOS_LIST_COST = 1

ISO_DURATION_RE = re.compile(
    r"^P(?:((?P<days>\d+)D))?T?((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?$"
)

# ── content-quality helpers ──────────────────────────────────────────────
# The search endpoint with a bare niche query surfaces "meta" videos — tutorials
# about *making* channels (how to start one, grow it, monetize it, do it with AI).
# Those describe the niche rather than being content *in* it, so they pollute the
# cohort. We strip the noise words from the query and block obvious meta videos.

_QUERY_NOISE_RE = re.compile(
    r"\b(best|top|ideas?|channels?|videos?|content|seriees|how to|build|talk about)\b"
    r"|\bniches?\b", re.IGNORECASE,
)

# A video is "meta" when its title/channel reads like instructions for running a
# channel instead of making content in it. "How to draw cartoons" must survive;
# "how to make money with a cartoon channel" must not.
_TITLE_META_RE = re.compile(
    r"(\bhow to (make|start|build|grow|monetize) a (youtube |yt )?channel"
    r"|\bfaceless\b"
    r"|\byoutube automation\b"
    r"|\b(channel|niche) ideas?\b"
    r"|\b(channel|niche) (growth|monetization|earnings|income)\b"
    r"|grow (your|a |the )?(youtube |yt )?channel\b"
    r"|\b(monetiz|passive income|side hustle|affiliate income|make money online|earn money)\b"
    r"|make money (on|with|from) (youtube|channels?|a .+ channel)"
    r"|\b(with|using) (ai|a\.i|chatgpt|artificial intelligence)\b"
    r"|\$[0-9],?[0-9]{2,}( \/ | per | a month| daily| weekly)"
    r"|\bniches?\b (that make|to make|that pay|for|with high)"
    r"|\b(easiest|best|profitable) (niches?|channels?)\b"
    r"|\bskills you need\b|\btech stack\b)", re.IGNORECASE)

_CHANNEL_META_RE = re.compile(
    r"(niche|tutorial|courses?|monetiz|passive|make ?money"
    r"|(yt|youtuber|channel)[_-]?(starter|growth|playbook)"
    r"|auto ?mation)", re.IGNORECASE)


def clean_niche_query(name: str) -> str:
    """Reduce 'cartoon niche' -> 'cartoon' so the search hits content, not meta."""
    q = name.strip().lower()
    q = q.replace("niche", " ").replace("niches", " ")
    q = _QUERY_NOISE_RE.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip()
    words = q.split()
    if len(words) > 4:
        words = words[:4]
    return " ".join(words) or name.strip()


def _is_meta(video: dict) -> bool:
    title = (video.get("title") or "").lower()
    channel = (video.get("channel_title") or "").lower()
    if _TITLE_META_RE.search(title):
        return True
    if "youtube channel" in title or "create videos" in title:
        return True
    if _CHANNEL_META_RE.search(channel):
        return True
    return False


def _page_ok(item: dict) -> bool:
    return bool(item.get("youtube_id")) and not _is_meta(item)


def _dedupe_channels(items: list[dict], limit: int) -> list[dict]:
    """Cap how many videos any single channel can contribute, preserving order."""
    if not items:
        return []
    counts: dict[str, int] = {}
    out: list[dict] = []
    for it in items:
        ch = (it.get("channel_title") or "").lower()
        if counts.get(ch, 0) >= 3:
            continue
        counts[ch] = counts.get(ch, 0) + 1
        out.append(it)
        if len(out) >= limit:
            break
    return out


class YouTubeError(Exception):
    """Base adapter error."""


class YouTubeConfigError(YouTubeError):
    """Missing/invalid API key."""


class QuotaExceeded(YouTubeError):
    """Daily quota budget would be exceeded."""


class RateLimited(YouTubeError):
    """API returned 429 after retries."""


def iso8601_to_seconds(iso: str | None) -> int | None:
    if not iso:
        return None
    m = ISO_DURATION_RE.match(iso)
    if not m:
        return None
    parts = m.groupdict()
    return (
        int(parts["days"] or 0) * 86400
        + int(parts["hours"] or 0) * 3600
        + int(parts["minutes"] or 0) * 60
        + int(parts["seconds"] or 0)
    )


def _thumbnail_url(thumbs: dict | None) -> str | None:
    for key in ("maxres", "high", "medium", "standard"):
        t = (thumbs or {}).get(key)
        if t and t.get("url"):
            return t["url"]
    return None


class YouTubeClient:
    def __init__(self, api_key: str | None = None, quota_limit: int | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.youtube_api_key
        self.quota_limit = quota_limit or settings.youtube_quota_daily_limit
        self.used_quota = 0.0
        self.day_marker = time.strftime("%Y-%m-%d")

    def _check_quota(self, cost: int) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self.day_marker:
            self.day_marker = today
            self.used_quota = 0.0
        if self.used_quota + cost > self.quota_limit:
            raise QuotaExceeded(
                f"YouTube quota budget for today would be exceeded "
                f"({self.used_quota:.0f}/{self.quota_limit} used, +{cost} needed)."
            )

    def _get(self, path: str, params: dict, cost: int) -> dict:
        self._check_quota(cost)
        if not self.api_key:
            raise YouTubeConfigError(
                "YOUTUBE_API_KEY not set. Add it to .env (see .env.example)."
            )
        params = {**params, "key": self.api_key}
        attempts = 3
        for attempt in range(attempts):
            try:
                resp = httpx.get(
                    f"{API_BASE}/{path}",
                    params=params,
                    timeout=20,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                if attempt == attempts - 1:
                    raise YouTubeError(f"YouTube request failed: {exc}") from exc
                time.sleep(0.5 * (attempt + 1) * (1 + random.random()))
                continue

            if resp.status_code == 200:
                self.used_quota += cost
                return resp.json()
            if resp.status_code == 429:
                if attempt == attempts - 1:
                    raise RateLimited("YouTube API rate limited; try again shortly.")
                time.sleep(2 ** attempt * (1 + random.random()))
                continue
            if resp.status_code == 403:
                data = resp.json()
                reason = (data.get("error", {}).get("errors", [{}])[0].get("reason", ""))
                if "quota" in reason.lower():
                    raise QuotaExceeded("YouTube daily quota exhausted.")
                raise YouTubeError(f"YouTube API key rejected: {data.get('error', {}).get('message')}")
            if resp.status_code in (400, 404):
                data = resp.json()
                raise YouTubeError(
                    data.get("error", {}).get("message", "YouTube API error")
                )
            time.sleep(0.5 * (attempt + 1))
        raise YouTubeError("YouTube API unreachable.")

    def search_top(self, niche: str, max_results: int = 30,
                   window_days: int = 90) -> list[dict]:
        """Recent videos for a niche via the official search endpoint.

        Returns raw video references (id, title, snippet) with meta-content
        (tutorials about running a channel) filtered out and results kept
        channel-diverse, so the cohort reflects the niche itself.

        The caller then fetches full stats via `fetch_details`.
        """
        query = clean_niche_query(niche)
        picked: list[dict] = []
        first_batch: list[dict] = []
        for batch in self._search_pages(query, window_days):
            if not first_batch:
                first_batch = batch
            candidates = [it for it in batch if _page_ok(it)]
            picked = _dedupe_channels(picked + candidates, max_results)
            if len(picked) >= max_results:
                break
        # Too thin even after several pages — ship the unfiltered page rather
        # than telling the user the niche "has no content".
        if not picked and first_batch:
            picked = _dedupe_channels(first_batch, max_results)
        return picked[:max_results]

    def _search_pages(self, query: str, window_days: int) -> Iterator[list[dict]]:
        """Yield successive pages of parsed search results, lazily."""
        token = None
        for _ in range(3):
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "relevance",
                "relevanceLanguage": "en",
                "publishedAfter": _iso_before(days=window_days),
                "maxResults": 50,
            }
            if token:
                params["pageToken"] = token
            data = self._get("search", params, SEARCH_COST)
            raw = data.get("items", [])
            yield [self._parse_item(it) for it in raw]
            token = data.get("nextPageToken")
            if not token or not raw:
                break

    @staticmethod
    def _parse_item(item: dict) -> dict:
        vid = item.get("id", {})
        snippet = item.get("snippet", {})
        return {
            "youtube_id": vid.get("videoId"),
            "title": snippet.get("title", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt"),
            "thumbnail_url": _thumbnail_url(snippet.get("thumbnails")),
            "description_txt": snippet.get("description", ""),
        }

    def fetch_details(self, refs: list[dict]) -> list[dict]:
        """Batch-fetch stats/contentDetails for refs and merge back."""
        ids = [r["youtube_id"] for r in refs if r.get("youtube_id")]
        if not ids:
            return refs
        out = {r["youtube_id"]: r for r in refs}
        for chunk in (ids[i:i + 50] for i in range(0, len(ids), 50)):
            data = self._get(
                "videos",
                {"part": "statistics,contentDetails", "id": ",".join(chunk)},
                VIDEOS_LIST_COST,
            )
            for item in data.get("items", []):
                vid = item.get("id")
                stats = item.get("statistics", {})
                cd = item.get("contentDetails", {})
                if vid not in out:
                    continue
                rec = out[vid]
                rec["views"] = int(stats.get("viewCount", 0) or 0)
                rec["likes"] = int(stats.get("likeCount", 0) or 0)
                rec["comments"] = int(stats.get("commentCount", 0) or 0)
                rec["duration_sec"] = iso8601_to_seconds(cd.get("duration"))
        return list(out.values())


def _iso_before(days: int) -> str:
    t = time.gmtime(time.time() - days * 86400)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", t)


def get_client(api_key: str | None = None) -> YouTubeClient:
    return YouTubeClient(api_key)