# llm.py
# ---------------------------------------------------------
# One function: send a prompt, get text back. MVP — a single
# provider (set in config.py), short timeout + one retry so a
# slow/failing LLM call can't blow past Twilio's ~15s webhook
# window and cause the user to get no reply at all.
# ---------------------------------------------------------

import logging
from functools import lru_cache

from config import (
    LLM_PROVIDER,
    GEMINI_API_KEY, GEMINI_MODEL,
    GROQ_API_KEY, GROQ_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    QWEN_API_KEY, QWEN_MODEL, QWEN_API_BASE,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client():
    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            # Gemini's API rejects deadlines under 10s outright (400
            # INVALID_ARGUMENT: "Manually set deadline Xs is too short.
            # Minimum allowed deadline is 10s.") — Groq/OpenAI are fine with
            # 8s, Gemini specifically needs at least 10.
            model=GEMINI_MODEL, google_api_key=GEMINI_API_KEY,
            temperature=0.3, max_retries=1, timeout=10,
        )
    if LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=GROQ_MODEL, groq_api_key=GROQ_API_KEY,
            temperature=0.3, max_retries=1, timeout=8,
        )
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=OPENAI_MODEL, api_key=OPENAI_API_KEY,
            temperature=0.3, max_retries=1, timeout=8,
        )
    if LLM_PROVIDER == "qwen":
        # DashScope exposes an OpenAI-compatible chat/completions endpoint,
        # so ChatOpenAI works as-is — just point base_url at DashScope and
        # pass the Qwen API key instead of an OpenAI one.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=QWEN_MODEL, api_key=QWEN_API_KEY, base_url=QWEN_API_BASE,
            temperature=0.3, max_retries=1, timeout=10,
        )
    raise ValueError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}' — use gemini, groq, openai, or qwen")


def ask_llm(prompt: str) -> str:
    """Send a prompt string, get the raw text response back. Raises on failure — caller handles it."""
    return _get_client().invoke(prompt).content.strip()