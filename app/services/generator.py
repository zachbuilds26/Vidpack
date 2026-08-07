"""Package generation service: tries AI, falls back to the rule engine."""

import logging

from ..adapters.ai import AIRateLimited, AIError, AINotConfigured, get_ai
from ..adapters.rules import generate_package as rule_package
from ..patterns import build_research_summary
from ..repositories import Repositories

logger = logging.getLogger("vidpack.generator")

_ENGINE_LABEL = {"GeminiClient": "gemini", "GroqClient": "groq"}


def generate(
    repos: Repositories,
    niche_id: str,
    force_rules: bool = False,
    ai=None,
) -> dict:
    """Build a package for the niche. Returns persisted package dict.

    Priority: AI (unless force_rules) -> deterministic rule engine.
    """
    niche = repos.get_niche(niche_id)
    if niche is None:
        raise ValueError(f"Niche '{niche_id}' not found.")

    videos = repos.list_videos(niche_id)
    if not videos:
        raise ValueError(
            "No research data yet. Run /research on this niche first."
        )
    summary = build_research_summary(niche["name"], videos)

    client = ai or get_ai()
    if not force_rules:
        try:
            pkg = client.generate_package(niche["name"], summary)
            engine = _ENGINE_LABEL.get(type(client).__name__, "ai")
            return repos.save_package(niche_id, engine, pkg)
        except AINotConfigured:
            logger.info("AI not configured; using rule engine.")
        except AIRateLimited:
            logger.warning("AI rate-limited; using rule engine.")
        except AIError as exc:
            logger.warning("AI generation failed: %s", exc)

    pkg = rule_package(summary, niche["name"])
    return repos.save_package(niche_id, "rules", pkg)