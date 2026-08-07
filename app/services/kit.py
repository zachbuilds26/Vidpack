"""Upload-ready kit generation: titles/description/tags for a finished script.
Tries AI, falls back to the rule engine (research-based where available)."""

import logging

from ..adapters.ai import AIRateLimited, AIError, AINotConfigured, get_ai
from ..adapters.rules import (
    generate_description as rule_description,
    generate_tags as rule_tags,
    generate_titles as rule_titles,
)
from ..patterns import build_research_summary
from ..repositories import Repositories

logger = logging.getLogger("vidpack.kit")

_ENGINE_LABEL = {"GroqClient": "groq"}


def _minimal_summary(niche: str) -> dict:
    return {
        "niche": niche,
        "keywords": [],
        "hook_types": [],
        "features": {},
    }


def generate_kit(repos: Repositories, niche_id: str, script: str) -> dict:
    """Turn a finished script into an upload-ready package (titles/tags/description).
    Persists it as a package so it lands in the library. Returns the package dict."""
    niche = repos.get_niche(niche_id)
    niche_name = niche["name"]

    videos = repos.list_videos(niche_id)
    summary = build_research_summary(niche_name, videos) if videos else _minimal_summary(niche_name)

    client = get_ai()
    try:
        kit = client.generate_kit(script, niche_name)
        engine = _ENGINE_LABEL.get(type(client).__name__, "ai")
    except AINotConfigured:
        logger.info("AI not configured; kit from rule engine.")
        kit = None
        engine = "rules"
    except AIRateLimited:
        logger.warning("AI rate-limited; kit from rule engine.")
        kit = None
        engine = "rules"
    except AIError as exc:
        logger.warning("AI kit failed: %s", exc)
        kit = None
        engine = "rules"

    if kit is None:
        titles = rule_titles(summary, niche_name)
        kit = {
            "titles": titles,
            "tags": rule_tags(summary, niche_name),
            "description": rule_description(summary, niche_name, titles),
        }

    package = {
        "titles": kit["titles"],
        "tags": kit["tags"],
        "summary": kit["description"],
        "script": script,
        "thumbnails": [],
    }
    return repos.save_package(niche_id, engine, package)
