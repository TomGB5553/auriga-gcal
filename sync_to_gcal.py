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


def existing_future_ids(svc, cid: str) -> set[str]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ids: set[str] = set()
    page_token = None
    while True:
        resp = svc.events().list(
            calendarId=cid, timeMin=now, singleEvents=True,
            privateExtendedProperty="auriga=1", maxResults=2500,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            ids.add(ev["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


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


def main() -> None:
    events = load_events()
    if not events:
        sys.exit("No events parsed from raw_timetable.json -- run fetch_timetable.py first.")

    svc = get_service()
    cid = get_calendar_id(svc)

    stale = existing_future_ids(svc, cid)
    upserted = 0
    for ev in events:
        body = ev.to_gcal_body()
        exists = body["id"] in stale
        stale.discard(body["id"])
        if exists:
            _run(svc.events().update(calendarId=cid, eventId=body["id"], body=body))
        else:
            try:
                _run(svc.events().insert(calendarId=cid, body=body))
            except HttpError as e:
                if e.resp.status == 409:  # already there -> update instead
                    _run(svc.events().update(calendarId=cid, eventId=body["id"], body=body))
                else:
                    raise
        upserted += 1
        time.sleep(0.25)  # stay under Google's per-calendar write burst

    for gid in stale:
        try:
            _run(svc.events().delete(calendarId=cid, eventId=gid))
        except HttpError as e:
            if e.resp.status not in (404, 410):
                raise

    print(f"{upserted} events synced, {len(stale)} stale removed -> '{config.CALENDAR_NAME}'.")


if __name__ == "__main__":
    main()
