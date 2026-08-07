# vidpack

**The channel of tomorrow.** Niche → research → full video package in ~60 seconds.

vidpack analyzes the top videos in a niche via the **official YouTube Data API v3**
(no scraping, within terms of service), extracts the patterns that actually work,
and then writes with you: a **Story studio** where the AI drafts a script for the
niche, and an **upload-ready kit** (title variants with CTR estimates, SEO
description + timestamps, tags) for any finished script. Every run and every kit
lands in a SQLite library that **compounds**: re-run `refresh` later and "proven
hooks" re-rank as stats move.

Built for the [YouTube Automation Hackathon](https://youtube-automate-hackathon.devpost.com/).

**Live demo: <https://vidpack.onrender.com>** — deployed on Render (landing at `/`, app at `/app`).

## Demo

Try it live at **<https://vidpack.onrender.com>**, or run locally:

```
.\run.ps1
open http://127.0.0.1:8000
```

## What it does

1. **Research** — enter a niche (e.g. `cooking for students`, `african tales faceless
   automation`). vidpack pulls recent top videos (up to 30, meta-content filtered out,
   channel-diverse), engagement scores them, extracts hook types, recurring keywords,
   and cohort features (best posting day, duration buckets).
2. **Story studio** — a grounded chat with the AI. Ask for topic ideas, outlines, or a
   full script. The chat knows your niche's proven hooks, keywords and top titles and
   uses them as context; "write a story about…" produces a complete first-line-to-CTA
   script, and the conversation keeps shaping it.
3. **Upload-ready kit** — on any script reply, hit **Upload-ready kit**: vidpack turns
   it into 5 title variants (each with a CTR estimate), a description with timestamps,
   and 12 tags, then saves it to the library.
4. **Library** — proven hooks and saved kits per niche. `refresh` re-polls stats and
   re-ranks "proven hooks" — the compounding story.

**Two engines, one tool**
- `groq` — **Llama-3.3-70B** on Groq's free tier generates context-aware packages and
  stories. Configures up to **3 keys that rotate automatically** when one is
  rate-limited or hits its daily quota — the demo never breaks mid-sweat.
- `rules` — deterministic generator that always works, no keys, and kicks in the
  moment every AI engine is missing, rate-limited, or offline.

## Quickstart

```bash
# 1. create venv + install
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. configure keys (optional for rules mode)
copy .env.example .env   # add YOUTUBE_API_KEY and optionally GROQ_API_KEY

# 3. run
py .venv\Scripts\uvicorn app.main:app   # or you can run `python app\main.py`
```

Open http://127.0.0.1:8000 — the landing page. The app lives at `/app`.

### API keys
- **YouTube Data API v3** (free, 10k units/day, quotas used only on research/refresh):
  Google Cloud Console → enable **YouTube Data API v3** → create an API key →
  `YOUTUBE_API_KEY=`. vidpack respects terms: official API only (no scraping), a daily
  quota budget, and batch fetches (search=100 units; a videos stats batch=1 unit).
- **Groq** (free tier, OpenAI-compatible): console.groq.com/keys → create an API key →
  `GROQ_API_KEY=`. Optional extras `GROQ_API_KEY_2=` / `GROQ_API_KEY_3=` enable
  automatic key rotation. If no Groq key is set at all, vidpack runs in `rules` mode
  at full functionality — deterministic packages, no AI.

## Deploy (Render)

The live site runs on a free Render web service:

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Environment**: `YOUTUBE_API_KEY`, `GROQ_API_KEY`, `GROQ_API_KEY_2`, `GROQ_API_KEY_3`
  (Render's "Add from .env" accepts the same `KEY=VALUE` lines as `.env`)

Note: Render's free tier uses an ephemeral disk — the SQLite library resets on each
redeploy. The local `data/vidpack.db` remains the compounding source of truth.

## Architecture

```
 Browser SPA (static/, no build step)
        │  /api/*
 FastAPI (app/main.py) — thin routes, typed errors
 ┌──────┴────────────────────────────┐
 │ services/  research · generator · │
 │            refresh · kit          │
 └──────┬─────────────────────┬──────┘
        │                     │
 📦 SQLite (app/repositories.py)   🔌 adapters/
   niches · videos · patterns  │  youtube.py — Data API client, quota/retries
   packages · hooks            │  ai.py      — Groq (rotating keys), strict-JSON
                               │  rules.py   — deterministic fallback
```

Design principles: routes never hold business logic; all external I/O behind
adapters; every external error maps to a typed `400/404/429/502`; pure math
(`scoring.py`, `patterns.py`) is 100% unit-tested. UI: a minimal, **light-first**
design system in **Syne** (display) + **Space Grotesk** (body) with a single red
accent and an optional dark theme — landing page at `/`, app at `/app`.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | landing page |
| GET | `/app` | the app (research / story studio / library) |
| GET | `/api/health` | engine + key status |
| POST | `/api/niches` | create niche (`name`, `window_days`) |
| GET | `/api/niches` | list niches |
| GET | `/api/niches/{id}` | detail: patterns + videos + hooks |
| POST | `/api/niches/{id}/research` | run research pass |
| POST | `/api/niches/{id}/generate` | produce a package (`force_rules: true` to skip AI) |
| GET | `/api/niches/{id}/packages` | saved packages |
| POST | `/api/niches/{id}/refresh` | re-pull stats, re-rank hooks |
| GET | `/api/niches/{id}/hooks` | hook library leaderboard |
| POST | `/api/chat` | story-studio chat (`messages`, optional `niche` id) |
| POST | `/api/story/kit` | upload-ready kit from a script (`niche_id`, `script`) |

### Key rotation (Groq)

`GROQ_API_KEY` is used first. On a daily-quota 429, invalid key (401/403), or
failed schema validation, vidpack rolls to `GROQ_API_KEY_2`, then `GROQ_API_KEY_3`.
Per-minute 429s/5xx back off briefly before moving on. All three keys are read
once at process start from `.env`.

## Tests

```bash
.venv\Scripts\python -m pytest tests
```

44 tests — pure math, rule-engine determinism, chat intent + role normalization,
kit validation, slug-collision safety, and a full end-to-end flow
(research → generate → refresh) against a fake YouTube client (no network, no key).

## Roadmap (next tool)

A **script → video renderer**: reads your script, generates storyboard images,
produces image prompts, generates voiceover, stitches images/clips with
transitions/captions/voiceover, and renders an `.mp4`. This competition's
scope is the research + story + package layer; the renderer is the natural
Phase-2 follow-on.

## License

MIT. Independent, community-run project — not affiliated with YouTube/Google.
