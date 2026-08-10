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

# WhatsApp only allows freeform business messages within a 24h window after
# the recipient last messaged you (error 63016 otherwise). For a reliable
# escalation alert to the owner (who may not have texted the bot recently),
# use an APPROVED WhatsApp Message Template instead — set this to that
# template's Content SID (Twilio Console -> Content Template Builder, after
# WhatsApp approves it). Leave blank to keep using freeform (only works if
# the owner has messaged within the last 24h).
TWILIO_ESCALATION_TEMPLATE_SID = os.getenv("TWILIO_ESCALATION_TEMPLATE_SID", "")

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
        "gemini,groq,openai,qwen,mistral"
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

# Mistral
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

# ── TidyCal (real booking) ────────────────────────────────
TIDYCAL_API_KEY         = os.getenv("TIDYCAL_API_KEY", "")
TIDYCAL_BOOKING_TYPE_ID = os.getenv("TIDYCAL_BOOKING_TYPE_ID", "")
TIDYCAL_API_BASE        = os.getenv("TIDYCAL_API_BASE", "https://tidycal.com/api")
TIDYCAL_TIMEZONE        = os.getenv("TIDYCAL_TIMEZONE", "Asia/Kolkata")
BOOKING_LINK            = os.getenv("BOOKING_LINK", "https://tidycal.com/freediscoverysession/fynlo-demo-discussion")

# ── Persona ────────────────────────────────────────────────
BUSINESS_NAME = "Fynlo"
BOT_NAME      = "Jessy"