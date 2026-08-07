"""End-to-end flow: research -> patterns -> generate -> refresh.

Exercised against the FastAPI TestClient with a fake YouTube client and a
rules-only AI resolver, so tests run without network or API keys.
"""

import pytest
from fastapi.testclient import TestClient

from app.adapters.ai import AINotConfigured
from app.adapters.youtube import YouTubeClient
from app.main import app


class FakeYouTube(YouTubeClient):
    def __init__(self, *a, **k):
        pass

    def search_top(self, niche, max_results=30, window_days=90):
        return [
            {
                "youtube_id": f"vid{i}",
                "title": f"Top {i} {niche} Tips You Must See",
                "channel_title": "Fake Channel",
                "published_at": "2026-07-01T00:00:00Z",
                "thumbnail_url": "https://img.example/thumb.jpg",
                "description_txt": "a demo description",
            }
            for i in range(1, 6)
        ]

    def fetch_details(self, refs):
        for idx, r in enumerate(refs):
            r["views"] = 100_000 + idx * 1000
            r["likes"] = 5000
            r["comments"] = 60
            r["duration_sec"] = 420
        return refs


class FakeAI:
    def generate_package(self, niche, summary):
        raise AINotConfigured("no key in tests")


class CapturingChatAI:
    """Records the exact message list the chat endpoint builds, replies
    with the role sequence it received (so tests can assert the fix)."""

    def __init__(self):
        self.last_messages = []

    def chat(self, messages):
        self.last_messages = list(messages)
        roles = [m["role"] for m in messages]
        return f"roles: {','.join(roles)}"

    def generate_package(self, niche, summary):
        raise AINotConfigured("no key in tests")


def _patch(monkeypatch):
    monkeypatch.setattr("app.adapters.youtube.get_client", lambda: FakeYouTube())
    monkeypatch.setattr("app.services.research.get_client", lambda: FakeYouTube())
    monkeypatch.setattr("app.services.refresh.get_client", lambda: FakeYouTube())
    monkeypatch.setattr("app.services.generator.get_ai", lambda: FakeAI())
    return TestClient(app)


def test_full_flow(monkeypatch):
    c = _patch(monkeypatch)

    r = c.post("/api/niches", json={"name": "kitchen hacks", "window_days": 90})
    assert r.status_code == 200, r.text
    niche_id = r.json()["niche"]["id"]

    r = c.post(f"/api/niches/{niche_id}/research")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["video_count"] == 5
    assert body["summary"]["hook_types"]
    assert body["videos"][0]["engagement_score"] > 0

    r = c.post(f"/api/niches/{niche_id}/generate")
    assert r.status_code == 200, r.text
    pkg = r.json()["package"]
    assert pkg["ai_source"] == "rules"
    assert len(pkg["titles"]) == 5
    assert pkg["script"]
    assert len(pkg["tags"]) == 12
    assert len(pkg["thumbnails"]) == 3

    r = c.get(f"/api/niches/{niche_id}/packages")
    assert r.status_code == 200
    assert len(r.json()["packages"]) == 1

    r = c.get(f"/api/niches/{niche_id}/hooks")
    assert r.status_code == 200
    assert len(r.json()["hooks"]) == 5

    r = c.post(f"/api/niches/{niche_id}/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["refreshed"] == 5


def test_generate_requires_research(monkeypatch):
    c = _patch(monkeypatch)
    r = c.post("/api/niches", json={"name": "fresh niche"})
    assert r.status_code == 200
    nid = r.json()["niche"]["id"]
    r = c.post(f"/api/niches/{nid}/generate")
    assert r.status_code == 400


def test_bad_niche_404(monkeypatch):
    c = _patch(monkeypatch)
    r = c.get("/api/niches/nope")
    assert r.status_code == 404


def test_slug_collision_does_not_overwrite(monkeypatch):
    c = _patch(monkeypatch)
    r1 = c.post("/api/niches", json={"name": "African Tales"})
    r2 = c.post("/api/niches", json={"name": "african tales"})
    assert r1.status_code == 200 and r2.status_code == 200
    n1 = r1.json()["niche"]
    n2 = r2.json()["niche"]
    assert n1["id"] != n2["id"]
    assert n1["name"] == "African Tales"
    assert n2["name"] == "african tales"
    names = {n["name"] for n in c.get("/api/niches").json()["niches"]}
    assert {"African Tales", "african tales"} <= names


def test_rerun_updates_window_days(monkeypatch):
    c = _patch(monkeypatch)
    r1 = c.post("/api/niches", json={"name": "window test", "window_days": 30})
    nid = r1.json()["niche"]["id"]
    c.post("/api/niches", json={"name": "window test", "window_days": 180})
    niche = c.get(f"/api/niches/{nid}").json()["niche"]
    assert niche["window_days"] == 180


def test_kit_requires_existing_niche(monkeypatch):
    c = _patch(monkeypatch)
    r = c.post("/api/story/kit", json={
        "niche_id": "does-not-exist",
        "script": "A full story script with a hook, scenes and a payoff.",
    })
    assert r.status_code == 404


def test_kit_flow_saves_to_library(monkeypatch):
    c = _patch(monkeypatch)
    r1 = c.post("/api/niches", json={"name": "story niche"})
    nid = r1.json()["niche"]["id"]
    r = c.post("/api/story/kit", json={
        "niche_id": nid,
        "script": "A full story script with a hook, scenes and a payoff.",
    })
    assert r.status_code == 200, r.text
    pkg = r.json()["package"]
    assert pkg["niche_id"] == nid
    assert pkg["titles"]
    assert pkg["script"]
    assert len(c.get(f"/api/niches/{nid}/packages").json()["packages"]) == 1


def test_chat_normalizes_roles_for_multiturn(monkeypatch):
    ai = CapturingChatAI()
    monkeypatch.setattr("app.main.get_ai", lambda: ai)
    c = _patch(monkeypatch)
    r = c.post("/api/chat", json={
        "messages": [
            {"role": "user", "content": "give me a topic idea"},
            {"role": "ai", "content": "A story about a flood"},
            {"role": "user", "content": "now write a story about it"},
        ],
    })
    assert r.status_code == 200, r.text
    # system (_STORY_SYSTEM) + system (creative direction) + user/assistant/user
    assert r.json()["reply"] == "roles: system,system,user,assistant,user"
    # provider-facing roles: no bare "ai" anywhere
    assert all(m["role"] in ("system", "user", "assistant") for m in ai.last_messages)


def test_chat_sends_niche_name_not_slug(monkeypatch):
    ai = CapturingChatAI()
    monkeypatch.setattr("app.main.get_ai", lambda: ai)
    c = _patch(monkeypatch)
    c.post("/api/niches", json={"name": "African Tales"})
    r = c.post("/api/chat", json={
        "messages": [{"role": "user", "content": "give me a topic idea"}],
        "niche": "african-tales",
    })
    assert r.status_code == 200, r.text
    joined = "\n".join(m["content"] for m in ai.last_messages)
    assert "the viewer's niche is 'African Tales'" in joined
    assert "african-tales" not in joined