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
# WHY ONE LLM CALL INSTEAD OF SEPARATE CLASSIFIER + FAQ +
# SALES FILES: for an MVP, understanding the message and
# answering it are the same piece of reasoning — splitting them
# into multiple LLM calls just means more API calls, more
# places to debug, and more chances for the pieces to disagree
# with each other. One prompt, one JSON response, done.
#
# BOOKING is the one part that's genuinely multi-step (need
# name, email, what it's about, then a time, then hit the real
# calendar) — that stays a small state machine in `state.py`.
#
# Run locally:
#   uvicorn main:app --reload --port 8001
#   ngrok http 8001
# ---------------------------------------------------------

import json
import logging
import re

from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from config import (
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM,
    OWNER_WHATSAPP_NUMBER, BUSINESS_NAME, BOT_NAME, BOOKING_LINK,
    TWILIO_ESCALATION_TEMPLATE_SID,
)
from knowledge_base import FYNLO_KNOWLEDGE
from llm import ask_llm
from booking import ask_for_name, ask_for_email, ask_for_query, ask_for_time, is_valid_email, attempt_booking, cancel_flow, reschedule_flow
from time_parser import parse_preferred_time
import state

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Fynlo WhatsApp Bot (MVP)")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

_GREETING_RE = re.compile(r"^\s*(hi+|hello+|hey+|yo|sup|good\s*(morning|afternoon|evening)|namaste|hola)\s*[!.?]*\s*$", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\b(cancel|scrap|drop)\b", re.IGNORECASE)


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
- If the user shared their OWN name earlier in the conversation, address
  THEM by that name naturally when it fits. Never address the user as
  "{bot}" — that is YOUR name, not theirs. Do not invent or guess a name
  for the user if they haven't given one; just don't use a name at all in
  that case.

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
- "manage_booking" — user wants to cancel or reschedule a call they ALREADY booked.
- "escalate" — genuinely needs a human: bugs, refunds, complaints, custom
               enterprise pricing negotiation, partnership requests, or
               anything you're truly not confident about. This alerts the
               founder with the conversation and tells the user the team
               will follow up — it does NOT book a call. If the user
               explicitly asks to book/schedule a call — whether in the
               same message or a later one — use "book" instead.
- "out_of_domain" — not about Fynlo at all (e.g. asking about the weather,
               general chit-chat unrelated to the product). Politely decline
               and steer back to what you can help with.

Respond with ONLY valid JSON, nothing else:
{{"intent": "answer" | "book" | "manage_booking" | "escalate" | "out_of_domain", "reply": "..."}}

"reply" rules:
- For "answer" and "out_of_domain": the actual message to send the user now.
  WhatsApp style — short, plain, friendly, 2-5 sentences, no markdown headers.
  Do NOT say "I am the official AI assistant" or similar, and do NOT sign
  off with your own name ("{bot}") or any name at all — just answer
  naturally, you don't need to re-introduce yourself or sign off.
- For "book" and "manage_booking": leave "reply" as an empty string — main.py
  handles the actual reply for these.
- For "escalate": a short (1 sentence) internal note on WHY this needs a
  human — this is NOT shown to the user, it's shown to the founder."""


def _understand_and_respond(message: str, history: str) -> dict:
    prompt = UNDERSTAND_PROMPT.format(
        bot=BOT_NAME, biz=BUSINESS_NAME, knowledge=FYNLO_KNOWLEDGE,
        history=history, message=message,
    )
    raw = ask_llm(prompt)
    return _parse_understand_response(raw)


def _parse_understand_response(raw: str) -> dict:
    """
    Parses the model's JSON reply, tolerating the common ways a text
    completion can drift from strict JSON (markdown fences, chatter before/
    after the object, an unescaped quote/newline inside "reply"). Only
    falls back to a generic decline if genuinely nothing usable can be
    salvaged — this avoids a harmless message like "can you sing" turning
    into a false "bot error" escalation to the owner over a formatting slip.
    """
    cleaned = re.sub(r"^```json\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(cleaned)
        if data.get("intent") in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
            return data
    except json.JSONDecodeError:
        pass

    # Fallback 1: the model likely added stray text around the JSON object —
    # grab the outermost {...} and retry.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if data.get("intent") in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
                return data
        except json.JSONDecodeError:
            pass

    # Fallback 2: pull out "intent" and "reply" with regex directly — handles
    # cases where an unescaped quote/newline inside "reply" broke strict
    # JSON parsing but the fields are still clearly there.
    intent_match = re.search(r'"intent"\s*:\s*"(\w+)"', cleaned)
    reply_match = re.search(r'"reply"\s*:\s*"(.*?)"\s*(?:,\s*"|\}\s*$)', cleaned, re.DOTALL)
    intent = intent_match.group(1) if intent_match else None
    if intent in ("answer", "book", "manage_booking", "escalate", "out_of_domain"):
        reply_text = reply_match.group(1) if reply_match else ""
        return {"intent": intent, "reply": reply_text}

    # Fallback 3: genuinely nothing usable — treat as an out-of-domain chat
    # message rather than throwing, so the user gets a normal reply instead
    # of the "I hit a snag" error and a false alarm to the owner.
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
    """Best-effort LLM summary for the escalation alert. Returns None on any
    failure so the caller can fall back to a raw trimmed transcript instead
    of losing the escalation entirely over a summarization hiccup."""
    try:
        summary = ask_llm(_ESCALATION_SUMMARY_PROMPT.format(history=history)).strip()
        return summary if summary else None
    except Exception as e:
        logger.warning(f"Escalation summary failed, falling back to raw history: {e}")
        return None


def escalate_to_owner(user_number: str, reason: str) -> bool:
    """
    Sends the founder a WhatsApp alert with context. Returns True if it
    actually sent.

    IMPORTANT: WhatsApp only allows FREEFORM business messages within a 24h
    window after the recipient last messaged you — outside that window,
    Twilio rejects the send with error 63016. Since the owner may not have
    texted the bot recently, freeform escalation alerts can silently fail.
    If TWILIO_ESCALATION_TEMPLATE_SID is set (an approved WhatsApp Message
    Template's Content SID), that's used instead — templates can be sent
    anytime, regardless of the 24h window, which is what business-initiated
    alerts like this actually need.
    """
    if not OWNER_WHATSAPP_NUMBER:
        logger.error("OWNER_WHATSAPP_NUMBER not set — can't escalate")
        return False
    try:
        reason = reason if len(reason) <= 300 else reason[:300] + "…"
        header = f"🚨 *Fynlo Escalation*\n\n*From:* {user_number}\n*Why:* {reason}\n\n*Summary:*\n"
        footer = "\n\nReply directly on WhatsApp to help them."
        budget = _TWILIO_BODY_LIMIT - len(header) - len(footer) - 20  # small safety margin

        history = state.get_history_text(user_number)
        body_middle = _summarize_for_escalation(history)

        if body_middle is None:
            # Fallback: raw history, trimmed from the OLDEST end first if it
            # doesn't fit, rather than cutting off wherever it lands.
            body_middle = history
            header = header.replace("*Summary:*", "*Conversation:*")
            if len(body_middle) > budget:
                body_middle = "...(earlier messages trimmed)...\n" + body_middle[-(budget - 40):]
        elif len(body_middle) > budget:
            # Summary itself somehow ran long — hard cap as a last resort.
            body_middle = body_middle[:budget - 1] + "…"

        if TWILIO_ESCALATION_TEMPLATE_SID:
            # Approved template path — works outside the 24h window. The
            # template must be pre-approved with matching variable slots
            # (e.g. {{1}}=from, {{2}}=why, {{3}}=summary) in Twilio's
            # Content Template Builder; adjust the variable keys below to
            # match however your specific template was defined.
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=OWNER_WHATSAPP_NUMBER,
                content_sid=TWILIO_ESCALATION_TEMPLATE_SID,
                content_variables=json.dumps({
                    "1": user_number,
                    "2": reason,
                    "3": body_middle[:1000],  # templates have their own (often tighter) limits
                }),
            )
        else:
            # Freeform fallback — only actually delivers if the owner has
            # messaged the bot within the last 24h (error 63016 otherwise).
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=OWNER_WHATSAPP_NUMBER,
                body=header + body_middle + footer,
            )
        return True
    except Exception as e:
        logger.error(f"Escalation send failed: {e}")
        return False


# ── Core routing ──────────────────────────────────────────
# Transient, self-resolving (retry later, no owner action needed):
_RATE_LIMIT_HINT_RE = re.compile(r"rate.?limit|429|tokens per day|tpd", re.IGNORECASE)
# Permanent until the owner adds billing/upgrades a plan — waiting doesn't
# fix this, so it needs a different message AND an owner heads-up:
_QUOTA_EXHAUSTED_HINT_RE = re.compile(
    r"free.?tier|free.?quota|allocationquota|payment.?information|"
    r"insufficient.?quota|billing", re.IGNORECASE,
)


def handle_message(message: str, user_number: str) -> str:
    state.add_turn(user_number, "user", message)
    try:
        reply = _route(message, user_number)
    except Exception as e:
        err_str = str(e)
        if _QUOTA_EXHAUSTED_HINT_RE.search(err_str):
            # Provider's free tier is exhausted / billing needed — this is
            # PERMANENT until someone adds payment info, not something that
            # resolves by waiting. Tell the user something honest (not "try
            # again shortly", which would be false), and make sure the owner
            # actually knows to go fix billing, since the bot is fully down
            # until they do.
            logger.error(f"LLM provider quota/billing exhausted for {user_number}: {e}")
            escalate_to_owner(user_number, f"LLM provider quota/billing exhausted — bot is down: {err_str[:200]}")
            reply = (
                "Sorry, I'm temporarily unable to answer questions — I've flagged this to our "
                f"team. For anything urgent, please contact us directly here: {BOOKING_LINK}"
            )
        elif _RATE_LIMIT_HINT_RE.search(err_str):
            # Provider-side rate-limit — expected & self-resolving, not a
            # real bug. Log it (so YOU notice quota is tight) but don't page
            # the owner over it every time, and give the user an honest,
            # less alarming message than "I hit a snag."
            logger.warning(f"LLM rate-limited for {user_number}: {e}")
            reply = "Sorry, I'm getting a lot of messages right now — mind trying again in a couple of minutes?"
        else:
            logger.error(f"Error handling message from {user_number}: {e}", exc_info=True)
            escalate_to_owner(user_number, f"Bot error: {e}")
            reply = (
                "Sorry, I hit a snag answering that. I've flagged it to our team — "
                f"for anything urgent, reach us directly here: {BOOKING_LINK}"
            )
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

_STEP_RESUME_HINT = {
    "name": "Anyway — what's your name?",
    "email": "Anyway — what email should the invite go to?",
    "query": "Anyway — what would you like the call to be about?",
    "time": "Anyway — what day/time works for you?",
}


def _looks_like_digression(message: str) -> bool:
    """
    Mid-booking, most steps (name/email/query) accept nearly any free text,
    so we only want to bail out to the reasoning LLM when the message looks
    like a genuine question/new topic rather than an attempted answer.
    "time" is the step where this matters most in practice (e.g. "do you
    sell apples" landing on a date parser instead of being answered), but
    any step can get derailed by a real question, so this check applies
    uniformly before we hand the message to the step-specific parser.
    """
    return bool(_QUESTION_HINT_RE.search(message.strip()))


def _maybe_inline_time(message: str):
    """
    Cheap pre-check before attempting to parse a time out of a message that
    triggered book/reschedule (e.g. "reschedule to friday after 2" already
    contains the new time — no reason to throw that away and ask again).
    Only bothers calling parse_preferred_time (which can fall back to an
    LLM call) if the message actually looks like it contains a time.
    """
    if not _TIME_HINT_RE.search(message):
        return None
    return parse_preferred_time(message)


def _start_booking_flow(user_number: str, message: str, rescheduling_id: str | None = None) -> str:
    """
    Starts a booking (fresh or reschedule), pre-filling name/email if we
    already have them from the customer's last successful booking — so a
    returning user doesn't get asked "what's your name/email" every single
    time, which is the whole point of remembering it in the first place.

    Fresh bookings (not reschedules) always ask "what's this about" FIRST,
    before any personal details — that way the query step (below, in
    _route) gets a chance to just answer the question directly instead of
    marching the user through name/email/time for something that didn't
    need a call at all. Reschedules skip the query step entirely (there's
    already a booking on file, nothing to "answer" instead of).
    """
    state.start_booking(user_number)
    booking = state.get_booking(user_number)

    last_name, last_email = state.get_last_customer(user_number)
    if not last_email:
        last_email = state.find_known_email(user_number)  # fallback: scan this conversation's history

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
                    booking["step"] = "time"  # slot busy / needs another attempt
                return reply

            booking["step"] = "time"
            return (
                f"Using your last details — {last_name}, {last_email} "
                f"(tell me if either's wrong). {ask_for_time()}"
            )

        if last_email:
            booking["email"] = last_email
            booking["_known_email"] = True
        booking["step"] = "name"
        return "Sure — what name should the new booking be under?"

    # ── Fresh booking: always ask what it's about first ──────
    if last_name:
        booking["name"] = last_name
    if last_email:
        booking["email"] = last_email
    booking["step"] = "query"
    return ask_for_query()


def _route(message: str, user_number: str) -> str:
    booking = state.get_booking(user_number)

    # ── Mid-booking-flow: collect fields step by step ────────
    if booking:
        step = booking["step"]

        # Explicit "stop/cancel this booking" always wins, cheaply, no LLM
        # call needed — e.g. "don't book a call", "never mind", "stop".
        if _STOP_BOOKING_RE.search(message):
            state.clear_booking(user_number)
            return "No worries, I've dropped that — anything else I can help with?"

        # Bail out to the reasoning LLM if this doesn't look like an answer
        # to the current step but a genuine question/new topic (e.g. "do
        # you sell apples" while we're waiting on a time). We still want to
        # resume the booking afterward, so only divert for intents that are
        # actually answerable/off-topic — "book"/"manage_booking" fall
        # through to normal step-processing since those are ambiguous
        # enough that treating the raw text as the step answer is still the
        # safer bet. "escalate" also breaks out, since something like a
        # refund complaint surfacing mid-flow shouldn't keep marching
        # toward name/email/time.
        if step != "query" and _looks_like_digression(message):
            result = _understand_and_respond(message, state.get_history_text(user_number))
            if result["intent"] in ("answer", "out_of_domain"):
                resume = _STEP_RESUME_HINT.get(step, "")
                return f"{result['reply']}\n\n{resume}".strip()
            if result["intent"] == "escalate":
                # Keep the booking alive — the user was already partway
                # through booking a call, no reason to drop that just
                # because something escalate-worthy came up along the way.
                sent = escalate_to_owner(user_number, result.get("reply") or message)
                resume = _STEP_RESUME_HINT.get(step, "")
                flag_note = (
                    "I've flagged this to our team so they can look into it properly. "
                    if sent else
                    f"I'm having trouble reaching our team's alert system right now — for "
                    f"anything urgent, contact us directly here: {BOOKING_LINK}. "
                )
                return f"{flag_note}{resume}".strip()

        if step == "query":
            state.update_booking(user_number, "query", message.strip())

            # Give the reasoning LLM a shot at just answering this before
            # committing to the full name/email/time booking flow — no
            # reason to book a call for something answerable from the
            # knowledge base.
            result = _understand_and_respond(message, state.get_history_text(user_number))
            if result["intent"] in ("answer", "out_of_domain"):
                state.clear_booking(user_number)
                return f"{result['reply']}\n\nWant me to set up a call for this too, or does that cover it?"

            if result["intent"] == "escalate":
                # The user's ORIGINAL intent here was to book a call — a
                # complex/escalate-worthy query doesn't change that. Flag it
                # to the owner (with the current conversation state) AND
                # keep moving toward getting the call actually booked,
                # instead of dropping the booking flow entirely.
                sent = escalate_to_owner(user_number, result.get("reply") or message)
                flag_note = (
                    "I've flagged this to our team so they can look into it properly. "
                    if sent else
                    f"I'm having trouble reaching our team's alert system right now — for "
                    f"anything urgent, contact us directly here: {BOOKING_LINK}. "
                )

                if booking.get("name") and booking.get("email"):
                    booking["step"] = "time"
                    return flag_note + "In the meantime, let's get that call on the calendar. " + ask_for_time()
                if booking.get("name"):
                    booking["step"] = "email"
                    return flag_note + "In the meantime, let's get that call on the calendar. " + ask_for_email()
                booking["step"] = "name"
                return flag_note + "In the meantime, let's get that call on the calendar. " + ask_for_name()

            if booking.get("name") and booking.get("email"):
                booking["step"] = "time"
                return ask_for_time()
            if booking.get("name"):
                booking["step"] = "email"
                return ask_for_email()
            booking["step"] = "name"
            return ask_for_name()

        if step == "name":
            state.update_booking(user_number, "name", message.strip())
            if booking.get("email"):
                booking["step"] = "time"
                return (
                    f"Thanks! I'll use {booking['email']} for the invite "
                    f"(let me know if that's wrong). {ask_for_time()}"
                )
            booking["step"] = "email"
            return ask_for_email()

        if step == "email":
            if not is_valid_email(message.strip()):
                return "That doesn't quite look like a valid email — mind double-checking it?"
            state.update_booking(user_number, "email", message.strip())
            booking["step"] = "time"
            return ask_for_time()

        if step == "time":
            rescheduling_id = booking.get("_rescheduling_id")
            if rescheduling_id:
                reply, new_id = reschedule_flow(rescheduling_id, booking["name"], booking["email"], message)
                if new_id != rescheduling_id:
                    state.set_last_booking_id(user_number, new_id)
                    state.set_last_customer(user_number, booking["name"], booking["email"])
                    state.clear_booking(user_number)
                # else: stay on "time" step, next message tried again
                return reply

            reply, booking_id = attempt_booking(
                name=booking["name"], email=booking["email"],
                query=booking["query"] or "", time_text=message,
            )
            if booking_id:
                state.set_last_booking_id(user_number, booking_id)
                state.set_last_customer(user_number, booking["name"], booking["email"])
                state.clear_booking(user_number)
            # else: stay on "time" step, next message tried again
            return reply

    # ── Pure greeting: instant, no LLM call — but ONLY if this is truly
    # the first message. Mid-conversation, a bare "yo"/"hey" is often
    # shorthand for "yeah" answering whatever the bot just asked, not a
    # fresh hello, so it needs the full-context LLM below instead.
    if state.is_first_message(user_number) and _GREETING_RE.match(message):
        return (
            f"Hey there! 👋 I'm {BOT_NAME}, from {BUSINESS_NAME}. I can answer questions "
            f"about pricing, features, integrations, or help you book a call. What can I help with?"
        )

    # ── Fresh message: one LLM call decides everything ───────
    result = _understand_and_respond(message, state.get_history_text(user_number))
    intent = result["intent"]
    logger.info(f"Intent: {intent}")

    if intent == "answer" or intent == "out_of_domain":
        return result["reply"]

    if intent == "book":
        return _start_booking_flow(user_number, message)

    if intent == "manage_booking":
        booking_id = state.get_last_booking_id(user_number)
        if not booking_id:
            escalate_to_owner(user_number, "Wants to cancel/reschedule but no booking on file")
            return "I don't have a booking on file for this number — I've flagged this to our team to sort out with you directly."

        if _CANCEL_RE.search(message):
            reply = cancel_flow(booking_id)
            state.set_last_booking_id(user_number, None)
            return reply

        return _start_booking_flow(user_number, message, rescheduling_id=booking_id)

    # intent == "escalate" — genuinely complex stuff (bugs, refunds, custom
    # enterprise terms, etc). Notify the owner with the full conversation,
    # let the user know the team will follow up, AND offer a call as a
    # faster path — if they take it, their next message naturally becomes
    # "book" per the prompt rules above.
    sent = escalate_to_owner(user_number, result.get("reply") or message)
    if sent:
        return (
            "Thanks for reaching out! This needs a closer look — I've flagged it to our "
            "team and someone will get back to you shortly. 🙏 If you'd rather not wait, "
            "I can also get a call on the calendar for you now — just say the word."
        )
    return f"Thanks for reaching out! I'm having trouble reaching our team's alert system right now — for anything urgent, please contact us directly here: {BOOKING_LINK}"


# ── Twilio webhook ────────────────────────────────────────
@app.post("/whatsapp/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    reply_text = handle_message(Body.strip(), From)
    twiml = MessagingResponse()
    twiml.message(reply_text)
    return PlainTextResponse(content=str(twiml), media_type="application/xml")


# ── Test endpoint (bypass Twilio) ─────────────────────────
@app.post("/test/message")
async def test_message(request: Request):
    data = await request.json()
    message = data.get("message", "")
    user_number = data.get("user_number", "whatsapp:+911111111111")
    reply = handle_message(message, user_number)
    return {"reply": reply, "history": state.get_history_text(user_number)}