# config.py
# ---------------------------------------------------------
# All settings in one place. MVP — one LLM provider, no
# per-task overrides, no fallback chains.
# ---------------------------------------------------------

import os
from dotenv import load_dotenv

load_dotenv()

# ── Twilio (WhatsApp gateway) ─────────────────────────────
TWILIO_ACCOUNT_SID    = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN     = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
OWNER_WHATSAPP_NUMBER = os.getenv("OWNER_WHATSAPP_NUMBER", "")  # e.g. "whatsapp:+91XXXXXXXXXX"

# ── LLM Providers ───────────────────────────────────────────────

# Order in which providers are tried.
# Example:
# LLM_PRIORITY=gemini,groq,openai,qwen
#
# The first provider that responds successfully is used.
LLM_PRIORITY = [
    p.strip().lower()
    for p in os.getenv(
        "LLM_PRIORITY",
        "gemini,groq,openai,qwen"
    ).split(",")
]

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Qwen
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
QWEN_API_BASE = os.getenv(
    "QWEN_API_BASE",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# ── TidyCal (real booking) ────────────────────────────────
TIDYCAL_API_KEY         = os.getenv("TIDYCAL_API_KEY", "")
TIDYCAL_BOOKING_TYPE_ID = os.getenv("TIDYCAL_BOOKING_TYPE_ID", "")
TIDYCAL_API_BASE        = os.getenv("TIDYCAL_API_BASE", "https://tidycal.com/api")
TIDYCAL_TIMEZONE        = os.getenv("TIDYCAL_TIMEZONE", "Asia/Kolkata")
BOOKING_LINK            = os.getenv("BOOKING_LINK", "https://tidycal.com/freediscoverysession/fynlo-demo-discussion")

# ── Persona ────────────────────────────────────────────────
BUSINESS_NAME = "Fynlo"
BOT_NAME      = "Jessy"