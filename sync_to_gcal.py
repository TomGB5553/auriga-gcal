"""Mirror the parsed timetable into a dedicated Google Calendar.

Idempotent: every event gets a deterministic id derived from its Auriga id, so
re-running upserts instead of duplicating. Future events that vanished from
Auriga are deleted from the calendar.

First run opens a browser for Google sign-in (needs credentials.json from a
Google Cloud OAuth "Desktop app" client). The token is cached in token.json.
"""
from __future__ import annotations

import datetime as dt
import sys
import time

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from events import load_events
from notify import notify

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_service():
    creds = None
    if config.GOOGLE_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(config.GOOGLE_TOKEN), SCOPES)
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # e.g. "Token has been expired or revoked" -- testing-mode apps lose
            # their refresh token after 7 days. Fall back to a fresh sign-in.
            creds = None
    if not creds or not creds.valid:
        if not config.GOOGLE_CREDENTIALS.exists():
            sys.exit(
                "Missing credentials.json. Create an OAuth 'Desktop app' client at "
                "https://console.cloud.google.com/apis/credentials and save it here."
            )
        if not sys.stdin.isatty():
            sys.exit(
                "Google sign-in needed but not running interactively. Run "
                "`./.venv/bin/python sync_to_gcal.py` by hand once to re-authorise."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.GOOGLE_CREDENTIALS), SCOPES
        )
        creds = flow.run_local_server(port=0)
    config.GOOGLE_TOKEN.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_calendar_id(svc) -> str:
    if config.CALENDAR_ID_FILE.exists():
        cid = config.CALENDAR_ID_FILE.read_text().strip()
        if cid:
            return cid
    # reuse an existing one with the same name if present
    page_token = None
    while True:
        lst = svc.calendarList().list(pageToken=page_token).execute()
        for cal in lst.get("items", []):
            if cal.get("summary") == config.CALENDAR_NAME:
                config.CALENDAR_ID_FILE.write_text(cal["id"])
                return cal["id"]
        page_token = lst.get("nextPageToken")
        if not page_token:
            break
    created = svc.calendars().insert(
        body={"summary": config.CALENDAR_NAME, "timeZone": config.TIMEZONE}
    ).execute()
    config.CALENDAR_ID_FILE.write_text(created["id"])
    print(f"Created calendar '{config.CALENDAR_NAME}'.")
    return created["id"]


def existing_future_events(svc, cid: str) -> dict[str, dict]:
    # start a week back so classes earlier today / earlier this week (which the
    # fetch still returns) are matched instead of re-inserted every run
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
    out: dict[str, dict] = {}
    page_token = None
    while True:
        resp = svc.events().list(
            calendarId=cid, timeMin=since, singleEvents=True,
            privateExtendedProperty="auriga=1", maxResults=2500,
            pageToken=page_token,
            fields="items(id,summary,location,description,colorId,start,end),nextPageToken",
        ).execute()
        for ev in resp.get("items", []):
            out[ev["id"]] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _instant(slot: dict):
    s = slot.get("dateTime")
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else slot.get("date")


def _differs(current: dict, body: dict) -> bool:
    """True if the calendar event needs updating to match the freshly built body."""
    if (current.get("summary") or "") != (body.get("summary") or ""):
        return True
    if (current.get("location") or "") != (body.get("location") or ""):
        return True
    if (current.get("description") or "") != (body.get("description") or ""):
        return True
    if (current.get("colorId") or "") != (body.get("colorId") or ""):
        return True
    try:
        if _instant(current["start"]) != _instant(body["start"]):
            return True
        if _instant(current["end"]) != _instant(body["end"]):
            return True
    except (KeyError, ValueError):
        return True
    return False


def _run(request):
    """Execute a Calendar API request, backing off on rate-limit / transient errors."""
    delay = 1.0
    for attempt in range(7):
        try:
            return request.execute(num_retries=3)
        except HttpError as e:
            transient = e.resp.status in (403, 429, 500, 503) and (
                b"ateLimit" in e.content or b"userRateLimit" in e.content
                or e.resp.status in (500, 503)
            )
            if not transient or attempt == 6:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 32)


def sync() -> tuple[int, int, int]:
    events = load_events()
    if not events:
        raise SystemExit("No events parsed from raw_timetable.json -- run fetch_timetable.py first.")

    svc = get_service()
    cid = get_calendar_id(svc)

    current = existing_future_events(svc, cid)
    added = changed = removed = 0

    for ev in events:
        body = ev.to_gcal_body()
        cur = current.pop(body["id"], None)
        if cur is None:
            try:
                _run(svc.events().insert(calendarId=cid, body=body))
            except HttpError as e:
                if e.resp.status == 409:  # race: already there
                    _run(svc.events().update(calendarId=cid, eventId=body["id"], body=body))
                else:
                    raise
            added += 1
            time.sleep(0.25)
        elif _differs(cur, body):
            _run(svc.events().update(calendarId=cid, eventId=body["id"], body=body))
            changed += 1
            time.sleep(0.25)
        # unchanged -> no API call

    # left in `current` = on the calendar but not in the fetched window.
    # Only remove ones still in the future -- past classes just fell out of the
    # fetch range and aren't real cancellations.
    now = dt.datetime.now(dt.timezone.utc)
    for gid, cur in current.items():
        try:
            if _instant(cur["start"]) < now:
                continue
        except (KeyError, ValueError, TypeError):
            pass
        try:
            _run(svc.events().delete(calendarId=cid, eventId=gid))
        except HttpError as e:
            if e.resp.status not in (404, 410):
                raise
        removed += 1

    print(f"CHANGES added={added} changed={changed} removed={removed}")
    print(f"{added + changed} written, {removed} removed, {len(events)} events "
          f"-> '{config.CALENDAR_NAME}'.")
    return added, changed, removed


_OFFLINE_HINTS = (
    "ServerNotFoundError", "TransportError", "ERR_NAME_NOT_RESOLVED",
    "Name or service not known", "Temporary failure in name resolution",
    "Network is unreachable", "Connection reset", "Connection aborted",
    "timed out", "getaddrinfo",
)


def _looks_offline(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    text = f"{type(exc).__name__}: {exc}"
    return any(h in text for h in _OFFLINE_HINTS)


def main() -> None:
    try:
        added, changed, removed = sync()
    except SystemExit as e:
        if e.code not in (0, None):
            notify("Auriga → Calendar: sync failed", str(e.code))
        raise
    except BaseException as e:
        if _looks_offline(e):
            print(f"network error, skipping this run: {e}")
            sys.exit(0)
        notify("Auriga → Calendar: sync failed", f"{type(e).__name__}: {e}")
        raise
    if added or changed or removed:
        notify("Timetable updated",
               f"added {added} · changed {changed} · removed {removed}")


if __name__ == "__main__":
    main()
