# state.py
# ---------------------------------------------------------
# WhatsApp webhooks are stateless, so this is the app's
# memory per user (keyed by phone number). Now backed by
# Upstash Redis for persistent, 24/7 memory.
# ---------------------------------------------------------

import json
import re
from upstash_redis import Redis

MAX_HISTORY_TURNS = 20

# Initialize Upstash Redis client. 
# Requires UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in your .env
redis_client = Redis.from_env()

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

def _get(user_number: str) -> dict:
    data = redis_client.get(user_number)
    if data:
        # Upstash returns strings, parsing them back to dictionaries
        return json.loads(data) if isinstance(data, str) else data
    
    # Default state if nothing exists in Redis yet
    return {
        "history": [], "booking": None, "last_booking_id": None,
        "last_name": None, "last_email": None,
        "user_name": None, "awaiting_name": False,
    }

def _save(user_number: str, entry: dict) -> None:
    # Save the modified dictionary back to the database
    redis_client.set(user_number, json.dumps(entry))

def find_known_email(user_number: str) -> str | None:
    match = _EMAIL_RE.search(get_history_text(user_number))
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)")

def get_user_name(user_number: str) -> str | None:
    return _get(user_number)["user_name"]

def set_user_name(user_number: str, name: str) -> None:
    entry = _get(user_number)
    entry["user_name"] = name
    _save(user_number, entry)

def is_awaiting_name(user_number: str) -> bool:
    return _get(user_number)["awaiting_name"]

def set_awaiting_name(user_number: str, value: bool) -> None:
    entry = _get(user_number)
    entry["awaiting_name"] = value
    _save(user_number, entry)

def set_last_customer(user_number: str, name: str | None, email: str | None) -> None:
    entry = _get(user_number)
    if name:
        entry["last_name"] = name
    if email:
        entry["last_email"] = email
    _save(user_number, entry)

def get_last_customer(user_number: str) -> tuple[str | None, str | None]:
    entry = _get(user_number)
    return entry["last_name"], entry["last_email"]

def add_turn(user_number: str, role: str, text: str) -> None:
    entry = _get(user_number)
    entry["history"].append(f"{'User' if role == 'user' else 'Jessy'}: {text}")
    entry["history"] = entry["history"][-MAX_HISTORY_TURNS:]
    _save(user_number, entry)

def get_history_text(user_number: str) -> str:
    entry = _get(user_number)
    return "\n".join(entry["history"]) if entry["history"] else "(no prior messages)"

def is_first_message(user_number: str) -> bool:
    return len(_get(user_number)["history"]) <= 1

def get_booking(user_number: str) -> dict | None:
    return _get(user_number)["booking"]

def start_booking(user_number: str) -> None:
    entry = _get(user_number)
    entry["booking"] = {"step": "query", "name": None, "email": None, "query": None}
    _save(user_number, entry)

def update_booking(user_number: str, field: str, value: str) -> None:
    entry = _get(user_number)
    if entry["booking"]:
        entry["booking"][field] = value
        _save(user_number, entry)

def save_booking(user_number: str, booking: dict) -> None:
    """
    Persists the FULL booking dict back to Redis in one write. Needed
    because get_booking() returns a fresh copy deserialized from Redis on
    every call — mutating fields on that dict directly (e.g.
    booking["step"] = "email") only changes the in-memory local object and
    is silently lost otherwise. Callers that mutate booking dict fields
    directly (step, name, email, query, _rescheduling_id, etc.) must call
    this before returning, or the next message will re-load the old state
    from Redis and the flow will appear stuck / repeat itself.
    """
    entry = _get(user_number)
    entry["booking"] = booking
    _save(user_number, entry)

def clear_booking(user_number: str) -> None:
    entry = _get(user_number)
    entry["booking"] = None
    _save(user_number, entry)

def end_session(user_number: str) -> None:
    """
    Full reset for an explicit "end chat" action (web widget close button).
    Deletes the whole Redis entry rather than just clearing booking, since
    the point is a genuinely fresh start next time, not a half-cleared
    state (old history, old name, orphaned active_booking_ids would all
    otherwise survive a soft clear).
    """
    redis_client.delete(user_number)

def set_last_booking_id(user_number: str, booking_id: str | None) -> None:
    """
    Sets the "current" booking id (used for cancel/reschedule shorthand)
    AND appends it to active_booking_ids so earlier bookings from the same
    number aren't silently lost when a second one is made. Previously this
    only tracked a single id, so booking #2 overwrote booking #1's id
    entirely — the app had no memory the first booking existed, couldn't
    cancel/verify it, yet nothing stopped the bot from later claiming it
    had. Pass None to clear the "current" pointer (e.g. after a cancel)
    without touching the active list.
    """
    entry = _get(user_number)
    entry["last_booking_id"] = booking_id
    if booking_id is not None:
        active = entry.get("active_booking_ids") or []
        if booking_id not in active:
            active.append(booking_id)
        entry["active_booking_ids"] = active
    _save(user_number, entry)

def get_last_booking_id(user_number: str) -> str | None:
    return _get(user_number)["last_booking_id"]

def get_active_booking_ids(user_number: str) -> list[str]:
    return _get(user_number).get("active_booking_ids") or []

def remove_active_booking_id(user_number: str, booking_id: str) -> None:
    entry = _get(user_number)
    active = entry.get("active_booking_ids") or []
    if booking_id in active:
        active.remove(booking_id)
    entry["active_booking_ids"] = active
    if entry.get("last_booking_id") == booking_id:
        entry["last_booking_id"] = active[-1] if active else None
    _save(user_number, entry)

def set_last_escalated_at(user_number: str, timestamp: float) -> None:
    entry = _get(user_number)
    entry["last_escalated_at"] = timestamp
    _save(user_number, entry)

def get_last_escalated_at(user_number: str) -> float | None:
    return _get(user_number).get("last_escalated_at")