"""Gemini adapter (free tier) that returns strictly-validated JSON packages.

If no key is configured, calls fail fast with AINotConfigured so the service
layer can transparently fall back to the rule engine.
"""

import json
import re
import time

import httpx

from ..config import get_settings

PACKAGE_SCHEMA_HINT = {
    "titles": [
        {"title": "string", "ctr_estimate": 0.0, "hook_type": "string",
         "rationale": "string"}
    ],
    "tags": ["string"],
    "summary": "string",
    "script": "string",
    "thumbnails": [
        {"concept": "string", "headline": "string", "palette": {"bg": "string", "text": "string"},
         "layout": "string", "hook": "string"}
    ],
}


class AINotConfigured(Exception):
    pass


class AIRateLimited(Exception):
    pass


class AIError(Exception):
    pass


JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

KIT_SCHEMA_HINT = {
    "titles": [
        {"title": "string", "ctr_estimate": 0.0, "hook_type": "string"}
    ],
    "tags": ["string"],
    "description": "string",
}


def _build_kit_prompt(script: str, niche: str) -> str:
    """Turn a finished story script into an upload-ready kit: title variants,
    tags and a description with timestamps matching the script."""
    return f"""
You are the packaging editor for a YouTube channel in the niche "{niche}".
The creator has written the story script below and needs it made
upload-ready for 2026 YouTube best practice.

SCRIPT:
{script[:6000]}

Create a package following the rules strictly:

1. TITLES — exactly 5 distinct variants. Hard rules:
   - 45-70 characters each (mobile shows ~60; the hook must survive truncation).
   - Each uses only ONE hook style (curiosity, number, mistake, story, promise,
     or contrast) matching the script's core payoff.
   - Prefer odd numbers (7, 9, 11) over 5/10 when a number fits.
   - No year, no ALL CAPS, no "in this video".
   - Give each a CTR estimate between 4.0 and 7.5.
2. TAGS — exactly 12: the niche phrase first, then long-tail phrases drawn
   from the script, then singles. Limit ~25 chars each.
3. description — a YouTube description:
   - Line 1: the script's core promise (this line shows before "Show more").
   - A 3-5 line middle with short paragraphs, keyword-carrying.
   - A TIMESTAMPS block matching the script's beats.
   - Exactly 3 relevant hashtags on the final line.

Respond with ONLY a single JSON object matching exactly this schema:
{json.dumps(KIT_SCHEMA_HINT, ensure_ascii=False)}
No markdown, no commentary.
"""


def _validate_kit(data: dict) -> dict | None:
    try:
        titles = data["titles"]
        if not isinstance(titles, list) or not titles:
            return None
        clean = []
        for t in titles[:5]:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            clean.append({
                "title": str(t["title"])[:75],
                "ctr_estimate": float(t.get("ctr_estimate", 3.0)),
                "hook_type": str(t.get("hook_type", "story")),
            })
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
            tags = []
        description = str(data.get("description", ""))
        if not clean or not description.strip():
            return None
        return {"titles": clean, "tags": tags[:12], "description": description}
    except (KeyError, TypeError, ValueError):
        return None


def _build_prompt(niche: str, summary: dict) -> str:
    return f"""
You are the senior YouTube research-and-packaging editor for a channel in the
niche "{niche}". Below is a JSON summary produced by analysing recent top
performing videos in this niche with the YouTube Data API.

Research summary:
{json.dumps(summary, ensure_ascii=False)}

Create a complete, copy-paste-ready video package built on 2026 best
practice. Follow the rules strictly:

1. TITLES — exactly 5 distinct variants. Hard rules:
   - 45-70 characters each (mobile shows ~60; the hook must survive truncation).
   - Primary niche keyword inside the first 40 chars (front-load it).
   - Each uses only ONE hook style strongly — pick from the hook_types that
     appear in the research, never stack three formulas in one title.
   - Prefer odd numbers (7, 9, 11) over 5/10 when a number fits.
   - Add a single low-risk power verb or curiosity gap (stop, mistakes, the
     real, nobody tells you, or a specific number) — no year, no ALL CAPS,
     no "in this video".
   - Give each a CTR estimate between 4.0 and 7.5 and a one-line rationale
     tied to the research.
2. TAGS — exactly 12, topically relevant, not generic spam. First tag must be
   the exact niche phrase; then 2-3 word long-tail phrases derived from the
   research keywords; then singles. Limit ~25 chars each.
3. summary — a YouTube description:
   - Line 1: primary keyword + the viewer's benefit (this line is what shows
     before "Show more").
   - A 3-5 line keyword-carrying middle with short paragraphs.
   - A TIMESTAMPS block matching the script's beats.
   - Exactly 3 relevant hashtags on the final line.
   - No link dumps, no keyword stuffing.
4. script — a full ~450-600 word script, retention-first:
   - Open with a pattern interrupt that states the specific payoff in the
     first 3-10 seconds [HOOK]. NO greeting, NO "hey guys". Your audience
     decides to stay in the first 15-30 seconds.
   - Then an opener that promises the one thing {niche} viewers actually
     want [OPENLOOP], a first concrete payoff ~40s in [PAYOFF], each later
     30-60s section [REHOOK] and [CLOSE LOOP] opens+closes a new loop, and
     end with ONE specific call to action - never stacked like subscribe+
     comment+like together [CTA].
   - Write for the ear: contractions, short sentences under 20 words, "you"
     constantly.
   - Write in the plainspoken voice of the niche's top performers (from the
     summary), hooks first.
5. thumbnails — exactly 3 concepts:
   - headline: max 4 WORDS, highest-emotion word first.
- palette: high-contrast pairs only (light text on a deep bg or dark text
      on a bright bg), given as {{bg, text}} hex.
   - layout: single focal point, max ONE visual cue (arrow, number, or
     ellipse) and a short hook line of copy.

Respond with ONLY a single JSON object matching exactly this schema:
{json.dumps(PACKAGE_SCHEMA_HINT, ensure_ascii=False)}
No markdown, no commentary.
"""


class GeminiClient:
    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = settings.gemini_model
        self.timeout = timeout or settings.gemini_timeout_seconds

    def chat(self, messages: list[dict]) -> str:
        """Plain-text conversational reply (story scripts etc.). No schema.

        System messages become the API's systemInstruction; user/assistant
        turns alternate in `contents` (Gemini rejects consecutive same-role
        entries, and roles must be user/model)."""
        if not self.api_key:
            raise AINotConfigured("GEMINI_API_KEY not set.")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        system_texts = [
            str(m.get("content", ""))
            for m in messages
            if str(m.get("role")) == "system"
        ]
        contents: list[dict] = []
        for m in messages:
            if str(m.get("role")) == "system":
                continue
            role = "model" if str(m.get("role")) in ("ai", "assistant") else "user"
            text = str(m.get("content", ""))
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n\n" + text
            else:
                contents.append({"role": role, "parts": [{"text": text}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 1.0,
                "maxOutputTokens": 4096,
            },
        }
        if system_texts:
            payload["systemInstruction"] = {
                "role": "user",
                "parts": [{"text": "\n".join(system_texts)}],
            }
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini request failed: {exc}") from exc

        if resp.status_code == 429:
            raise AIRateLimited("Gemini free-tier quota exhausted for the moment.")
        if resp.status_code != 200:
            raise AIError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Unexpected Gemini response shape.") from exc

    def generate_package(self, niche: str, summary: dict) -> dict:
        if not self.api_key:
            raise AINotConfigured("GEMINI_API_KEY not set.")
        prompt = _build_prompt(niche, summary)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 1.0,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini request failed: {exc}") from exc

        if resp.status_code == 429:
            raise AIRateLimited("Gemini free-tier quota exhausted for the moment.")
        if resp.status_code != 200:
            raise AIError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Unexpected Gemini response shape.") from exc

        text = text.strip()
        block = JSON_BLOCK.search(text)
        if block:
            text = block.group(1)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError("Gemini returned non-JSON; falling back.") from exc

        validated = _validate_package(parsed)
        if validated is None:
            raise AIError("Gemini JSON failed schema validation.")
        return validated

    def generate_kit(self, script: str, niche: str) -> dict:
        """Upload-ready kit (titles/tags/description) from a finished script."""
        if not self.api_key:
            raise AINotConfigured("GEMINI_API_KEY not set.")
        prompt = _build_kit_prompt(script, niche)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 1.0,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini request failed: {exc}") from exc

        if resp.status_code == 429:
            raise AIRateLimited("Gemini free-tier quota exhausted for the moment.")
        if resp.status_code != 200:
            raise AIError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Unexpected Gemini response shape.") from exc

        text = text.strip()
        block = JSON_BLOCK.search(text)
        if block:
            text = block.group(1)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError("Gemini returned non-JSON; falling back.") from exc

        validated = _validate_kit(parsed)
        if validated is None:
            raise AIError("Gemini JSON failed schema validation.")
        return validated


class GroqClient:
    """OpenAI-compatible chat endpoint (api.groq.com). Same schema + validator as Gemini.
    Rotates through GROQ_API_KEY / _2 / _3: daily-quota hits and bad credentials
    roll to the next key; per-minute 429s and provider errors retry in place."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float | None = None) -> None:
        settings = get_settings()
        self.api_keys = ([api_key] if api_key else settings.groq_keys)
        self.model = model or settings.groq_model
        self.timeout = timeout or settings.groq_timeout_seconds

    def generate_package(self, niche: str, summary: dict) -> dict:
        if not self.api_keys:
            raise AINotConfigured("GROQ_API_KEY not set.")
        prompt = _build_prompt(niche, summary)

        last_error: Exception | None = None
        # 1 attempt per key is enough here: heavy retries belong in shared web
        # jobs; vidpack regenerating is cheap and the user can hit "generate" again.
        for index, api_key in enumerate(self.api_keys):
            try:
                parsed = self._call_json(api_key, prompt)
                validated = _validate_package(parsed)
                if validated is not None:
                    return validated
                raise AIError("Groq JSON failed schema validation.")
            except AIRateLimited:
                # per-minute TPM limit or transient provider failure -> back off,
                # then keep going down the key ring
                if index < len(self.api_keys) - 1:
                    time.sleep(10)
                last_error = AIRateLimited("Groq rate-limited.")
            except (AIError, json.JSONDecodeError) as exc:
                last_error = exc
                if index >= len(self.api_keys) - 1:
                    break
        raise last_error or AIError("Groq generation failed.")

    def chat(self, messages: list[dict]) -> str:
        """Plain-text conversational reply (story scripts etc.). No schema."""
        if not self.api_keys:
            raise AINotConfigured("GROQ_API_KEY not set.")
        last_error: Exception | None = None
        for index, api_key in enumerate(self.api_keys):
            try:
                return self._call_text(api_key, messages)
            except AIRateLimited:
                if index < len(self.api_keys) - 1:
                    time.sleep(10)
                last_error = AIRateLimited("Groq rate-limited.")
            except AIError as exc:
                last_error = exc
                if index >= len(self.api_keys) - 1:
                    break
        raise last_error or AIError("Groq chat failed.")

    def generate_kit(self, script: str, niche: str) -> dict:
        """Upload-ready kit (titles/tags/description) from a finished script."""
        if not self.api_keys:
            raise AINotConfigured("GROQ_API_KEY not set.")
        prompt = _build_kit_prompt(script, niche)
        last_error: Exception | None = None
        for index, api_key in enumerate(self.api_keys):
            try:
                parsed = self._call_json(api_key, prompt)
                validated = _validate_kit(parsed)
                if validated is not None:
                    return validated
                raise AIError("Groq kit JSON failed schema validation.")
            except AIRateLimited:
                if index < len(self.api_keys) - 1:
                    time.sleep(10)
                last_error = AIRateLimited("Groq rate-limited.")
            except (AIError, json.JSONDecodeError) as exc:
                last_error = exc
                if index >= len(self.api_keys) - 1:
                    break
        raise last_error or AIError("Groq kit generation failed.")

    def _call_text(self, api_key: str, messages: list[dict]) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 1.0,
            "max_tokens": 4096,
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Groq request failed: {exc}") from exc

        text = resp.text[:300]
        if resp.status_code == 429:
            body_lower = resp.text[:1000].lower()
            if "tokens per day" in body_lower or "tpd" in body_lower:
                raise AIRateLimited("Groq daily quota exhausted for this key.")
            raise AIRateLimited(f"Groq rate-limited (429): {text}")
        if resp.status_code in (401, 403):
            raise AIError(f"Groq key rejected ({resp.status_code}).")
        if resp.status_code != 200:
            raise AIError(f"Groq API error {resp.status_code}: {text}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Unexpected Groq response shape.") from exc

    def _call_json(self, api_key: str, prompt: str) -> dict:
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Groq request failed: {exc}") from exc

        text = resp.text[:300]
        if resp.status_code == 429:
            body_lower = resp.text[:1000].lower()
            if "tokens per day" in body_lower or "tpd" in body_lower:
                raise AIRateLimited("Groq daily quota exhausted for this key.")
            raise AIRateLimited(f"Groq rate-limited (429): {text}")
        if resp.status_code in (401, 403):
            raise AIError(f"Groq key rejected ({resp.status_code}).")
        if resp.status_code != 200:
            raise AIError(f"Groq API error {resp.status_code}: {text}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Unexpected Groq response shape.") from exc

        content = (content or "").strip()
        block = JSON_BLOCK.search(content)
        if block:
            content = block.group(1)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIError("Groq returned non-JSON; falling back.") from exc


def _validate_package(data: dict) -> dict | None:
    def is_list_of_strings(v) -> bool:
        return isinstance(v, list) and v and all(isinstance(i, str) for i in v)

    try:
        titles = data["titles"]
        if not isinstance(titles, list) or not titles:
            return None
        clean_titles = []
        for t in titles[:5]:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            clean_titles.append({
                "title": str(t["title"])[:75],
                "ctr_estimate": float(t.get("ctr_estimate", 3.0)),
                "hook_type": str(t.get("hook_type", "how-to")),
                "rationale": str(t.get("rationale", ""))[:160],
            })

        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(
            isinstance(x, str) for x in tags
        ):
            tags = []

        summary = str(data.get("summary", ""))
        script = str(data.get("script", ""))
        thumbs = data.get("thumbnails", [])
        clean_thumbs = []
        if isinstance(thumbs, list):
            for th in thumbs[:3]:
                if not isinstance(th, dict):
                    continue
                palette = th.get("palette")
                if not isinstance(palette, dict):
                    palette = {"bg": "#4DA3FF", "text": "#0A0B0F"}
                clean_thumbs.append({
                    "concept": str(th.get("concept", "Concept")),  # placeholder branch
                    "headline": str(th.get("headline", "Big news"))[:24],
                    "palette": {"bg": str(palette.get("bg", "#4DA3FF")),
                                "text": str(palette.get("text", "#0A0B0F"))},
                    "layout": str(th.get("layout", "face + text")),
                    "hook": str(th.get("hook", ""))[:120],
                })

        if not clean_titles or not (summary and script):
            return None

        return {
            "titles": clean_titles,
            "tags": tags[:12] or ["youtube", "tutorial"],
            "summary": summary,
            "script": script,
            "thumbnails": clean_thumbs[:3],
        }
    except (KeyError, TypeError, ValueError):
        return None


def get_ai():
    """Return the configured AI client: Gemini if set, else Groq, else a stub that
    raises AINotConfigured so the service layer can fall back to rules."""
    settings = get_settings()
    if settings.has_gemini_key:
        return GeminiClient()
    if settings.has_groq_key:
        return GroqClient()
    return GeminiClient()