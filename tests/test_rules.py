from app.adapters.rules import generate_package, generate_titles


def test_generate_titles_uses_niche_and_hook_bank():
    summary = {"hook_types": [{"type": "listicle", "count": 5, "share": 0.5}],
               "keywords": [], "features": {"best_post_day": "Sun"}}
    titles = generate_titles(summary, "kitchen hacks")
    assert len(titles) == 5
    assert all(t["ctr_estimate"] > 0 for t in titles)
    assert titles[0]["hook_type"] == "listicle"
    assert "kitchen" in titles[0]["title"]


def test_generate_package_is_complete_and_deterministic():
    summary = {"hook_types": [{"type": "how-to", "count": 3, "share": 1.0}],
               "keywords": [{"term": "cooking", "freq": 4, "weight": 5.0}],
               "features": {"best_post_day": "Wed"}}
    p1 = generate_package(summary, "cooking")
    p2 = generate_package(summary, "cooking")
    assert p1 == p2
    assert len(p1["titles"]) == 5
    assert len(p1["tags"]) == 12
    assert "[HOOK" in p1["script"]
    assert len(p1["thumbnails"]) == 3


def test_generate_package_with_empty_summary():
    p = generate_package({}, "my niche")
    assert len(p["titles"]) == 5
    assert p["script"]


def test_titles_are_short_frontloaded_and_odd_numbered():
    summary = {"hook_types": [{"type": "number-led", "count": 4, "share": 0.8}],
               "keywords": [], "features": {}}
    titles = generate_titles(summary, "home gym")
    assert all(len(t["title"]) <= 70 for t in titles)
    # niche keyword should be front-loaded in the top variant
    assert titles[0]["title"].lower().split().index("gym") < 6
    assert titles[0]["hook_type"] == "number-led"
    # odd starting number magic divisor: 7, 9, 11, 5...
    assert any(t["title"].startswith(("7 ", "9 ", "11 ", "5 ")) for t in titles)


def test_tags_are_focused_exact_match_first():
    summary = {"hook_types": [], "keywords": [
        {"term": "budget cooking", "freq": 3, "weight": 4},
        {"term": "cheap", "freq": 2, "weight": 3}], "features": {}}
    tags = generate_package(summary, "budget cooking")["tags"]
    assert len(tags) == 12
    assert tags[0] == "budget cooking"
    assert any("budget cooking" in t for t in tags[:3])