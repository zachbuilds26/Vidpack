"""Deterministic package generator — the always-available fallback, and the
engine that powers the tool when no API keys are configured.

Built around the 2026 best-practice research baked into this codebase:
front-loaded keywords, odd-number & power-verb title levers, retention-first
script pacing (hook, re-hook, one CTA), high-contrast single-focal thumbnails,
a keyword-first description with timestamps, and a focused exact-match-first
tag sequence.
"""

import re

# Title template banks per hook style. {t} is the niche topic, {n} an odd
# number. Every template is deterministic; the bank is cycled so the five
# variants read differently instead of repeating one formula.
TITLE_BANKS: dict[str, list[str]] = {
    "listicle": [
        "Top {n} {t} Nobody Else Is Talking About",
        "{n} {t} That Actually Work, Backed by Data",
        "The Only {n} {t} You'll Ever Need",
    ],
    "number-led": [
        "{n} {t} That Change Everything",
        "{n} {t} Mistakes That Are Costing You",
        "{n} {t} Under $50 That Deliver",
    ],
    "how-to": [
        "How to {t} the Right Way (Step by Step)",
        "{t}: The 3-Step System That Works",
        "How to {t} Without Wasting Hours",
    ],
    "question": [
        "Why Your {t} Is Wrong (And How to Fix It)",
        "Can You {t}? The Honest Answer",
        "What's Actually Working With {t}?",
    ],
    "comparison": [
        "{t} vs Everything Else: The Real Winner",
        "{t}: Two Proven Paths, One Clear Winner",
    ],
    "urgency": [
        "Do This Before Your Next {t}",
        "Don't Start {t} Until You See This",
    ],
    "benefit": [
        "The Fastest Way to Win With {t}",
        "How to Double Your {t} Results",
        "One Skill That Makes {t} Easier",
    ],
    "curiosity": [
        "What Nobody Tells You About {t}",
        "The {t} Secret Nobody Shares",
        "I Tried {t} for 30 Days — Here's What Happened",
    ],
    "plain": [
        "The Complete {t} Guide",
        "{t}, Explained Simply",
    ],
}

# Odd numbers far out-lift even ones in CTR studies (7/9/11 feel specific).
_ODDS = [7, 9, 11, 5, 3]

CTR_BASE = 4.2
CTR_LIFT = {
    "listicle": 1.6, "number-led": 1.6, "how-to": 1.1, "question": 1.2,
    "comparison": 1.4, "urgency": 1.05, "benefit": 1.3, "curiosity": 1.7,
    "plain": 0.8,
}
MAX_TITLE_LEN = 70

# High-contrast pairs (WCAG AA or close): light text on deep bg, or dark on
# bright — never two mid tones. One focal point and one cue per concept.
THUMB_META = [
    {
        "concept": "Number-led bold",
        "palette": {"bg": "#101828", "text": "#FFD166"},
        "layout": "Big odd number + 2-3 word headline, single accent bar",
        "cue": "giant number, no faces needed",
    },
    {
        "concept": "Curiosity gap",
        "palette": {"bg": "#F43F5E", "text": "#FFFFFF"},
        "layout": "Emotive face up top, 3-word hook under it, one red arrow",
        "cue": "arrow pointing at the headline",
    },
    {
        "concept": "Result focused",
        "palette": {"bg": "#0EA5E9", "text": "#FDF7E3"},
        "layout": "Before/after split, 4-word result, one checkmark cue",
        "cue": "checkmark on the 'after' side",
    },
]


def _title_from_bank(kind: str, topic: str, n: int, variant: int) -> str:
    bank = TITLE_BANKS.get(kind, TITLE_BANKS["plain"])
    t = bank[variant % len(bank)].format(t=topic, n=n)
    return t[:MAX_TITLE_LEN].strip()


def _hook_order(summary: dict) -> list[str]:
    """Order hook types by observed share in the niche, plus defaults."""
    observed = [
        h["type"] for h in summary.get("hook_types", [])
        if h.get("type") in TITLE_BANKS
    ]
    default = ["listicle", "curiosity", "how-to", "question", "benefit"]
    return observed[:5] + [d for d in default if d not in observed][:5]


def generate_titles(summary: dict, niche: str) -> list[dict]:
    topic = niche.strip() or "this"
    titles = []
    for i, kind in enumerate(_hook_order(summary)[:5]):
        share = next(
            (h.get("share", 0) for h in summary.get("hook_types", [])
             if h.get("type") == kind),
            0,
        )
        titles.append({
            "title": _title_from_bank(kind, topic, _ODDS[i], i),
            "ctr_estimate": round(CTR_BASE * CTR_LIFT.get(kind, 1.0), 1),
            "hook_type": kind,
            "rationale": (
                f"'{kind}' appears in ~{round(share * 100)}% of the top "
                f"videos we analysed — the winning pattern here — so the "
                f"title leans on it. Estimate is a ranking aid, not a promise."
            ),
        })
    return titles


def generate_tags(summary: dict, niche: str) -> list[str]:
    keywords = [k["term"] for k in summary.get("keywords", [])]
    phrases = [k["term"] for k in summary.get("keywords", []) if " " in k]
    niche_words = [w for w in re.split(r"\W+", niche.lower()) if w]
    tags: list[str] = []
    # Exact-match niche first, then multi-word phrases, then single terms.
    primary = niche.lower().strip()
    if primary and len(primary) > 2:
        tags.append(primary)
    for t in niche_words + phrases:
        if t not in tags and len(t) > 2:
            tags.append(t)
    for t in keywords:
        if t not in tags and len(t) > 2:
            tags.append(t)
    # Long-tail combos keep tags focused when research is thin.
    first = niche_words[0] if niche_words else niche.lower().strip()
    combos = [f"{first} tips", f"{first} tutorial", f"best {first}",
              f"top {first}", f"{first} ideas", f"{first} guide",
              f"{first} for beginners", f"{first} mistakes", f"{first} 2026",
              f"{first} tools", f"{first} workflow", f"{first} examples"]
    for c in combos:
        if len(tags) >= 12:
            break
        if c not in tags:
            tags.append(c)
    return tags[:12]


def generate_description(summary: dict, niche: str, titles: list[dict]) -> str:
    best = titles[0]["title"] if titles else (niche or "this video")
    kw = ", ".join(k["term"] for k in summary.get("keywords", [])[:6]) or niche
    day = summary.get("features", {}).get("best_post_day") or "any day"

    # Keyword + promise in the first two lines (above "Show more").
    first_tag = (niche.split()[0] if niche.split() else "youtube").lower()
    second_tag = kw.split(",")[0].strip().lower() if kw.split(",") else "youtube"
    return "\n".join([
        f"{best} — the exact {kw} behind the top videos in the {niche} niche, "
        f"in the order that drives results.",
        "",
        f"In this video: {kw}.",
        f"Posting on {day} performs best for this niche — worth scheduling "
        f"around it.",
        "",
        "TIMESTAMPS",
        "0:00 The hook — why the top creators win here",
        "0:45 The pattern behind every winner",
        "1:30 The workflow, step by step",
        "3:00 Re-hooks that hold retention",
        "4:00 Your next action in 5 minutes",
        "",
        f"#{first_tag} #{second_tag} #creator",
    ])


def _sanitize_title(t: str) -> str:
    """Trim a title down so script speech isn't a wall of dashes."""
    return re.sub(r"[:—-]", "", t).strip()


def generate_script(summary: dict, niche: str, titles: list[dict]) -> str:
    best = _sanitize_title(titles[0]["title"]) if titles else "this video"
    kind = titles[0].get("hook_type", "how-to") if titles else "how-to"
    kw = ", ".join(k["term"] for k in summary.get("keywords", [])[:6])
    return (
        f"[HOOK · 0:00-0:12]\n"
        f"{best}. Details aren't the point — the pattern is. "
        f"Once you see it, you can't unsee it.\n\n"
        f"[OPENLOOP · 0:12-0:40]\n"
        f"Across the {niche} niche, the winners lean on the '{kind}' hook. "
        f"Here's the exact structure — and why it beats everything else in "
        f"the data.\n\n"
        f"[PAYOFF · 0:40-1:20]\n"
        f"Start the value: one concrete, surprising finding from the "
        f"research ({kw}). Land the first payoff 30 seconds after the hook — "
        f"that's where most videos lose people.\n\n"
        f"[REHOOK · 1:20-2:00]\n"
        f"Now make them stay. Open the second loop: 'Here's the mistake "
        f"everyone makes next.' Then answer it with the second payoff — "
        f"tight and specific.\n\n"
        f"[CLOSE LOOP · 2:00-2:30]\n"
        f"Close both loops in one sentence: the pattern exists, it shows up "
        f"in the top videos, and it's yours to reuse.\n\n"
        f"[CTA · 2:30-2:45]\n"
        f"One action only: type '{kind}' in the comments and I'll send the "
        f"exact template. Go build."
    )


def thumbnail_concepts(titles: list[dict], niche: str) -> list[dict]:
    concepts = []
    for i, t in enumerate(titles[:3]):
        meta = THUMB_META[i % len(THUMB_META)]
        # ≤4 significant words, keyword-carrying headline.
        words = [
            w for w in re.findall(r"[\w']+", t["title"])
            if w.lower() not in {"the", "to", "and", "with", "your", "how",
                                 "that", "of", "for", "a", "an", "is", "you",
                                 "why", "what", "can"}
        ]
        headline = " ".join(words[:4]).title() or niche.title()
        pal = meta["palette"]
        concepts.append({
            "concept": meta["concept"],
            "headline": headline[:24],
            "palette": {"bg": pal["bg"], "text": pal["text"]},
            "layout": meta["layout"],
            "hook": f"{meta['cue']} · {t['title'][:60]}",
        })
    return concepts


def generate_package(summary: dict, niche: str) -> dict:
    """Full deterministic package. Used when AI is unavailable."""
    titles = generate_titles(summary, niche)
    return {
        "titles": titles,
        "tags": generate_tags(summary, niche),
        "summary": generate_description(summary, niche, titles),
        "script": generate_script(summary, niche, titles),
        "thumbnails": thumbnail_concepts(titles, niche),
    }