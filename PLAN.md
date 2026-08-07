# vidpack — Build Plan

> **YouTube Automation Hackathon** · "Code the Channel of Tomorrow"
> Deadline: **Aug 9, 2026 @ 5:00pm PDT**
> Goal: research → full video package in ~60 seconds, with a compounding hook/idea library.

---

## 1. The product in one sentence

Enter a niche → the tool analyzes the top videos in that niche via the **official YouTube Data API v3** (never scraping), extracts the patterns that actually work, and generates a complete video package — **5 title variants with CTR estimates, SEO description + keywords, tags, a full script, and thumbnail concepts** — then stores everything in a database that credentials with every run.

## 2. The moat (why this wins a judge over)

- **Compounding data, not a one-shot generator.** Every research run stores titles, hooks, engagement metrics. A `refresh` job re-polls stats later and re-ranks "proven hooks." Month 3 = 150+ proven hooks and 100+ idea prompts, each with a track record. This is a real differentiator and architected from day one.
- **Respects platform rules**: official Data API only. Spreads quota usage (search costs 100 units, per-video stats = 1 unit; we use a quota budget + cache).
- **Graceful degradation**: if AI is unavailable (no Groq key yet, rate-limited), a rule-based engine still generates a valid package. The demo never breaks.

## 3. Team & stack

| Concern | Choice | Why |
|---|---|---|
| Backend | **Python 3.11 + FastAPI** | Fast to build, great data/AI ecosystem, async-native |
| Storage | **SQLite (WAL mode)** | the compounding DB, zero setup, ships with the tool |
| Rules-legal data | **YouTube Data API v3** (`search.list`, `videos.list`) | official, quota-aware |
| AI generation | **Groq free tier** (Llama-3.3-70B, up to 3 rotating keys) | free, no subscription, any niche; rule-based fallback otherwise |
| Frontend | **Single-page site, vanilla JS + hand-rolled CSS** (no build step) | ships fast, exact design control |
| UI language | **Syne** (display) + **Space Grotesk** (body), light-first minimal with an optional dark theme, single red accent | design system |
| Repo | Git (GitHub) | submission requires a repo + README |

---

## 3. Architecture

```
                    ┌──────────────────────────────┐
                    │     Browser (SPA dashboard)  │
                    └──────────────┬───────────────┘
                                   │ /api/*
                    ┌──────────────▼───────────────┐
                    │          FastAPI layer        │
                    │  routes/ → validation → DTO   │
                    └──────┬───────────────┬────────┘
                           │               │
              ┌────────────▼────┐  ┌───────▼─────────────────┐
              │ Service layer  │  │  Quota/retry/backoff    │
              │ research       │  │  (shared middleware)    │
              │ generate       │  │                          │
              │ refresh        │  └───┬──────┬───────┬──────┘
              └──────┬─────────┘      │      │       │
                     │                │      │       │
        ┌────────────▼────┬───────────▼──┬───▼───────▼─────────┐
        │ Repository/DB  │ YouTubeAdapter│ GroqAdapter        │
        │ (SQLite WAL)  │ (API client) │ (no key → rule      │
        │                │              │  fallback)          │
        └────────────────┴──────────────┴─────────────────────┘
```

**Layering rules**
- Routes contain **no business logic** — they validate and call services.
- Services orchestrate; adapters own external I/O.
- All SQLite access sits behind the repository module (swap-testable, transactional).
- Every external call wraps errors into typed exceptions that the API maps to `409/429/502/503` with a safe message.

### Module layout

```
vidgrid/
├── app/
│   ├── main.py          # FastAPI app, static mount, CORS, startup
│   ├── config.py        # env parsing, pydantic-settings, .env
│   ├── db.py            # connection mgmt, WAL, schema migration
│   ├── repositories.py  # niches / videos / patterns / packages / hooks
│   ├── services/
│   │   ├── research.py        # orchestrate an research run
│   │   ├── generator.py       # build package (AI or rule)
│   │   ├── refresh.py         # re-poll stats, re-rank hooks
│   │   └── kit.py             # upload-ready kit from a finished script
│   ├── adapters/
│   │   ├── youtube.py         # Data API client + quota budget
│   │   ├── ai.py              # Groq client + strict-JSON parsing
│   │   └── rules.py           # deterministic template engine (fallback)
│   ├── patterns.py            # hook/keyword/format extractor (pure)
│   └── scoring.py             # engagement-score math (pure, unit-testable)
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tests/                     # pytest; fixtures with real-shaped JSON
├── README.md
├── .env.example
├── requirements.txt
└── PLAN.md
```

---

## 4. Data model (SQLite)

```
schemas migrated at startup (sqlite WAL, foreign_keys=on)

niches
  id TEXT PK (slugified)
  name TEXT UNIQUE
  window_days INTEGER DEFAULT 90
  created_at, last_research_at, total_runs

research_runs
  id INTEGER PK AUTOINCREMENT
  niche_id FK
  started_at, video_count, api_units_used

videos
  youtube_id TEXT PK
  niche_id TEXT FK
  title, channel_title, thumbnail_url,
  published_at TEXT ISO, duration_sec INTEGER,
  views, likes, comments INTEGER,
  tags_json TEXT, description_txt TEXT,
  engagement_score REAL,      -- derived, see §5
  collected_at, refreshed_at

patterns
  id INTEGER PK
  niche_id, run_id
  kind TEXT          -- hook_type | keyword | duration_bucket | cadence
  value TEXT
  occurrences INTEGER
  avg_score REAL

packages
  id INTEGER PK
  niche_id, created_at
  ai_source TEXT     -- 'groq' | 'rules'
  titles_json TEXT   -- [{title, ctr_estimate, rationale}]
  summary TEXT       -- description + SEO
  tags_json TEXT     -- [..]
  script TEXT
  thumbnails_json    -- [{concept, subject, text_style, colors}]

hooks
  id INTEGER PK
  source_video_id TEXT FK videos
  niche_id, hook_type, hook_text, score, updated_at
  -- the compounding "proven hooks" library
```

Indexes: `videos(niche_id, engagement_score DESC)`, `patterns(niche_id, kind)`, `hooks(niche_id, score DESC)`.

---

## 5. Engagement math (the "pattern" core)

For each observed video compute:

```
age_days      = (now - published_at).days + 1
views_rate    = views / age_days
like_ratio    = likes / max(views, 1)
comment_ratio = comments / max(views, 1) * 1000 (per-1k)
engagement    = 0.5*log1p(views_rate) + 0.3*like_ratio*10 + 0.2*comment_ratio
rank          = percentile rank of engagement within run's cohort
```

A hook is **"proven"** when its video ranks ≥ p75 with age ≥ 30 days. The `refresh` run recomputes these so the "hook library" improves over time — the compounding story for the demo/write-up.

### Pattern extractor (pure functions, rule-based — no AI cost)

1. **Tokenize** titles (regex, lowercase; strip numbers→`<n>`, stop-word list).
2. **Hook classifier**: regex/rules → `listicle`, `how-to`, `question`, `number-led`, `benefit/promise`, `urgency`, `comparison`, `curiosity-gap`.
3. **Recurring keywords**: frequency over titles + top tags (after stop-words).
4. **Cohort features**: median duration bucket, best posting day-of-week by views_rate, word-count statistics.
5. Everything summed into a `research_summary` JSON passed to the AI (or used directly by the rule engine).

---

## 6. API contract

All JSON, errors: `{ "error": { "code", "message" } }`.

| Route | Method | Purpose |
|---|---|---|
| `/api/niches` | GET/POST | list / create a niche (name, windowDays) |
| `/api/niches/{id}` | GET | detail: latest research summary + patterns |
| `/api/niches/{id}/research` | POST | run fresh research (search + videos stats) |
| `/api/niches/{id}/generate` | POST | produce a package (`{force_rules:bool}`) |
| `/api/niches/{id}/packages` | GET | package library for the niche |
| `/api/niches/{id}/refresh` | POST | re-poll stats on observed videos, re-rank hooks |
| `/api/niches/{id}/hooks` | GET | the compounding hook leaderboard |
| `/api/chat` | POST | story-studio chat, grounded in the niche's research |
| `/api/story/kit` | POST | upload-ready kit (titles/tags/description) from a script |

---

## 7. YouTube adapter (quota-aware)

- `search.list` (cost **100**), `videos.list` (cost **1** each video part request).
- Fetch pages up to a **budget** (default 30 videos → 1 search + 1 videos.list batch). Quota estimate tracked per run, per day; fails early w/ `429`-style message on edge.
- Built-in retries (3, exponential+ jitter), 429/5xx aware.
- Thumbnails cached (`maxres/standard/hqdefault`) for thumbnail-concept mockups.
- Input validated (length, charset); niche must be a real search term.

**Terms compliance:** official API only, no scrape, no rate abuse.

---

## 8. AI adapter (Groq free tier + strict fallback)

1. Service builds a compact `research_summary` + niche context.
2. Prompt asks for **strict JSON** (schema shown explicitly).
3. Groq returns OpenAI-compatible JSON (`response_format`), temperature ~1.0; free tier with up to 3 rotating keys.
4. Response validated against schema; if malformed/missing/rate-limited → **rule engine fallback** produces a valid package (titles from proven hook templates + keywords, script outline built from a proven structure, thumbnail concept from top hook + palette).
5. `packages.ai` records which engine made it — transparent.

Generated output:
- **Titles**: 5 variants each with `{ctr_estimate, rationale, hook_type, length}`.
- **Description**: 2–3 line hook + expander text, filled with keywords.
- **Tags**: top 12 from research + niche.
- **Script**: full script w/ intro hook, outline with timestamps, patterns borrowed from the winning cohort, plus a call-to-action.
- **Thumbnail concepts**: 3 concepts `{subject, headline (≤3 words), face_or_diagram, palette, layout}` — rendered as CSS/real-frame mockups in the UI.

---

## 9. Dashboard design (senior-product bar)

**Design system**
- Palette: **paper white** `#FAF9F6` base, cards `#FFFFFF`, hairlines `#E8E5DE`; **accent terracotta** `#C06547`; text `#1F1E1B`; muted `#817C72`. Claude-inspired light/minimal.
- Typography: **Bricolage Grotesque** for display and body (headlines/logo/stat numerals). Loaded via Google Fonts, default to system sans.
- Feel: Linear/Stripe-grade — 1px hairline borders, subtle ambient glow, micro-transitions, opacity stagger, no heavy shadows, mono tabular numerals for stats.
- States: loading (spinner + skeleton), error (toast + inline retry), empty (onboarding copy).

**Views (one-page app, left rail):**
1. **Research** — input niche → progress (searching… scoring… extracting) → results: cohort table w/ engagement bars, pattern chips, top hooks.
2. **Package** — the generated package, fully copyable (title chips w/ CTR, description block, tag chips, script w/ copy, thumbnail mockups rendered with the real chosen palette + font).
3. **Library** — the compounding hook/idea leaderboard w/ "proven" badges, sort by score, age/coverage.
4. Top banner: quote used today, last refresh.

**Post-states**: all destructive (regenerate/refresh) require a confirm; copy buttons give a micro "copied" state.

---

## 10. Testing strategy

- `pytest` + `tests/fixtures/youtube.json` shaped from real API responses (captured once with a key, stripped).
- Unit: engagement math, hook extractor, keyword extractor, rule-generator determinism.
- API: `TestClient` integration for research→generate→refresh flow against a temp SQLite.
- Manual/e2e: run locally with real keys on the seeded data, record demo video.

---

## 11. Timeline → Deadline Aug 31

| Slot | Hours | Deliverable |
|---|---|---|
| Sat AM | 1.5 | Scaffold, env harness, DB schema + repos, FastAPI shell |
| Sat PM | 5 | YouTube adapter + quota budget + research service + tests |
| Sun AM | 4 | Pattern extractor + engagement math + research summary JSON |
| Sun PM | 5 | AI adapter + rules fallback + package generation + tests |
| Mon AM | 4 | API complete / integration tests / refresh job |
| Mon PM | 4 | Dashboard v1 + design polish |
| Tue AM | 3 | Hardening: empty states, errors, cancel on regenerate, double-check imports |
| Tue PM | 3 | README, `.env.example`, demo video (2–4 min) + write-up + submit |

Buffer ≈ 4h = 0. **Gate**: if anything slips, cut scope *from the dashboard*, never from the core loop.

## 12. Submission pack (Devpost)

1. **Repo** — GitHub, private→final 24h before deadline, README w/ architecture diagram (from §3), quickstart, screenshot, `.env.example`.
2. **Demo video (2–4 min)** — script: problem (2–3h research/scripting) → 60s show both a fresh niche AND the compounding library → rules-fallback shown if AI absent.
3. **Write-up (title + few sentences)**: the problem, how it works, tech stack, the compounding moat.

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| No Groq key / rate limit | rule engine always works; code path demoed |
| YouTube quota exhausted live | cache + daily budget warning; demo on seeded DB |
| Rare niche → zero results | friendly empty states + broaden suggestion |
| Time overrun | dashboard is the only sacrifceable |
| OAuth/API keys in repo | `.env`, `.gitignore`, rotate in guide |

---

## Status

(_All core items shipped; the list below records the original plan._)

- [x] Scaffold + repo + harness
- [x] Schema + repositories
- [x] YouTube adapter + research
- [x] Pattern extractor + engagement math
- [x] AI adapter + rule fallback
- [x] API layer + tests
- [x] Refresh/compling job
- [x] Dashboard (design system + views)
- [x] Hardening + final integration test
- [ ] README + demo video + write-up  ← remaining for submission