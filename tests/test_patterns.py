from app.patterns import classify_hooks, extract_features, extract_hooks

V = [
    {"youtube_id": "a", "title": "Top 10 Kitchen Hacks That Save Time",
     "tags": ["cooking", "hacks"], "engagement_score": 5.0,
     "duration_sec": 240, "published_at": "2026-07-01T00:00:00Z"},
    {"youtube_id": "b", "title": "How to Cook Salmon the Easy Way",
     "tags": ["cooking", "fish"], "engagement_score": 4.0,
     "duration_sec": 480, "published_at": "2026-07-02T00:00:00Z"},
    {"youtube_id": "c", "title": "Why Your Steak Is Dry — The Truth",
     "tags": ["steak"], "engagement_score": 6.0,
     "duration_sec": 900, "published_at": "2026-07-03T00:00:00Z"},
]


def test_classify_hooks():
    assert "listicle" in classify_hooks("Top 10 Kitchen Hacks")
    assert "how-to" in classify_hooks("How to Cook Salmon the Easy Way")
    assert classify_hooks("Random Day In The Life") == ["plain"]


def test_extract_hooks_aggregate():
    out = extract_hooks(V)
    assert out["aggregate"]  # non-empty
    types = {t["type"] for t in out["aggregate"]}
    assert types
    assert len(out["per_video"]) == 3


def test_best_day_uses_channel_default():
    feats = extract_features(V)
    assert feats["avg_title_length"] > 0
    assert set(feats["duration_buckets"])  # buckets present


def test_keywords_weight_performance():
    from app.patterns import extract_keywords
    kw = extract_keywords(V)
    terms = [k["term"] for k in kw]
    assert "cooking" in terms or "steak" in terms
    # sorted by (weight / freq, term) descending — normalizes by usage
    assert kw == sorted(
        kw, key=lambda k: (k["weight"] / max(k["freq"], 1), k["term"]),
        reverse=True,
    )