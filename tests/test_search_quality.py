"""Search-quality behaviour: query cleaning, meta filtering, channel diversity."""

from app.adapters.youtube import clean_niche_query, _is_meta, _dedupe_channels


def test_clean_niche_query_strips_meta_words():
    assert clean_niche_query("cartoon niche") == "cartoon"
    assert clean_niche_query("Cartoon Niche") == "cartoon"
    assert clean_niche_query("best passive income ideas") == "passive income"
    # keeps a real multi-word niche that isn't filled with noise words
    assert clean_niche_query("home gym workouts") == "home gym workouts"
    assert clean_niche_query("budget cooking") == "budget cooking"


def test_meta_title_blocked():
    v = {"title": "How to Make Money with a Cartoon Channel", "channel_title": "Some Channel"}
    assert _is_meta(v) is True


def test_real_content_passes():
    v = {"title": "How to Draw a Cute Cat — Cartoons for Kids", "channel_title": "Art Corner"}
    assert _is_meta(v) is False


def test_meta_channel_blocked():
    v = {"title": "Episode 12", "channel_title": "NicheChannelGrowthTips"}
    assert _is_meta(v) is True


def test_dedupe_caps_per_channel():
    items = [{"channel_title": "A", "youtube_id": i} for i in range(10)]
    out = _dedupe_channels(items, limit=20)
    assert len(out) == 3  # capped at 3 per channel

    mixed = [{"channel_title": "A", "youtube_id": i} for i in range(6)]
    mixed += [{"channel_title": "B", "youtube_id": i} for i in range(6)]
    out2 = _dedupe_channels(mixed, limit=20)
    assert len(out2) == 6  # 3 + 3