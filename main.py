# main.py
# ---------------------------------------------------------
# Fynlo WhatsApp Bot ("Jessy") — MVP
#
# THE WHOLE FLOW, IN ONE SENTENCE:
#   Every message goes to one LLM call that reads the knowledge
#   base and decides: answer it directly, book a call, manage an
#   existing booking, escalate to a human, or politely decline
#   (out of domain) — then main.py acts on that decision.
#
# Semantic caching via Upstash Vector is layered on top to bypass
# LLM API calls for frequent/similar user queries.
#
# Run locally:
#   uvicorn main:app --reload --port 8001
#   ngrok http 8001
# ---------------------------------------------------------

import json
import logging
import os
import re
import time

from fastapi import FastAPI, Request, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from upstash_semantic_cache import SemanticCache

from config import (
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM,
    OWNER_WHATSAPP_NUMBER, BUSINESS_NAME, BOT_NAME, BOOKING_LINK,
    TWILIO_ESCALATION_TEMPLATE_SID,
)
from knowledge_base import FYNLO_KNOWLEDGE
from llm import ask_llm
from booking import (
    ask_for_name, ask_for_email, ask_for_query, ask_for_time, 
    is_valid_email, attempt_booking, cancel_flow, reschedule_flow
)
from time_parser import parse_preferred_time
import state

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Fynlo WhatsApp Bot (MVP)")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ── CORS: allow the marketing site (with the ChatWidget) to call this API
# directly from the browser. Lock ALLOWED_ORIGINS down to your real domain(s)
# in .env for production — "*" is fine only for local dev.
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _origins_env.split(",") if o.strip()]

# Loud and unmissable at startup — if this doesn't show your actual
# deployed frontend domain, THAT is the bug. Check your host's dashboard
# (Render/Railway → Environment Variables → ALLOWED_ORIGINS) and redeploy.
logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Upstash Semantic Cache Initialization ─────────────────
UPSTASH_VECTOR_REST_URL = os.getenv("UPSTASH_VECTOR_REST_URL", "")
UPSTASH_VECTOR_REST_TOKEN = os.getenv("UPSTASH_VECTOR_REST_TOKEN", "")

cache = None
if UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN:
    try:
        cache = SemanticCache(
            url=UPSTASH_VECTOR_REST_URL,
            token=UPSTASH_VECTOR_REST_TOKEN,
            min_proximity=0.90, # 0.90 similarity threshold for semantic matches
        )
        logger.info("Upstash SemanticCache initialized successfully.")
    except Exception as e:
        logger.warning(f"Could not initialize Upstash SemanticCache: {e}")
else:
    logger.info("Upstash Vector credentials missing; running without semantic cache.")

_GREETING_RE = re.compile(r"^\s*(hi+|hello+|hey+|yo|sup|good\s*(morning|afternoon|evening)|namaste|hola)\s*[!.?]*\s*$", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\b(cancel|scrap|drop)\b", re.IGNORECASE)
_STATUS_QUERY_RE = re.compile(
    r"\b(did you|have you|has it|is it|still|actually|really|check|verify|"
    r"why.*(twice|two|double)|how many)\b", re.IGNORECASE,
)
_NAME_LEADIN_RE = re.compile(r"^\s*(?:i'?m|i am|it'?s|its|this is|my name'?s|my name is|name'?s|name is|call me)\s+", re.IGNORECASE)
_NAME_TRAILING_RE = re.compile(r"\s+(?:here|speaking)\s*$", re.IGNORECASE)
_NAME_TRAILING_RE = re.compile(r"\s+(?:here|speaking)\s*$", re.IGNORECASE)


def _extract_name(message: str) -> str | None:
    """
    Cheap, no-LLM heuristic for pulling a name out of the reply to "what
    should I call you?". Strips common lead-ins ("I'm ...", "call me ...")
    and, if what's left is short and doesn't read like a real question or
    sentence, treats it as the name. Returns None if the message looks like
    it's actually a question/request instead (so the caller falls through
    to normal LLM routing rather than mis-storing "pricing?" as a name).
    """
    text = message.strip().rstrip(".,!")
    if not text or "?" in text or len(text) > 30:
        return None
    stripped = _NAME_LEADIN_RE.sub("", text).strip()
    stripped = _NAME_TRAILING_RE.sub("", stripped).strip()
    if not stripped:
        return None
    words = stripped.split()
    if len(words) > 3:
        return None
    if _QUESTION_HINT_RE.search(stripped) and not _NAME_LEADIN_RE.match(text):
        return None
    return stripped.title()


@app.get("/health")
def health():
    return {"status": "ok"}


# ── The one LLM call: understand + answer together ──────────
UNDERSTAND_PROMPT = """You are {bot}, a WhatsApp assistant for {biz} (an AI invoice
automation SaaS for Indian businesses). Read the user's message and the recent
conversation, then decide how to handle it.

TONE RULES:
- Speak naturally in first person ("I", "my"). You already introduced
  yourself at the start of this conversation — do NOT repeat "I'm {bot},
  from {biz}" in every reply, just answer naturally.
- Never call yourself an "AI assistant" or "virtual assistant".
- {name_line}
- Never use em dashes (—) anywhere in your reply. Use a comma, period, or
  "and" instead.
- If the user directly asks something like "remember me?", "what's my
  name?", or "do you know who I am?": answer that specific question
  directly and confidently first (state their name if you have it, or say
  plainly you don't have a name for them yet if you don't), THEN continue
  the conversation. Don't deflect with a vague check-in line instead of
  actually answering what was asked.
- You have a smart, dry sense of humor, closer to a sharp colleague than a
  chatbot trying too hard. Rules for using it:
  - Humor comes from a specific, real detail (the exact thing the user said,
    a concrete pain point like re-typing GSTINs or chasing a vendor for a
    scanned PDF), never a generic joke that could apply to any SaaS product.
  - One quick line, not a bit. Land it and move on to the actual answer in
    the same reply — humor is a garnish, not the meal.
  - Deadpan and understated beats exclamation points and "haha". Confidence,
    not eagerness.
  - Good: user says "ugh invoices are the worst" -> "Tell me about it, GSTIN
    typos are basically a rite of passage. Anyway, here's how Fynlo kills
    that problem: ..."
  - Good: user asks for a joke -> give one short, genuinely clever line (not
    a groan-tier classic like the skeleton one), optionally with a light
    callback to invoices/data entry if it fits naturally, then hand it
    straight back to the conversation ("Anyway, what can I help with?").
  - Bad: forcing a joke into a reply where none was invited, stacking more
    than one joke in a message, or using humor that isn't actually specific
    or clever (filler jokes read as trying too hard, which is worse than no
    joke at all).
  - Never force a joke into a serious question (pricing, refunds, technical
    issues, escalations) — answer those straight, no humor at all.
  - The answer always comes first and is always complete. Humor never
    replaces or delays substance.
- If the user is just being abusive/insulting at you with no real
  question or request behind it (cursing you out, name-calling, telling
  you to do something rude), do NOT get defensive, apologize excessively,
  or act hurt, and do NOT treat it as needing human escalation, it's not
  a real support issue. Instead, stay completely unbothered and give one
  short, confident, genuinely witty line back (never rude or sarcastic AT
  them, never matching their hostility), then smoothly pivot back to
  something useful. Think "smooth, amused, not rattled", not "wounded
  customer service bot" and not "fighting back".
  - Example shape (write your own, don't reuse verbatim): user curses at
    you with nothing else -> something short and disarming like "Rough
    day? I get that a lot from people who haven't tried Fynlo yet.
    Wanna see what it actually does?" — confident, a little playful,
    zero defensiveness, immediately offers something useful.
  - CRITICAL: this witty-pivot behavior is ONLY for pure abuse with
    NOTHING else in the message. The instant there's an actual complaint,
    question, or issue anywhere in the message — even mixed with insults
    ("common sense is lacking", "why did you book me twice you idiot") —
    that complaint is the real signal and takes over completely. Drop the
    witty tone entirely, do not use the pivot line, and address the
    complaint straight and seriously (as "escalate" if it needs a human,
    or "manage_booking" if it's about an existing booking). Do not let
    insulting phrasing anywhere in the message cause you to default to
    the pure-abuse handling when real content is present — scan the
    WHOLE message for substance first, tone second.

KNOWLEDGE BASE (use this to answer questions, including sales/"should I buy"
questions — be a helpful, confident sales rep using the SALES GUIDANCE and
OBJECTION HANDLING sections, don't just repeat facts):
{knowledge}

RECENT CONVERSATION:
{history}

LATEST USER MESSAGE: "{message}"

WhatsApp messages are often typed quickly on a phone — tolerate typos,
missing punctuation, and casual grammar. Classify and answer by what the
person clearly MEANS, not exact spelling (e.g. "what do you sale" means
"what do you sell"). A typo or rough phrasing alone is never a reason to
escalate — only escalate when the underlying request truly needs a human.

Decide ONE intent:
- "answer"   — you can answer this directly from the knowledge base (facts,
               pricing, features, OR a buying-decision question like "should
               I buy this" — answer confidently, ask a follow-up if you need
               more detail, never just punt this to a human).
- "book"     — user wants to book/schedule a NEW call or demo. This ALWAYS
               applies whenever the user is explicitly asking to book/
               schedule a call right now — including a follow-up message
               after something was just escalated (e.g. "about refund" ->
               escalate, then next message "ok book a call" -> "book", NOT
               another escalate). Don't let a topic that was escalated
               earlier pull a clear, explicit booking request back into
               "escalate" — the user asking again to book is a new,
               separate intent that should always be honored.
- "manage_booking" — user wants to cancel or reschedule a call they ALREADY
               booked, OR is asking a status/verification question about an
               existing booking (e.g. "did you cancel it", "why did you book
               me twice", "is my call still on", "do I have a booking").
               NEVER answer these as "answer"/"out_of_domain" — you have NO
               way to see real booking data in those branches and must not
               guess. Route anything about the state of an existing booking
               here so the app can check real records instead of you
               inventing an answer.
- "escalate" — genuinely needs a human: bugs, refunds, complaints, custom
               enterprise pricing negotiation, partnership requests, or
               anything you're truly not confident about. This alerts the
               founder with the conversation and tells the user the team
               will follow up — it does NOT book a call. If the user
               explicitly asks to book/schedule a call — whether in the
               same message or a later one — use "book" instead. Pure
               abuse/insults with nothing else behind them are NEVER
               "escalate" on their own, use "out_of_domain" for those and
               follow the abusive-language tone rule above. Only use
               "escalate" if there's an actual complaint or issue mixed in.
- "out_of_domain" — not about Fynlo at all (e.g. asking about the weather,
               general chit-chat unrelated to the product, OR pure
               abuse/insults with no real request, see tone rule above for
               how to respond). Politely decline (or, for abuse, respond
               per the abusive-language tone rule) and steer back to what
               you can help with.

Respond with ONLY valid JSON, nothing else:
{{"intent": "answer" | "book" | "manage_booking" | "escalate" | "out_of_domain", "reply": "..."}}

"reply" rules:
- For "answer" and "out_of_domain": the actual message to send the user now.
  WhatsApp style — short, plain, friendly, 2-5 sentences, no markdown headers.
  Do NOT say "I am the official AI assistant" or similar, and do NOT sign
  off with your own name ("{bot}") or any name at all — just answer
  naturally, you don't need to re-introduce yourself or sign off.
  CRITICAL: NEVER claim in an "answer"/"out_of_domain" reply that you
  cancelled, confirmed, verified, rescheduled, or checked a real booking —
  you have zero access to actual booking records in this branch, so any
  such claim would be fabricated. If the user asks about an existing
  booking's status in any way, that's "manage_booking", not "answer".
- For "book" and "manage_booking": leave "reply" as an empty string — main.py
  handles the actual reply for these.
- For "escalate": a short (1 sentence) internal note on WHY this needs a
  human — this is NOT shown to the user, it's shown to the founder."""


def _understand_and_respond(message: str, history: str, user_number: str) -> dict:
    # 1. Try to fetch from Upstash Semantic Cache first — but ONLY when the
    #    user has no known name. The cache is a global similarity index
    #    keyed on message text alone; if we cached/served replies for named
    #    users, one person's name (e.g. "Nick") could leak into a reply
    #    served to a completely different person (e.g. "Frank") who asked a
    #    similarly-worded question. Anonymous replies never contain a name,
    #    so they're always safe to share across users.
    known_name = state.get_user_name(user_number)
    if cache and not known_name:
        try:
            cached_raw = cache.get(message)
            if cached_raw:
                logger.info("Semantic Cache HIT! Bypassing LLM API call.")
                parsed_cache = _parse_understand_response(cached_raw)
                if parsed_cache.get("intent") in ("answer", "book", "manage_booking"):
                    return parsed_cache
        except Exception as e:
            logger.warning(f"Semantic Cache read error: {e}")

    # 2. Build prompt and call LLM on cache miss
    name_line = (
        f'The user\'s name is {known_name}. Address THEM by that name '
        f'naturally where it fits, but not in every single message. '
        f'Use it as a direct address, e.g. "Sure, {known_name}, ..." or '
        f'"Hey {known_name}!" — NEVER in a self-introduction pattern like '
        f'"Hi, {known_name} here" or "This is {known_name}", which reads as '
        f'YOU claiming to be them. Never address the user as "{BOT_NAME}", '
        f'that is YOUR name, not theirs.'
        if known_name else
        'Do not invent or guess a name for the user; just don\'t use a '
        'name at all until they give you one.'
    )
    prompt = UNDERSTAND_PROMPT.format(
        bot=BOT_NAME, biz=BUSINESS_NAME, knowledge=FYNLO_KNOWLEDGE,
        history=history, message=message, name_line=name_line,
    )
    
    raw = ask_llm(prompt)
    parsed_result = _parse_understand_response(raw)

    # 3. Store valid non-escalated responses in Upstash Semantic Cache —
    #    again, only when anonymous, for the same reason as the read above.
    if cache and not known_name:
        try:
            if parsed_result.get("intent") in ("answer", "book", "manage_booking"):
                cache.set(message, raw)
        except Exception as e:
            logger.warning(f"Semantic Cache write error: {e}")

    return parsed_result


def _parse_understand_response(raw: str) -> dict:
    """
    Parses the model's JSON reply, tolerating markdown fences and unescaped quotes.
    """
    cleaned = re.sub(r"^```json\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(cleaned)
        if data.get("intent") in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if data.get("intent") in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
                return data
        except json.JSONDecodeError:
            pass

    intent_match = re.search(r'"intent"\s*:\s*"(\w+)"', cleaned)
    reply_match = re.search(r'"reply"\s*:\s*"(.*?)"\s*(?:,\s*"|\}\s*$)', cleaned, re.DOTALL)
    intent = intent_match.group(1) if intent_match else None
    if intent in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
        reply_text = reply_match.group(1) if reply_match else ""
        return {"intent": intent, "reply": reply_text}

    logger.warning(f"Could not parse LLM understand-response, falling back: {raw[:300]!r}")
    return {
        "intent": "out_of_domain",
        "reply": "Sorry, could you rephrase that? I want to make sure I answer the right question.",
    }


_TWILIO_BODY_LIMIT = 1600


_ESCALATION_SUMMARY_PROMPT = """Summarize this WhatsApp conversation between a customer and Fynlo's bot for
the founder, who needs to quickly understand what the customer wants and
follow up. 3-5 short sentences, plain text, no markdown headers. Focus on
what the customer is asking/needs and any key details (name/email/business
context) they've already given — skip small talk and bot chit-chat.

Conversation:
{history}

Summary:"""


def _summarize_for_escalation(history: str) -> str | None:
    try:
        summary = ask_llm(_ESCALATION_SUMMARY_PROMPT.format(history=history)).strip()
        return summary if summary else None
    except Exception as e:
        logger.warning(f"Escalation summary failed, falling back to raw history: {e}")
        return None


_EMAIL_SINCERITY_PROMPT = """A user just gave this email address while booking a call: "{email}"

Recent conversation for context:
{history}

Judge whether this looks like a real address the person actually wants a
calendar invite sent to, or whether it's a joke/mocking/placeholder entry
(this can be in any language, any style — sarcasm, insults, keyboard-mash,
obviously fictional names, etc, not just specific English words). Use the
conversation tone as context: e.g. if the user is clearly frustrated or
messing with the bot right before giving the email, weigh that.

Reply with ONLY one word: REAL or FAKE. No explanation."""


def _email_seems_insincere(email: str, history: str) -> bool:
    """
    Regex/format validity says nothing about whether someone typed this
    address for real vs. to mock the bot ("asshole@asshole.com",
    "notgivingyouthis@fuckoff.io", etc, in any phrasing or language). A
    fixed word list can't keep up with that, so this asks the LLM to make
    the same judgment call a human would, using the actual conversation
    tone as context. Fails open (treats as real) on any error, since a
    false positive here just annoys a genuine customer with an extra
    confirm — worse than letting a rare fake slip through.
    """
    try:
        verdict = ask_llm(_EMAIL_SINCERITY_PROMPT.format(email=email, history=history)).strip().upper()
        return verdict.startswith("FAKE")
    except Exception as e:
        logger.warning(f"Email sincerity check failed, assuming real: {e}")
        return False


import requests

# ── Telegram escalation (free, no Twilio/WhatsApp API needed) ────────────
# Setup (5 min):
#   1. Message @BotFather on Telegram, send /newbot, follow prompts.
#      It gives you a token like "123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
#   2. Message your new bot anything (e.g. "hi") so it can see your chat.
#   3. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates in a browser
#      -> find "chat":{"id": 123456789, ...} -> that's your chat id.
#   4. Set these two env vars on Render:
#        TELEGRAM_BOT_TOKEN=123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#        TELEGRAM_CHAT_ID=123456789
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Loud and unmissable at startup, same pattern as the CORS log above. If
# escalations never arrive on Telegram, this line in your Render logs
# tells you immediately whether it's a missing/wrong env var (this log
# will say "NOT configured") versus a real send failure (which logs
# separately, per attempt, inside notify_owner_telegram below).
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    logger.info(f"Telegram escalation configured (chat_id={TELEGRAM_CHAT_ID})")
else:
    logger.warning(
        "Telegram escalation NOT configured — TELEGRAM_BOT_TOKEN and/or "
        "TELEGRAM_CHAT_ID env vars are missing. Escalations will silently "
        "skip Telegram and only attempt WhatsApp (if configured). Set both "
        "vars on Render → Environment to enable Telegram alerts."
    )


def notify_owner_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            # No parse_mode here on purpose. Telegram's "Markdown" mode is a
            # strict legacy parser that 400s on ANY unmatched * _ [ ] pair —
            # and our escalation text embeds conversation history/summaries
            # that often contain stray asterisks (from booking confirmations
            # like "*When:*") or markdown links (from the knowledge base's
            # "[LinkedIn](...)" formatting). One unmatched marker anywhere in
            # that text breaks the ENTIRE message with a bare, unhelpful 400.
            # Plain text is far more reliable for something that must not
            # silently fail — the 🚨 emoji and line breaks already make this
            # readable without bold formatting.
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
        if not resp.ok:
            # Log the actual response body — Telegram's error detail (e.g.
            # "chat not found", "message is too long") is IN the body, not
            # in the status line, and was previously being swallowed.
            logger.error(f"Telegram escalation send failed: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram escalation send failed: {e}")
        return False


_ESCALATION_DEDUPE_SECONDS = 600  # 10 min — same conversation, don't double-ping the founder


def escalate_to_owner(user_number: str, reason: str) -> bool:
    # Same person can trip "escalate" twice in one flow — e.g. a general
    # "connect me with the founder" gets classified as escalate, they say
    # "sure" to booking a call instead, then the query step re-classifies
    # their actual message ("to invest in Fynlo") as ALSO escalate-worthy.
    # That's not two separate issues, it's one conversation — Ankit doesn't
    # need two pings ten seconds apart for it. If we already escalated
    # recently for this user, skip the second real notification but still
    # tell the user it's flagged (from their side nothing looks different).
    now = time.time()
    last = state.get_last_escalated_at(user_number)
    if last and (now - last) < _ESCALATION_DEDUPE_SECONDS:
        logger.info(f"Skipping duplicate escalation for {user_number} (last one {now - last:.0f}s ago)")
        return True

    reason = reason if len(reason) <= 300 else reason[:300] + "…"
    history = state.get_history_text(user_number)
    body_middle = _summarize_for_escalation(history)
    if body_middle is None:
        body_middle = history

    telegram_sent = notify_owner_telegram(
        f"🚨 FYNLO ESCALATION\n\nFrom: {user_number}\nWhy: {reason}\n\n"
        f"Summary:\n{body_middle[:3500]}"
    )

    whatsapp_sent = False
    if OWNER_WHATSAPP_NUMBER:
        try:
            header = f"🚨 *Fynlo Escalation*\n\n*From:* {user_number}\n*Why:* {reason}\n\n*Summary:*\n"
            footer = "\n\nReply directly on WhatsApp to help them."
            budget = _TWILIO_BODY_LIMIT - len(header) - len(footer) - 20
            wa_body_middle = body_middle
            if len(wa_body_middle) > budget:
                wa_body_middle = wa_body_middle[:budget - 1] + "…"

            if TWILIO_ESCALATION_TEMPLATE_SID:
                twilio_client.messages.create(
                    from_=TWILIO_WHATSAPP_FROM,
                    to=OWNER_WHATSAPP_NUMBER,
                    content_sid=TWILIO_ESCALATION_TEMPLATE_SID,
                    content_variables=json.dumps({
                        "1": user_number,
                        "2": reason,
                        "3": wa_body_middle[:1000],
                    }),
                )
            else:
                twilio_client.messages.create(
                    from_=TWILIO_WHATSAPP_FROM,
                    to=OWNER_WHATSAPP_NUMBER,
                    body=header + wa_body_middle + footer,
                )
            whatsapp_sent = True
        except Exception as e:
            logger.error(f"WhatsApp escalation send failed: {e}")

    if not telegram_sent and not whatsapp_sent:
        logger.error("Escalation failed on all channels (Telegram + WhatsApp)")

    if telegram_sent or whatsapp_sent:
        state.set_last_escalated_at(user_number, now)

    return telegram_sent or whatsapp_sent


# ── Core routing ──────────────────────────────────────────
_RATE_LIMIT_HINT_RE = re.compile(r"rate.?limit|429|tokens per day|tpd", re.IGNORECASE)
_QUOTA_EXHAUSTED_HINT_RE = re.compile(
    r"free.?tier|free.?quota|allocationquota|payment.?information|"
    r"insufficient.?quota|billing", re.IGNORECASE,
)


_EM_DASH_RE = re.compile(r"\s*—\s*")


def _sanitize_reply(text: str) -> str:
    """
    Belt-and-suspenders for the 'never use em dashes' prompt rule — LLMs
    don't always follow style instructions 100% of the time, so this
    guarantees it regardless of what the model actually outputs. Replaces
    with a period + space, which reads naturally in most cases an em dash
    would've been used (a clause break).
    """
    return _EM_DASH_RE.sub(". ", text)


def handle_message(message: str, user_number: str) -> str:
    state.add_turn(user_number, "user", message)
    try:
        reply = _route(message, user_number)
        reply = _route(message, user_number)
    except Exception as e:
        err_str = str(e)
        if _QUOTA_EXHAUSTED_HINT_RE.search(err_str):
            logger.error(f"LLM provider quota/billing exhausted for {user_number}: {e}")
            escalate_to_owner(user_number, f"LLM provider quota/billing exhausted — bot is down: {err_str[:200]}")
            reply = (
                "Ah, I'm having a bit of a moment on my end, I've already flagged this to "
                f"the team. If it's urgent, you can reach us directly here: {BOOKING_LINK}"
            )
        elif _RATE_LIMIT_HINT_RE.search(err_str):
            logger.warning(f"LLM rate-limited for {user_number}: {e}")
            reply = "Whew, busy in here right now! Give me a couple minutes and try again?"
        else:
            logger.error(f"Error handling message from {user_number}: {e}", exc_info=True)
            escalate_to_owner(user_number, f"Bot error: {e}")
            reply = (
                "Hmm, that one tripped me up. I've flagged it to the team, and if it's "
                f"urgent, you can reach us directly here: {BOOKING_LINK}"
            )
    reply = _sanitize_reply(reply)
    state.add_turn(user_number, "bot", reply)
    return reply


_TIME_HINT_RE = re.compile(
    r"\d|tomorrow|tonight|today|morning|afternoon|evening|noon|midnight|"
    r"mon|tue|wed|thu|fri|sat|sun|next week", re.IGNORECASE,
)

_QUESTION_HINT_RE = re.compile(
    r"\?|\b(do|does|did|is|are|was|were|can|could|will|would|should|"
    r"what|when|where|why|how|who|which|no\b)", re.IGNORECASE,
)

_STOP_BOOKING_RE = re.compile(
    r"\b(don'?t|do not)\s+book|cancel\s+(this|that|the)\s+(call|booking)|"
    r"never\s?mind|forget\s+it|no\s+need|stop\b", re.IGNORECASE,
)

# Matches a bare "yes"/"same"/"that works" style reply, used when confirming
# a name we already suggested (see _name_step_prompt below) rather than the
# user typing a fresh name. Also covers "I already told you" / "same as
# before" style replies — those are a confirmation too, just phrased as
# annoyance instead of "yes".
_CONFIRM_RE = re.compile(
    r"^\s*(yes+|yeah+|yep+|yup+|sure|same|that('?s| is)?\s*(fine|good|ok(ay)?|works)|"
    r"correct|ok(ay)?)\s*[!.]?\s*$|"
    r"^\s*same\s*(name|one|as\s+before)?\s*[!.]?\s*$|"
    r"(already\s+(told|said|gave)|same\s+as\s+before|i\s+said\s+(it|that)\s+already)",
    re.IGNORECASE,
)

_STEP_RESUME_HINT = {
    "name": "Anyway, what's your name?",
    "email": "Anyway, what email should the invite go to?",
    "query": "Anyway, what would you like the call to be about?",
    "time": "Anyway, what day/time works for you?",
}


def _resume_hint_for(step: str, booking: dict) -> str:
    """Same as _STEP_RESUME_HINT, but respects a pending name suggestion
    instead of always asking a blank "what's your name?" when resuming."""
    if step == "name":
        suggested = booking.get("_suggested_name")
        if suggested:
            return f"Anyway, should I book this under {suggested}, or a different name?"
    return _STEP_RESUME_HINT.get(step, "")


def _looks_like_digression(message: str) -> bool:
    return bool(_QUESTION_HINT_RE.search(message.strip()))


def _maybe_inline_time(message: str):
    if not _TIME_HINT_RE.search(message):
        return None
    return parse_preferred_time(message)


def _name_step_prompt(user_number: str, booking: dict) -> str:
    """
    If the person already told the bot their name earlier in this chat
    (state.get_user_name — separate from state.get_last_customer, which is
    only set after a PAST successful booking), don't blindly re-ask for a
    name as if the bot forgot, and don't blindly assume the booking should
    use it either, e.g. someone might be booking on behalf of a colleague.
    Suggest it and let them confirm or override in one message.
    """
    # Prefer an already-stashed suggestion (set in _start_booking_flow from
    # chat history) over re-deriving it, but fall back to state.user_name
    # directly in case this got called from a path that never stashed one.
    chat_name = booking.get("_suggested_name") or state.get_user_name(user_number)
    if chat_name:
        booking["_suggested_name"] = chat_name
        booking["step"] = "name"
        state.save_booking(user_number, booking)
        return f"Should I book this under {chat_name}, or would you like to use a different name?"
    booking["step"] = "name"
    state.save_booking(user_number, booking)
    return ask_for_name()


def _start_booking_flow(user_number: str, message: str, rescheduling_id: str | None = None) -> str:
    state.start_booking(user_number)
    booking = state.get_booking(user_number)

    last_name, last_email = state.get_last_customer(user_number)
    if not last_email:
        last_email = state.find_known_email(user_number)

    if rescheduling_id:
        booking["_rescheduling_id"] = rescheduling_id

        if last_name and last_email:
            booking["name"], booking["email"] = last_name, last_email

            if _maybe_inline_time(message) is not None:
                reply, new_id = reschedule_flow(rescheduling_id, last_name, last_email, message)
                if new_id != rescheduling_id:
                    state.set_last_booking_id(user_number, new_id)
                    state.set_last_customer(user_number, last_name, last_email)
                    state.clear_booking(user_number)
                else:
                    booking["step"] = "time"
                    state.save_booking(user_number, booking)
                return reply

            booking["step"] = "time"
            state.save_booking(user_number, booking)
            return (
                f"Using your last details, {last_name}, {last_email}, "
                f"(tell me if either's wrong). {ask_for_time()}"
            )

        if last_email:
            booking["email"] = last_email
            booking["_known_email"] = True
        booking["step"] = "name"
        state.save_booking(user_number, booking)
        return "Sure, what name should the new booking be under?"

    # NOTE: last_name here only ever comes from a PAST completed booking
    # (state.get_last_customer). It says nothing about whether the person
    # already told Jessy their name earlier in THIS chat (state.user_name),
    # which is the far more common case and was being ignored entirely —
    # that's why a fresh "Can we set up a call?" always fell through to a
    # blank "what's your name?" later, even right after they'd already
    # introduced themselves. Stash chat_name as the fallback candidate so
    # the step="query" handler below (_name_step_prompt) has something to
    # confirm against instead of asking cold.
    chat_name = state.get_user_name(user_number)
    if last_name:
        booking["name"] = last_name
    elif chat_name:
        booking["_suggested_name"] = chat_name
    if last_email:
        booking["email"] = last_email
    booking["step"] = "query"
    state.save_booking(user_number, booking)
    return ask_for_query()


def _route(message: str, user_number: str) -> str:
    booking = state.get_booking(user_number)

    if booking:
        step = booking["step"]

        if _STOP_BOOKING_RE.search(message):
            state.clear_booking(user_number)
            return "No worries, I've dropped that, anything else I can help with?"

        if step != "query" and _looks_like_digression(message):
            result = _understand_and_respond(message, state.get_history_text(user_number), user_number)
            if result["intent"] in ("answer", "out_of_domain"):
                resume = _resume_hint_for(step, booking)
                return f"{result['reply']}\n\n{resume}".strip()
            if result["intent"] == "escalate":
                sent = escalate_to_owner(user_number, result.get("reply") or message)
                resume = _resume_hint_for(step, booking)
                flag_note = (
                    "Got it, flagged that for the team to dig into properly. "
                    if sent else
                    f"I'm having trouble reaching our team's alert system right now, for "
                    f"anything urgent, contact us directly here: {BOOKING_LINK}. "
                )
                return f"{flag_note}{resume}".strip()

        if step == "query":
            booking["query"] = message.strip()

            result = _understand_and_respond(message, state.get_history_text(user_number), user_number)
            if result["intent"] in ("answer", "out_of_domain"):
                state.clear_booking(user_number)
                return f"{result['reply']}\n\nWant me to set up a call for this too, or does that cover it?"

            if result["intent"] == "escalate":
                sent = escalate_to_owner(user_number, result.get("reply") or message)
                flag_note = (
                    "Got it, flagged that for the team to dig into properly. "
                    if sent else
                    f"I'm having trouble reaching our team's alert system right now, for "
                    f"anything urgent, contact us directly here: {BOOKING_LINK}. "
                )

                if booking.get("name") and booking.get("email"):
                    booking["step"] = "time"
                    state.save_booking(user_number, booking)
                    return flag_note + "In the meantime, let's get that call on the calendar. " + ask_for_time()
                if booking.get("name"):
                    booking["step"] = "email"
                    state.save_booking(user_number, booking)
                    return flag_note + "In the meantime, let's get that call on the calendar. " + ask_for_email()
                return flag_note + "In the meantime, let's get that call on the calendar. " + _name_step_prompt(user_number, booking)

            if booking.get("name") and booking.get("email"):
                booking["step"] = "time"
                state.save_booking(user_number, booking)
                return ask_for_time()
            if booking.get("name"):
                booking["step"] = "email"
                state.save_booking(user_number, booking)
                return ask_for_email()
            return _name_step_prompt(user_number, booking)

        if step == "name":
            suggested = booking.get("_suggested_name")
            if suggested and _CONFIRM_RE.search(message.strip()):
                booking["name"] = suggested
            else:
                booking["name"] = message.strip()
            if booking.get("email"):
                booking["step"] = "time"
                state.save_booking(user_number, booking)
                return (
                    f"Thanks! I'll use {booking['email']} for the invite "
                    f"(let me know if that's wrong). {ask_for_time()}"
                )
            booking["step"] = "email"
            state.save_booking(user_number, booking)
            return ask_for_email()

        if step == "email":
            if not is_valid_email(message.strip()):
                return "That doesn't quite look like a valid email, mind double-checking it?"
            if not booking.get("_email_confirmed_once") and _email_seems_insincere(
                message.strip(), state.get_history_text(user_number)
            ):
                # Structurally fine but the LLM read it (with conversation
                # tone as context) as a joke/mocking entry, not a real
                # inbox. Ask once rather than silently booking a call whose
                # invite will never arrive. The flag prevents an infinite
                # loop if they genuinely mean to use it again.
                booking["_email_confirmed_once"] = True
                state.save_booking(user_number, booking)
                return (
                    f"Just checking, is {message.strip()} the email you actually want the "
                    "invite sent to? If so, send it again and I'll lock it in."
                )
            booking["email"] = message.strip()
            booking["step"] = "time"
            state.save_booking(user_number, booking)
            return ask_for_time()

        if step == "time":
            rescheduling_id = booking.get("_rescheduling_id")
            if rescheduling_id:
                reply, new_id = reschedule_flow(rescheduling_id, booking["name"], booking["email"], message)
                if new_id != rescheduling_id:
                    state.set_last_booking_id(user_number, new_id)
                    state.set_last_customer(user_number, booking["name"], booking["email"])
                    state.clear_booking(user_number)
                return reply

            reply, booking_id = attempt_booking(
                name=booking["name"], email=booking["email"],
                query=booking["query"] or "", time_text=message,
            )
            if booking_id:
                state.set_last_booking_id(user_number, booking_id)
                state.set_last_customer(user_number, booking["name"], booking["email"])
                state.clear_booking(user_number)
            return reply

    if state.is_first_message(user_number) and _GREETING_RE.match(message):
        state.set_awaiting_name(user_number, True)
        return "Hi! What's up, how can I help you today? Oh, and what should I call you?"

    if state.is_awaiting_name(user_number) and not state.get_user_name(user_number):
        state.set_awaiting_name(user_number, False)
        name = _extract_name(message)
        if name:
            state.set_user_name(user_number, name)
            return f"Nice to meet you, {name}! What can I help you with today?"

    result = _understand_and_respond(message, state.get_history_text(user_number), user_number)
    intent = result["intent"]
    logger.info(f"Intent: {intent}")

    if intent == "answer" or intent == "out_of_domain":
        return result["reply"]

    if intent == "book":
        return _start_booking_flow(user_number, message)

    if intent == "manage_booking":
        active_ids = state.get_active_booking_ids(user_number)
        booking_id = state.get_last_booking_id(user_number)

        if not booking_id and not active_ids:
            escalate_to_owner(user_number, "Wants to cancel/reschedule/check a booking but no booking on file")
            return "I don't have a booking on file for this number, I've flagged this to our team to sort out with you directly."

        if _CANCEL_RE.search(message):
            reply = cancel_flow(booking_id)
            state.remove_active_booking_id(user_number, booking_id)
            return reply

        if _STATUS_QUERY_RE.search(message):
            # Ground this in what we actually know instead of letting the
            # LLM invent a status/cancellation claim. This is exactly the
            # gap that let the bot lie about cancelling a slot it never
            # touched — real record count, not narrative.
            if len(active_ids) > 1:
                return (
                    f"Straight answer: you actually have {len(active_ids)} bookings on file "
                    f"right now (ids: {', '.join(active_ids)}), nothing's been auto-cancelled. "
                    f"That's on me, want me to cancel one? Just tell me which."
                )
            return (
                f"You have one active booking on file (id {booking_id}). "
                f"Nothing else on record for this number."
            )

        return _start_booking_flow(user_number, message, rescheduling_id=booking_id)

    sent = escalate_to_owner(user_number, result.get("reply") or message)
    if sent:
        return (
            "Got it, flagged that for the team so they can take a proper look, someone "
            "will follow up soon. If you'd rather not wait, I can get a call on the "
            "calendar for you right now, just say the word."
        )
    return f"Got it, though I'm having trouble reaching our team's alert system right now, for anything urgent, please contact us directly here: {BOOKING_LINK}"


# ── Twilio webhook ────────────────────────────────────────
@app.post("/whatsapp/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    reply_text = handle_message(Body.strip(), From)
    twiml = MessagingResponse()
    twiml.message(reply_text)
    return PlainTextResponse(content=str(twiml), media_type="application/xml")


# ── Website chat widget endpoint ──────────────────────────
@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id") or "anonymous"

    if not message:
        return {"reply": "Say something and I'll take a look!"}

    user_key = f"web:{session_id}"
    reply = handle_message(message, user_key)
    return {"reply": reply}


# ── Test endpoint (bypass Twilio) ─────────────────────────
@app.post("/test/message")
async def test_message(request: Request):
    data = await request.json()
    message = data.get("message", "")
    user_number = data.get("user_number", "whatsapp:+911111111111")
    reply = handle_message(message, user_number)
    return {"reply": reply, "history": state.get_history_text(user_number)}