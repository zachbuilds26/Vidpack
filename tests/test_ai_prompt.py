from app.adapters.ai import _build_prompt


def test_prompt_locks_2026_title_rules():
    prompt = _build_prompt("budget cooking", {})
    assert "45-70 characters" in prompt
    assert "first 40 chars" in prompt
    assert "ONE hook style" in prompt
    assert "Odd numbers" in prompt or "odd numbers" in prompt.lower()
    assert "no ALL CAPS" in prompt


def test_prompt_locks_tag_and_description_rules():
    prompt = _build_prompt("budget cooking", {})
    assert "exactly 12" in prompt
    assert "exact niche phrase" in prompt
    assert "TIMESTAMPS" in prompt
    assert "Exactly 3 relevant hashtags" in prompt
    assert "No link dumps" in prompt


def test_prompt_locks_script_and_thumbnail_rules():
    prompt = _build_prompt("budget cooking", {})
    assert "[HOOK]" in prompt and "[OPENLOOP]" in prompt and "[PAYOFF]" in prompt
    assert "[REHOOK]" in prompt and "[CLOSE LOOP]" in prompt and "[CTA]" in prompt
    assert "NO greeting" in prompt
    assert "under 20 words" in prompt
    assert "max 4 WORDS" in prompt
    assert "high-contrast" in prompt


def test_prompt_interpolates_niche():
    prompt = _build_prompt("gym motivation", {})
    assert '"gym motivation"' in prompt
