"""Intent detection: the chat must answer what the user asks, not always write
a story (e.g. "give me a topic idea" must NOT trigger story mode)."""

from app.main import _wants_story


def test_idea_questions_are_not_stories():
    assert not _wants_story("give me a topic idea")
    assert not _wants_story("give me some topic ideas for this niche")
    assert not _wants_story("suggest 5 topics for videos")
    assert not _wants_story("what should I make a video about")
    assert not _wants_story("recommend some ideas")
    assert not _wants_story("help me brainstorm topics")
    assert not _wants_story("any good title ideas?")


def test_story_requests_are_stories():
    assert _wants_story("write a story about a dog")
    assert _wants_story("write a script for a 3 minute video")
    assert _wants_story("tell me a story about the old mill")
    assert _wants_story("make a story about a baker")
    assert _wants_story("create a creepy story")


def test_story_word_plus_idea_word_is_still_story():
    # "story" appearing with "idea" — the explicit story ask wins
    assert _wants_story("write a story about my idea for a flood")


def test_story_ideas_are_ideas_not_stories():
    # "story ideas" / "ideas for a story" ask for ideas, not a full script
    assert not _wants_story("give me story ideas")
    assert not _wants_story("some story ideas for this niche")
    assert not _wants_story("ideas for a story about a dog")
    assert not _wants_story("suggest script ideas for kids")
    assert not _wants_story("what are good story topics")
    assert not _wants_story("tale ideas for bedtime")
