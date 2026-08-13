# time_parser.py
# ---------------------------------------------------------
# Turns whatever a human types ("tomorrow at 3pm", "Friday
# morning", "thurday after 2" [typo], "sometime in the
# afternoon") into a real datetime.
#
# Two-step approach:
#   1. Try dateparser first — fast, free, no API call, and
#      handles most normal phrasing fine.
#   2. If that fails (typos, vague ranges like "afternoon",
#      unusual phrasing), ask the LLM to normalize it into a
#      clean date/time string, then retry dateparser on that.
#
# This keeps the common case cheap (no LLM call at all) and
# only pays the extra latency/cost for the fuzzy cases that
# actually need it.
# ---------------------------------------------------------

import logging
from datetime import datetime
import dateparser

from config import TIDYCAL_TIMEZONE
from llm import ask_llm

logger = logging.getLogger(__name__)

_SETTINGS = {
    "TIMEZONE": TIDYCAL_TIMEZONE,
    "RETURN_AS_TIMEZONE_AWARE": True,
    "PREFER_DATES_FROM": "future",
}

_FUZZY_TIME_PROMPT = """The user is booking a meeting and typed this as their preferred time: "{text}"

Current date/time: {now} (timezone: {timezone})

Convert it into a clean, unambiguous date/time string in the format "YYYY-MM-DD HH:MM".
- Fix obvious typos (e.g. "thurday" means "Thursday", "tommorow" means "tomorrow").
- If they gave a vague range ("afternoon", "after 2"), pick one reasonable exact
  time within it (afternoon -> 14:00, "after 2" -> 14:30, morning -> 10:00).
- "after X" means strictly later than X, never exactly X, pick a small
  reasonable offset past it (e.g. "after 2pm" -> 14:30, "after 5" -> 17:15).
- "before X" means strictly earlier than X, never exactly X, pick a small
  reasonable offset before it (e.g. "before 11am" -> 10:30, "before noon" -> 11:30).
- If they gave just a day with no time, use 10:00 as the default.
- If the text genuinely isn't a date/time at all (e.g. random words), reply with
  exactly the word UNKNOWN and nothing else.

Reply with ONLY the formatted string or UNKNOWN — no explanation, no extra words."""


import re

# "after 2pm" / "before 11am" etc — dateparser silently DROPS this word and
# returns the literal clock time (2:00pm exactly), not "sometime after
# 2pm". That produced real booking bugs: a user asking for "after 2pm"
# would get booked at exactly 2:00pm, or told 2:00pm wasn't free when a
# later free slot the same day would have satisfied their actual request.
# Force these through the LLM normalizer instead, which is explicitly
# instructed above to apply a real offset.
_RELATIVE_QUALIFIER_RE = re.compile(r"\b(after|before)\b", re.IGNORECASE)


def _looks_like_bad_guess(text: str, result: datetime) -> bool:
    """
    dateparser can "succeed" with a wrong answer instead of failing outright —
    e.g. "thursday after 2" (no am/pm) gets misread and silently defaults to
    midnight a year in the future, rather than returning None. If the user's
    text contains a digit (implying they meant a specific time) but the
    result landed on exact midnight with no "midnight"/"12am" wording, treat
    that as a bad guess and fall through to the LLM instead of trusting it.
    """
    has_digit = bool(re.search(r"\d", text))
    is_midnight = result.hour == 0 and result.minute == 0
    said_midnight = bool(re.search(r"midnight|12\s*a\.?m\.?", text, re.IGNORECASE))
    return has_digit and is_midnight and not said_midnight


def parse_preferred_time(text: str) -> datetime | None:
    """
    Returns a timezone-aware datetime if a date/time could be parsed,
    otherwise None (caller should ask the user to rephrase).
    """
    # Step 1: try the fast, free, no-API-call path first — but not for
    # "after X" / "before X" phrasing, since dateparser drops that word
    # entirely and returns the literal time X, not an offset from it.
    result = dateparser.parse(text, settings=_SETTINGS)
    has_relative_qualifier = bool(_RELATIVE_QUALIFIER_RE.search(text))
    if result is not None and not _looks_like_bad_guess(text, result) and not has_relative_qualifier:
        return result
    if result is not None:
        reason = "relative qualifier ('after'/'before')" if has_relative_qualifier else "suspicious result"
        logger.info(f"dateparser result for '{text}' ({result}) needs LLM normalization: {reason}")

    # Step 2: dateparser gave up — ask the LLM to clean up typos/vague
    # phrasing, then retry dateparser on its cleaned-up output.
    try:
        import zoneinfo
        now_str = datetime.now(zoneinfo.ZoneInfo(TIDYCAL_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        cleaned = ask_llm(
            _FUZZY_TIME_PROMPT.format(text=text, now=now_str, timezone=TIDYCAL_TIMEZONE)
        ).strip()
        logger.info(f"Fuzzy time parse: '{text}' -> '{cleaned}'")

        if cleaned.upper() == "UNKNOWN" or not cleaned:
            return None

        return dateparser.parse(cleaned, settings=_SETTINGS)

    except Exception as e:
        logger.error(f"Fuzzy LLM time parsing failed, giving up: {e}")
        return None