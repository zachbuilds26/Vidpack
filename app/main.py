"""vidpack — FastAPI application. Routes are thin; logic lives in services."""

import logging
import os
import random
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .adapters.ai import AINotConfigured, AIError, AIRateLimited, get_ai
from .adapters.youtube import (
    QuotaExceeded, RateLimited, YouTubeConfigError, YouTubeError,
)
from .config import get_settings
from .db import DB
from .repositories import get_repos
from .services.generator import generate as generate_package
from .services.kit import generate_kit
from .services.refresh import refresh as refresh_niche
from .services.research import run_research

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vidpack")

settings = get_settings()
db = DB(settings.db_path)
db.init_schema()
repos = get_repos(db)


class NicheIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    window_days: int = Field(default=90, ge=1, le=365)


class GenerateIn(BaseModel):
    force_rules: bool = False


class ChatIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    niche: str | None = None


class KitIn(BaseModel):
    niche_id: str = Field(min_length=1, max_length=100)
    script: str = Field(min_length=20, max_length=20000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_schema()
    logger.info("vidpack ready. AI engine: %s", "groq" if settings.has_groq_key else "rules")
    if not settings.has_youtube_key:
        logger.warning("YOUTUBE_API_KEY missing — research will fail until it is set.")
    yield


app = FastAPI(title="vidpack", version="0.1.0", lifespan=lifespan)

STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, YouTubeConfigError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, QuotaExceeded):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, RateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, YouTubeError):
        return HTTPException(status_code=502, detail=str(exc))
    logger.exception("unhandled error")
    return HTTPException(status_code=500, detail="Internal error.")


# ---- pages ----------------------------------------------------------------

@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(str(STATIC / "landing.html"))


@app.get("/app", include_in_schema=False)
def index():
    return FileResponse(str(STATIC / "index.html"))


# ---- api ------------------------------------------------------------------

@app.get("/api/health")
def health():
    ai = "groq" if settings.has_groq_key else "rules"
    return {
        "ok": True,
        "youtube_key": settings.has_youtube_key,
        "ai": ai,
        "ai_model": settings.groq_model if ai == "groq" else "",
        "db": settings.db_path,
    }


@app.post("/api/niches")
def create_niche(body: NicheIn):
    niche = repos.create_niche(body.name, body.window_days)
    return {"niche": niche}


@app.get("/api/niches")
def list_niches():
    return {"niches": repos.list_niches()}


@app.get("/api/niches/{niche_id}")
def get_niche(niche_id: str):
    niche = repos.get_niche(niche_id)
    if niche is None:
        raise HTTPException(404, f"Niche '{niche_id}' not found.")
    return {
        "niche": niche,
        "patterns": repos.list_patterns(niche_id),
        "videos": repos.list_videos(niche_id),
        "hooks": repos.list_hooks(niche_id),
    }


@app.post("/api/niches/{niche_id}/research")
def research(niche_id: str):
    try:
        return run_research(repos, niche_id)
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/niches/{niche_id}/generate")
def generate(niche_id: str, body: GenerateIn | None = None):
    try:
        return {"package": generate_package(repos, niche_id, force_rules=(body.force_rules if body else False))}
    except Exception as exc:
        raise _http_error(exc)


_STORY_SYSTEM = (
    "You are the creative writing partner for a YouTube channel. Read what "
    "the user actually asks and answer THAT — never default to writing a "
    "story.\n"
    "- If they ask for topic ideas, titles, hooks, outlines, planning or "
    "advice: give a concise, specific, useful answer (a short list is "
    "perfect). Match your answer's length to the ask.\n"
    "- Only when they explicitly ask for a story or script: write the "
    "complete script from first line to last — an open hook, scene-by-scene "
    "beats, dialogue and narration, a payoff, and a single call to action. "
    "Write for the ear — short sentences, contractions, second person. "
    "No meta commentary, no 'here is a script'. Just the script.\n"
    "If the question is short, keep the answer short."
)

_IDEA_RE = re.compile(
    r"\b(topic|topics|idea|ideas|suggest|suggestion|outline|brainstorm|"
    r"list|what should|give me|recommend|any good|any better|help me)\b",
    re.IGNORECASE,
)
_STORY_NOUN_RE = re.compile(r"\b(story|script|tale)\b", re.IGNORECASE)
# "story ideas" / "ideas for a story" ask for ideas, not a story. These must be
# checked before the bare story-noun rule, which would otherwise win.
_STORY_IDEA_RE = re.compile(
    r"\b(?:stor(?:y|ies)|scripts?|tales?)\s+(ideas?|topics?|prompts?)|"
    r"\bideas?\s+(?:for|about|on)\s+(?:a\s+|the\s+)?(?:stor(?:y|ies)|scripts?|tales?)\b",
    re.IGNORECASE,
)


def _wants_story(text: str) -> bool:
    """Decide whether a user message is asking for a story (vs. ideas/advice).
    An explicit story noun always wins — except "story ideas"/"ideas for a
    story" phrasing, which is an idea request; everything else defaults to
    story mode."""
    if _STORY_IDEA_RE.search(text):
        return False
    if _STORY_NOUN_RE.search(text):
        return True
    if _IDEA_RE.search(text):
        return False
    return True

# rotate these angle choices per request so the same user prompt yields a
# genuinely different story each time instead of the same script repeating
_ANGLES = [
    "Tell the story from a different narrator's perspective than the obvious one.",
    "Open in the middle of the action, then flash back to the setup.",
    "Give the story a quiet, tense mood with very little dialogue.",
    "Make the story comedic and fast-paced with one twist near the end.",
    "Tell it in reverse: reveal the ending first, then show how it happened.",
    "Add a rival or obstacle that appears just before the payoff.",
    "Use a ticking clock — the character has one day to pull it off.",
    "Make the protagonist flawed: their own mistake creates the climax.",
]
_STRUCTURES = [
    "Use three scenes of rising stakes and a 40-second payoff.",
    "Use a cold open hook, two scenes, and a closing loop at the end.",
    "Use four short beats that each escalate the tension.",
    "Use one setup scene, two turning points, and a resolution.",
]
_VOICES = [
    "second person, as if speaking directly to the viewer",
    "first person from the main character",
    "an unseen narrator with a dry, warm tone",
    "present tense, urgent and cinematic",
]


_COMMON_BIGRAMS = {
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es",
    "or", "te", "of", "ed", "is", "it", "al", "ar", "st", "to", "nt", "ng",
    "se", "ha", "as", "ou", "io", "le", "ve", "co", "me", "de", "hi", "ri",
    "ro", "ic", "ne", "im", "ly", "ra", "la", "di", "si", "el", "ea", "ns",
    "ll", "ec", "ie", "us", "un", "ch", "wh", "ck", "gh", "ph", "sh", "br",
    "gr", "pl", "fl", "dr", "tr", "pr", "sp", "sk", "sm", "sn", "bl", "cr",
    "fr", "gl", "sl", "sw", "cl", "ft", "mp", "nd", "lt", "nt", "pt", "rd",
    "rg", "rk", "rl", "rm", "rn", "rp", "rr", "rt", "rv", "ry",
}


def _gibberish(text: str) -> bool:
    """Reject spam/garbage prompts so the AI is not forced to make a story
    out of keyboard mashing or empty filler."""
    t = text.strip()
    if len(t) < 3:
        return True
    letters = re.sub(r"[^a-zA-Z\s]", "", t)
    words = [w for w in letters.split() if w]
    if not words:
        return True
    # repeated single-character spam ("aaaaaa", "!!!")
    if re.fullmatch(r"(\w)\1{2,}|\W+", t):
        return True
    # home-row / keyboard mashes that accidentally contain common bigrams
    if re.search(
        r"(asdf|qwer|wert|sdfg|zxcv|xcvb|hjkl|fghj|tyui|vbn|jkl|xyz)", t.lower()
    ):
        return True
    # a lone 5+ letter word with <2 distinct vowels and no common English
    # bigram is mashed keys (e.g. "fgfur") — real words almost always carry
    # either two vowels or a common bigram ("clock" has "cl"+"ck").
    for w in words:
        if len(w) >= 5:
            vowels = set(re.findall(r"[aeiouy]", w))
            bigrams = {w[i:i + 2] for i in range(len(w) - 1)}
            if len(vowels) < 2 and not (bigrams & _COMMON_BIGRAMS):
                return True
    return False


def _research_context(niche_id: str | None) -> str | None:
    """Ground the story writer in the niche's proven research (if any): the
    hook styles, keywords and top titles seen in the niche's top videos."""
    if not niche_id or repos.get_niche(niche_id) is None:
        return None
    hooks = repos.list_hooks(niche_id, limit=8)
    patterns = repos.list_patterns(niche_id)
    keywords = [p["value"] for p in patterns if p["kind"] == "keyword"][:10]
    videos = repos.list_videos(niche_id, limit=5)
    lines = ["Here is the proven research for this exact niche (from the top "
             "performing videos we analysed with the YouTube API). Use it to "
             "ground your answer — match the style that already works in this "
             "niche, never copy:"]
    if hooks:
        lines.append("Winning hook styles: " + ", ".join(
            f"{h['hook_text']}" for h in hooks[:8]))
    if keywords:
        lines.append("Keywords viewers search: " + ", ".join(keywords))
    if videos:
        lines.append("Top titles in the niche: " + "; ".join(
            v["title"] for v in videos[:5]))
    if len(lines) == 1:
        return None
    return "\n".join(lines)


@app.post("/api/chat")
def chat(body: ChatIn):
    try:
        client = get_ai()
        msgs = [{"role": "system", "content": _STORY_SYSTEM}]
        last_user = next(
            (str(m.get("content", "")) for m in reversed(body.messages) if m.get("role") == "user"),
            "",
        )
        if not last_user.strip():
            raise HTTPException(400, "Type a story idea first.")
        if _gibberish(last_user):
            raise HTTPException(
                400,
                "That looks like random characters. Describe a story idea in a sentence or two.",
            )
        # `body.niche` is a niche *id* from the UI; the AI needs the real name.
        niche_name = None
        if body.niche and len(body.niche) <= 100:
            niche = repos.get_niche(body.niche)
            if niche is not None:
                niche_name = niche["name"]
        if niche_name:
            msgs.append(
                {"role": "system", "content": f"Context: the viewer's niche is '{niche_name}'."}
            )
        context = _research_context(body.niche if niche_name else None)
        if context:
            msgs.append({"role": "system", "content": context})
        if _wants_story(last_user):
            msgs.append({
                "role": "system",
                "content": (
                    f"This request is for a story. Creative direction for THIS "
                    f"response only — pick from these three and follow them, "
                    f"and do not repeat stories you have already told:\n"
                    f"- angle: {random.choice(_ANGLES)}\n"
                    f"- structure: {random.choice(_STRUCTURES)}\n"
                    f"- voice: {random.choice(_VOICES)}"
                ),
            })
        msgs.extend(
            {"role": "assistant" if str(m.get("role")) == "ai" else str(m.get("role", "user")),
             "content": str(m.get("content", ""))}
            for m in body.messages[-20:]
        )
        return {"reply": client.chat(msgs)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/story/kit")
def story_kit(body: KitIn):
    """Turn a finished script into an upload-ready package (titles, description,
    tags) and save it to the library."""
    if repos.get_niche(body.niche_id) is None:
        raise HTTPException(404, f"Niche '{body.niche_id}' not found.")
    try:
        return {"package": generate_kit(repos, body.niche_id, body.script)}
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/niches/{niche_id}/packages")
def packages(niche_id: str):
    return {"packages": repos.list_packages(niche_id)}


@app.post("/api/niches/{niche_id}/refresh")
def refresh(niche_id: str):
    try:
        return refresh_niche(repos, niche_id)
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/niches/{niche_id}/hooks")
def hooks(niche_id: str, limit: int = Query(50, ge=1, le=200)):
    return {"hooks": repos.list_hooks(niche_id, limit)}


if __name__ == "__main__":
    import uvicorn

    db.init_schema()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)