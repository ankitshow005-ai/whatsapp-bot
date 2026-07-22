# state.py
# ---------------------------------------------------------
# WhatsApp webhooks are stateless, so this is the app's
# memory per user (keyed by phone number). MVP — one dict,
# no timeout logic, no separate "stage machine" file.
#
#   - "history"  the transcript, so escalations show full
#                context, not just one message
#   - "booking"  None if no booking in progress, otherwise a
#                dict tracking which field we're collecting
#                next and what's been gathered so far
#   - "last_booking_id"  most recent confirmed booking, for
#                cancel/reschedule requests later
# ---------------------------------------------------------

MAX_HISTORY_TURNS = 20

_state: dict[str, dict] = {}
_EMAIL_RE = __import__("re").compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def find_known_email(user_number: str) -> str | None:
    """
    Cheap, no-LLM scan of the conversation so far for an email address the
    user already typed (e.g. while asking a question before deciding to
    book). Lets the booking flow skip re-asking for it. Regex only — no
    extra LLM round-trip, unlike a "smart extraction" call would need.
    """
    match = _EMAIL_RE.search(get_history_text(user_number))
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)")


def _get(user_number: str) -> dict:
    if user_number not in _state:
        _state[user_number] = {
            "history": [], "booking": None, "last_booking_id": None,
            "last_name": None, "last_email": None,
        }
    return _state[user_number]


def set_last_customer(user_number: str, name: str | None, email: str | None) -> None:
    """
    Remembers the name/email used on the most recent successful booking so
    future bookings/reschedules can skip re-asking for them. Deliberately
    stored OUTSIDE the "booking" dict, which gets wiped after each booking
    completes — this needs to survive across bookings.
    """
    entry = _get(user_number)
    if name:
        entry["last_name"] = name
    if email:
        entry["last_email"] = email


def get_last_customer(user_number: str) -> tuple[str | None, str | None]:
    entry = _get(user_number)
    return entry["last_name"], entry["last_email"]


def add_turn(user_number: str, role: str, text: str) -> None:
    entry = _get(user_number)
    entry["history"].append(f"{'User' if role == 'user' else 'Jessy'}: {text}")
    entry["history"] = entry["history"][-MAX_HISTORY_TURNS:]


def get_history_text(user_number: str) -> str:
    entry = _get(user_number)
    return "\n".join(entry["history"]) if entry["history"] else "(no prior messages)"


def is_first_message(user_number: str) -> bool:
    """
    True only if the current user turn is the very first thing said in this
    conversation (i.e. the bot hasn't replied yet). Used to gate the instant
    "hi there" greeting shortcut — a bare "yo"/"hey" said mid-conversation is
    NOT a fresh greeting, it's often shorthand for "yeah" answering whatever
    the bot just asked, so it needs the full-context LLM, not the canned intro.
    """
    return len(_get(user_number)["history"]) <= 1


def get_booking(user_number: str) -> dict | None:
    return _get(user_number)["booking"]


def start_booking(user_number: str) -> None:
    _get(user_number)["booking"] = {"step": "query", "name": None, "email": None, "query": None}


def update_booking(user_number: str, field: str, value: str) -> None:
    _get(user_number)["booking"][field] = value


def clear_booking(user_number: str) -> None:
    _get(user_number)["booking"] = None


def set_last_booking_id(user_number: str, booking_id: str | None) -> None:
    _get(user_number)["last_booking_id"] = booking_id


def get_last_booking_id(user_number: str) -> str | None:
    return _get(user_number)["last_booking_id"]