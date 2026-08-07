"""Tests for the upload-ready kit: prompt building, validation, rules fallback."""

import json

import pytest

from app.adapters.ai import _build_kit_prompt, _validate_kit
from app.services.kit import _minimal_summary

SCRIPT = (
    "A story about a baker who rescues his town from a flood by reopening the "
    "old mill. Full script with hook, scenes, dialogue and a payoff."
)


class TestBuildKitPrompt:
    def test_mentions_script_and_niche(self):
        prompt = _build_kit_prompt(SCRIPT, "cartoon")
        assert SCRIPT[:60] in prompt
        assert "cartoon" in prompt
        assert "TITLES" in prompt and "TAGS" in prompt and "description" in prompt

    def test_truncates_huge_scripts(self):
        huge = "x" * 10000
        prompt = _build_kit_prompt(huge, "sports")
        assert len(prompt) < 9000


class TestValidateKit:
    def test_accepts_good_kit(self):
        kit = _validate_kit({
            "titles": [
                {"title": "The Old Mill Comes Back to Life", "ctr_estimate": 5.2,
                 "hook_type": "story"}
            ] * 5,
            "tags": ["cartoon story", "flood rescue", "village"],
            "description": "Line one.\n\nTIMESTAMPS\n0:00 Hook\n#cartoon #story #rescue",
        })
        assert kit is not None
        assert len(kit["titles"]) == 5
        assert kit["tags"][:3] == ["cartoon story", "flood rescue", "village"]
        assert "TIMESTAMPS" in kit["description"]

    def test_rejects_missing_titles(self):
        assert _validate_kit({"tags": [], "description": "x"}) is None

    def test_rejects_missing_description(self):
        assert _validate_kit({"titles": [{"title": "T"}], "tags": []}) is None

    def test_tolerates_malformed_tags(self):
        kit = _validate_kit({
            "titles": [{"title": "T"}],
            "tags": "not-a-list",
            "description": "desc",
        })
        assert kit is not None
        assert kit["tags"] == []


class TestRulesFallback:
    def test_minimal_summary_is_safe_for_rules(self):
        summary = _minimal_summary("cartoon")
        assert summary["keywords"] == []
        assert summary["niche"] == "cartoon"
