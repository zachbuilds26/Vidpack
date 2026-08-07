from app.scoring import age_days, engagement_score, percentile_rank


def test_age_days_floor_one():
    assert age_days(None) == 1
    assert age_days("2030-01-01T00:00:00Z") >= 1


def test_engagement_orders_by_views_rate():
    fresh_high = engagement_score(100_000, 5_000, 500, "2026-08-06T00:00:00Z")
    old_low = engagement_score(100_000, 5_000, 500, "2020-01-01T00:00:00Z")
    assert fresh_high > old_low


def test_engagement_likes_and_comments_help():
    a = engagement_score(10_000, 900, 100, "2026-08-01T00:00:00Z")
    b = engagement_score(10_000, 100, 0, "2026-08-01T00:00:00Z")
    assert a > b


def test_percentile_rank():
    assert percentile_rank(10, [1, 5, 10, 20]) == 0.75
    assert percentile_rank(0, []) == 0.0