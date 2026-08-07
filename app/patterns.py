"""Rule-based research pattern extractor. Pure, no AI, unit-testable.

Suns a cohort of videos into:
  - hook types (listicle, how-to, question, ...) with occurrence counts
  - recurring keywords (weighted by engagement performance)
  - cohort features (duration buckets, best posting day, avg title length)

The result becomes the `research_summary` JSON consumed by the AI prompt or
used directly by the rule-based package generator.
"""

import re
from collections import Counter
from datetime import datetime

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "of",
    "for", "with", "by", "your", "you", "this", "that", "it", "is", "are",
    "be", "how", "what", "why", "best", "top", "get", "make", "use", "new",
    "do", "does", "can", "will", "watch", "video", "like", "really", "just",
    # common non-English function words so foreign-language titles do not
    # leak stopwords into the keyword list
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "aos", "yo", "tu", "mi", "en", "es", "son", "por", "que", "con", "para",
    "se", "su", "sus", "nos", "les", "les", "como", "mas", "muy", "tambien",
    "meu", "minha", "e", "o", "os", "as", "um", "uma", "do", "da", "dos",
    "das", "no", "na", "em", "com", "para", "ser", "est", "sont", "les",
    "des", "une", "du", "au", "aux", "et", "il", "elle", "on", "nous",
    "vous", "das", "der", "die", "und", "ein", "eine", "ist", "sind",
    "im", "mit", "von", "für", "nicht", "che", "per", "sono", "con",
    "come", "della", "del", "alla", "в", "на", "и", "с", "по", "из",
}

HOOK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("listicle", re.compile(r"\b(top|best|highest)\s+\d+|\b\d+\s+(ways|tips|reasons|things|ideas|tricks|secrets|hacks)", re.I)),
    ("number-led", re.compile(r"^\d+\s", re.I)),
    ("how-to", re.compile(r"(how\s+to|how\s+i|tutorial|guide|walkthrough|diy\b)", re.I)),
    ("question", re.compile(r"(\?|who\s|why\s|what\s+happens|can\s+you|should)", re.I)),
    ("comparison", re.compile(r"(vs\.?|\bversus\b|\bvs\b)", re.I)),
    ("urgency", re.compile(r"(now|before\s+it|don.t\s+miss|last|while\s+you|today)", re.I)),
    ("benefit", re.compile(r"(boost|grow|learn|save|win|earn|free|profit|\bhack\b|fast|easy|promise)", re.I)),
    ("curiosity", re.compile(r"(you\s+won't|nobody|released|crazy|shocked|truth|behind)", re.I)),
]


def _tokens(title: str) -> list[str]:
    """Lowercase word tokens, numbers collapsed to a single placeholder.

    Words containing non-ASCII letters are dropped entirely: accents make
    foreign titles fragment into gibberish ("selección" -> "selecci"), and
    those fragments pollute the keyword list. Non-ASCII titles still
    contribute hook/feature signals, just no keyword terms.
    """
    text = title.lower()
    text = re.sub(r"\d+", "<n>", text)
    # split on unicode-aware boundaries first so accented words are detected
    # whole, then re-filter to ascii-only tokens
    raw = re.findall(r"[\w']{2,}|<n>", text)
    out: list[str] = []
    for w in raw:
        if w.startswith("<") or not w.isascii():
            continue
        tok = re.sub(r"[^a-z']", "", w)
        if tok in STOPWORDS or not tok:
            continue
        out.append(tok)
    return out


def classify_hooks(title: str) -> list[str]:
    """Return list of hook types matched by the title (may be empty => 'plain')."""
    matched = [kind for kind, pat in HOOK_PATTERNS if pat.search(title)]
    return matched or ["plain"]


def extract_hooks(videos: list[dict]) -> dict:
    """Aggregate hook types + best fragment per video for the library."""
    per_video = []
    for v in videos:
        title = (v.get("title") or " ").strip()
        kinds = classify_hooks(title)
        per_video.append({
            "video_id": v.get("youtube_id"),
            "title": title,
            "type": "|".join(map(str, kinds)).replace("plain", "plain"),
            "score": v.get("engagement_score", 0.0),
        })
    agg: Counter[str] = Counter()
    for p in per_video:
        for k in p["type"].split("|"):
            agg[k] += 1
    total = sum(agg.values()) or 1
    turn_summary = [
        {"type": k, "count": c, "share": round(c / total, 3)}
        for k, c in agg.most_common()
    ]
    return {"per_video": per_video, "aggregate": turn_summary}


def extract_keywords(videos: list[dict], top_n: int = 12) -> list[dict]:
    """Terms weighted by summed engagement of videos that use them."""
    freq: Counter[str] = Counter()
    score: dict[str, float] = {}
    for v in videos:
        eng = v.get("engagement_score", 0.0)
        title = v.get("title") or " "
        for tok in set(_tokens(title)):
            freq[tok] += 1
            score[tok] = score.get(tok, 0.0) + eng
        for tag in (v.get("tags") or []):
            tag = str(tag).strip().lower()
            if len(tag) > 2:
                freq[tag] += 1
                score[tag] = score.get(tag, 0.0) + eng * 0.5

    ranked = sorted(
        (t for t in freq if freq[t] >= 2),
        key=lambda t: (score.get(t, 0.0) / max(freq[t], 1), t),
        reverse=True,
    )
    return [
        {"term": t, "freq": freq[t], "weight": round(score.get(t, 0.0), 3)}
        for t in ranked[:top_n]
    ]


def duration_bucket(duration_sec: int | None) -> str | None:
    if duration_sec is None:
        return None
    mins = duration_sec / 60
    if mins < 1:
        return "under-1m"
    if mins < 3:
        return "1-3m"
    if mins < 5:
        return "3-5m"
    if mins < 10:
        return "5-10m"
    if mins < 20:
        return "10-20m"
    return "20m+"


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def extract_features(videos: list[dict]) -> dict:
    buckets: Counter[str] = Counter()
    weekday_scores: dict[int, list[float]] = {}
    lengths: list[int] = []

    for video in videos:
        b = duration_bucket(video.get("duration_sec"))
        if b:
            buckets[b] += 1
        lengths.append(len(video.get("title") or " "))
        try:
            dt = datetime.fromisoformat(
                (video.get("published_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            dt = None
        if dt is not None:
            weekday_scores.setdefault(dt.weekday(), []).append(
                video.get("engagement_score", 0.0)
            )

    best_weekday, best_avg = None, -1.0
    for wd, scores in weekday_scores.items():
        avg = sum(scores) / len(scores)
        if avg > best_avg:
            best_avg, best_weekday = avg, WEEKDAYS[wd]

    return {
        "duration_buckets": dict(buckets.most_common()),
        "best_post_day": best_weekday,
        "avg_title_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
    }


def build_research_summary(niche: str, videos: list[dict]) -> dict:
    hooks = extract_hooks(videos)
    return {
        "niche": niche,
        "video_count": len(videos),
        "hook_types": hooks["aggregate"],
        "keywords": extract_keywords(videos),
        "features": extract_features(videos),
    }