# booking.py
# ---------------------------------------------------------
# Real booking, not just a link. Flow (driven by main.py,
# state tracked in conversation_state.py):
#
#   1. ask_for_name()
#   2. ask_for_email()
#   3. ask_for_query()      — what the call is about
#   4. ask_for_time()       — their preferred day/time
#   5. attempt_booking(...) — checks LIVE TidyCal availability:
#        - free  -> books it, returns the meeting link
#        - busy  -> offers other slots that same day, or the
#                   next few days if nothing's free that day
#
# Cancel/reschedule reuse the same "hit the real API" pattern
# via cancel_flow() / reschedule_flow(), keyed off the user's
# last confirmed booking (conversation_state.get_last_booking_uid).
#
# NOTE: TidyCal has no reschedule endpoint — reschedule_flow()
# cancels the old booking and creates a new one (see tidycal_api.py).
# ---------------------------------------------------------

import logging
import re
import zoneinfo
from datetime import datetime, timedelta

from tidycal_api import (
    is_slot_available,
    get_available_slots,
    create_booking,
    cancel_booking,
    reschedule_booking,
    TidyCalApiError,
)
from time_parser import parse_preferred_time
from config import TIDYCAL_TIMEZONE, BOOKING_LINK

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOCAL_TZ = zoneinfo.ZoneInfo(TIDYCAL_TIMEZONE)


# ── Step prompts ────────────────────────────────────────────
def ask_for_name() -> str:
    return "Happy to set that up! First, what's your name?"


def ask_for_email() -> str:
    return "Thanks! And what email should the calendar invite + meeting link go to?"


def ask_for_query() -> str:
    return (
        "Before I set up the call — what would you like help with? "
        "If it's something quick I might be able to answer it right here."
    )


def ask_for_time() -> str:
    return (
        "Perfect, last thing — what day/time works best for you? "
        "(e.g. \"tomorrow at 3pm\" or \"Friday morning\")"
    )


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


# ── Booking attempt ─────────────────────────────────────────
def attempt_booking(name: str, email: str, query: str, time_text: str) -> tuple[str, str | None]:
    """
    Tries to book the requested time against the real calendar.
    Returns (reply_text, booking_id_as_str). booking_id is None if
    nothing was actually booked yet — caller keeps waiting for
    another time from the user in that case.
    """
    requested_time = parse_preferred_time(time_text)

    if requested_time is None:
        return (
            "I couldn't quite figure out a date/time from that — could you try "
            "again, e.g. \"tomorrow 3pm\" or \"July 24th at 11am\"?",
            None,
        )

    try:
        if is_slot_available(requested_time):
            booking = create_booking(name=name, email=email, start_time=requested_time, notes=query)
            when = requested_time.astimezone(_LOCAL_TZ).strftime("%A, %d %b at %I:%M %p")
            return (
                f"You're booked, {name}! 🎉\n\n"
                f"*When:* {when} ({TIDYCAL_TIMEZONE})\n"
                f"*Meeting link:* {booking.get('meeting_url') or '(check your email for the link)'}\n\n"
                f"A calendar invite is on its way to {email}. Need to reschedule or cancel "
                f"later? Just tell me here.",
                str(booking.get("id")) if booking.get("id") is not None else None,
            )

        alt_message = _suggest_alternatives(requested_time)
        return (f"That exact time isn't free, unfortunately. {alt_message}", None)

    except TidyCalApiError as e:
        if str(e) == "slot_taken":
            # Someone else grabbed it between our check and the booking call
            alt_message = _suggest_alternatives(requested_time)
            return (f"Ah, that slot just got taken. {alt_message}", None)
        return (
            "I'm having trouble reaching the calendar system right now. Here's a direct "
            f"booking link you can use instead: {BOOKING_LINK}\n\n"
            "I've also flagged this to our team with your details.",
            None,
        )


def _suggest_alternatives(requested_time: datetime) -> str:
    day_start = requested_time.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        same_day_slots = get_available_slots(day_start, day_start + timedelta(days=1))
        if same_day_slots:
            # IMPORTANT: TidyCal returns slot times in UTC. Displaying them
            # with strftime() directly (without converting to the local
            # TIDYCAL_TIMEZONE first) shows the WRONG wall-clock time to the
            # user — e.g. a UTC 08:00 slot is actually 1:30 PM in
            # Asia/Kolkata, not 8:00 AM. That mismatch caused an infinite
            # "not free" loop: the user would reply with the literal time
            # shown (which matched nothing in local time), and this loop
            # would immediately show the same UTC-labelled list again.
            # Always convert to local tz here before formatting.
            local_slots = [s.astimezone(_LOCAL_TZ) for s in same_day_slots]
            times = ", ".join(s.strftime("%I:%M %p") for s in local_slots[:5])
            return f"Here's what's free that day instead: {times}. Any of these work?"

        window_slots = get_available_slots(day_start, day_start + timedelta(days=3))
        if window_slots:
            local_window_slots = [s.astimezone(_LOCAL_TZ) for s in window_slots]
            by_day: dict[str, list[str]] = {}
            for s in local_window_slots:
                by_day.setdefault(s.strftime("%A, %d %b"), []).append(s.strftime("%I:%M %p"))
            lines = [f"*{day}:* {', '.join(times[:4])}" for day, times in by_day.items()]
            return (
                "Here's what's open over the next few days:\n\n"
                + "\n".join(lines)
                + "\n\nLet me know which works, or share another day/time."
            )

        return "Nothing's open in the next few days — do you have another time frame in mind?"

    except TidyCalApiError:
        return (
            "I couldn't pull up alternative slots right now — you can pick a time "
            f"directly here instead: {BOOKING_LINK}"
        )


# ── Cancel / reschedule ──────────────────────────────────────
def cancel_flow(booking_id: str) -> str:
    try:
        cancel_booking(int(booking_id))
        return "Done — that booking's been cancelled. Want to grab a new time instead?"
    except TidyCalApiError:
        return (
            "I couldn't cancel that automatically — I've flagged it to our team "
            "to cancel manually on their end."
        )


def reschedule_flow(booking_id: str, name: str, email: str, time_text: str) -> tuple[str, str | None]:
    """
    Returns (reply_text, booking_id) — booking_id updated to the NEW booking's
    id if the reschedule succeeded (TidyCal has no reschedule endpoint, so
    this cancels the old one and books a fresh slot).
    """
    new_time = parse_preferred_time(time_text)
    if new_time is None:
        return (
            "Couldn't figure out a date/time from that — try something like \"next Monday 2pm\"?",
            booking_id,
        )

    try:
        if is_slot_available(new_time):
            booking = reschedule_booking(int(booking_id), name=name, email=email, new_start_time=new_time)
            when = new_time.astimezone(_LOCAL_TZ).strftime("%A, %d %b at %I:%M %p")
            new_id = str(booking.get("id")) if booking.get("id") is not None else booking_id
            return (
                f"Rescheduled! ✅\n\n*New time:* {when} ({TIDYCAL_TIMEZONE})\n"
                f"*Meeting link:* {booking.get('meeting_url') or '(check your email)'}",
                new_id,
            )

        alt_message = _suggest_alternatives(new_time)
        return (f"That time isn't free either. {alt_message}", booking_id)

    except TidyCalApiError:
        return (
            "Couldn't reach the calendar system to reschedule. You can pick a new time "
            f"directly here: {BOOKING_LINK}\n\nI've also flagged this to our team.",
            booking_id,
        )