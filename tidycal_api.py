# tidycal_api.py
# ---------------------------------------------------------
# Thin wrapper around TidyCal's REST API — this is what
# actually checks real availability and creates/cancels
# bookings. booking.py never talks HTTP directly.
#
# Requires (in .env):
#   TIDYCAL_API_KEY        - Personal Access Token from
#                             Integrations -> Advanced -> Manage API keys
#                             -> "Personal tokens" (requires a paid plan)
#   TIDYCAL_BOOKING_TYPE_ID - numeric ID of the booking type to book
#                             against (GET /api/booking-types with your
#                             token to find it)
#
# IMPORTANT DIFFERENCE FROM CAL.COM:
# TidyCal has NO reschedule endpoint. A "reschedule" here is
# implemented as cancel-the-old-booking + create-a-new-one —
# see reschedule_booking() below.
#
# Docs: https://tidycal.com/developer/docs/
# ---------------------------------------------------------

import logging
from datetime import datetime, timezone

import requests

from config import TIDYCAL_API_KEY, TIDYCAL_BOOKING_TYPE_ID, TIDYCAL_API_BASE, TIDYCAL_TIMEZONE

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {TIDYCAL_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def tidycal_datetime(dt: datetime) -> str:
    """
    TidyCal requires strict UTC in the form YYYY-MM-DDTHH:MM:SSZ. A plain
    dt.isoformat() on a timezone-aware datetime produces an offset suffix
    instead (e.g. "+05:30"), which TidyCal rejects — this was the actual
    cause of "trouble reaching the calendar system" errors, not a real
    outage. Always convert to UTC and format with a literal Z here.
    """
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware.")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TidyCalApiError(Exception):
    """Raised when a TidyCal API call fails — caller decides how to degrade."""
    pass


def get_available_slots(start: datetime, end: datetime) -> list[datetime]:
    """Returns available start-time slots between start/end for the configured booking type."""
    try:
        resp = requests.get(
            f"{TIDYCAL_API_BASE}/booking-types/{TIDYCAL_BOOKING_TYPE_ID}/timeslots",
            headers=_HEADERS,
            params={
                "starts_at": tidycal_datetime(start),
                "ends_at": tidycal_datetime(end),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        slots = [
            datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
            for slot in data
            if slot.get("available_bookings", 0) > 0
        ]
        return sorted(slots)

    except Exception as e:
        logger.error(f"Failed to fetch TidyCal availability: {e}")
        raise TidyCalApiError(str(e)) from e


def is_slot_available(requested_time: datetime, tolerance_minutes: int = 15) -> bool:
    """Checks whether requested_time falls within an available slot (± tolerance)."""
    from datetime import timedelta
    day_start = requested_time.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    slots = get_available_slots(day_start, day_end)  # let TidyCalApiError propagate
    return any(abs((slot - requested_time).total_seconds()) <= tolerance_minutes * 60 for slot in slots)


def create_booking(name: str, email: str, start_time: datetime, notes: str = "") -> dict:
    """
    Books the meeting. Returns dict with id, meeting_url, starts_at.
    Raises TidyCalApiError on failure (including 409 = slot no longer available).
    """
    try:
        payload = {
            "starts_at": tidycal_datetime(start_time),
            "name": name,
            "email": email,
            "timezone": TIDYCAL_TIMEZONE,
        }
        # TidyCal has no free-text "notes" field on the booking itself — if you've
        # set up a booking-type question for this, map it via booking_questions
        # (needs the question's ID from GET /api/booking-types/{id}). Left out
        # here since it's account-specific; add it if you wire one up.

        resp = requests.post(
            f"{TIDYCAL_API_BASE}/booking-types/{TIDYCAL_BOOKING_TYPE_ID}/bookings",
            headers=_HEADERS,
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        return {
            "id": data.get("id"),
            "meeting_url": data.get("meeting_url"),
            "starts_at": data.get("starts_at"),
        }

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            logger.info("TidyCal: requested slot no longer available (409)")
            raise TidyCalApiError("slot_taken") from e
        logger.error(f"Failed to create TidyCal booking: {e}")
        raise TidyCalApiError(str(e)) from e
    except Exception as e:
        logger.error(f"Failed to create TidyCal booking: {e}")
        raise TidyCalApiError(str(e)) from e


def cancel_booking(booking_id: int, reason: str = "Cancelled via WhatsApp bot") -> None:
    try:
        resp = requests.patch(
            f"{TIDYCAL_API_BASE}/bookings/{booking_id}/cancel",
            headers=_HEADERS,
            json={"reason": reason},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"Cancelled TidyCal booking {booking_id}")

    except Exception as e:
        logger.error(f"Failed to cancel TidyCal booking {booking_id}: {e}")
        raise TidyCalApiError(str(e)) from e


def reschedule_booking(booking_id: int, name: str, email: str, new_start_time: datetime, notes: str = "") -> dict:
    """
    TidyCal has no reschedule endpoint, so this cancels the old booking and
    creates a new one. If creating the new booking fails, the old one is
    LEFT INTACT (we cancel only after the new booking succeeds) so the user
    is never left with nothing booked.
    """
    new_booking = create_booking(name=name, email=email, start_time=new_start_time, notes=notes)
    try:
        cancel_booking(booking_id, reason="Rescheduled via WhatsApp bot")
    except TidyCalApiError:
        # New booking exists but old one didn't cancel cleanly — log loudly,
        # the founder should manually clean up the stale old slot.
        logger.error(
            f"Rescheduled to new booking {new_booking.get('id')} but failed to "
            f"cancel old booking {booking_id} — needs manual cleanup"
        )
    return new_booking