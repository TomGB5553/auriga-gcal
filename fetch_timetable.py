"""Pull the raw timetable JSON out of Auriga.

    python fetch_timetable.py --login
        Opens a real browser window so you can log in through the Keycloak SSO
        by hand, once. The session is saved to storage_state.json. Use this if
        the automatic login ever breaks.

    python fetch_timetable.py
        Headless. Reuses the saved session (logging in again automatically from
        the Keychain credentials if it expired), grabs a fresh API token, calls
        the planning API for the next few weeks, and writes raw_timetable.json.

Turning that JSON into calendar events is sync_to_gcal.py's job.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from playwright.sync_api import sync_playwright

import config
from auth import PLANNING_PAGE, OfflineError, _is_offline, authenticated_page
from notify import notify


def monday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def week_ranges(weeks_ahead: int) -> list[tuple[dt.date, dt.date]]:
    start = monday_of(dt.date.today())
    return [
        (start + dt.timedelta(weeks=i), start + dt.timedelta(weeks=i, days=6))
        for i in range(weeks_ahead)
    ]


def api_url(start: dt.date, end: dt.date) -> str:
    days = "&".join(f"days={n}" for n in range(1, 8))
    return f"{config.PLANNING_API}?{days}&startDate={start}&endDate={end}"


def do_login() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(PLANNING_PAGE)
        print("\nLog in through the SSO. When your timetable is visible, come back here.\n")
        input("Press Enter when you are logged in... ")
        context.storage_state(path=str(config.STORAGE_STATE))
        browser.close()
    print(f"Session saved to {config.STORAGE_STATE.name}")


def _grab_api_token(page) -> str:
    """Reload the planning view and capture the Authorization header the SPA
    sends on its own /api/ call."""
    token: dict[str, str] = {}

    def on_request(req):
        if "/api/" in req.url and not token:
            auth = req.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                token["v"] = auth

    page.on("request", on_request)
    page.goto(PLANNING_PAGE, wait_until="domcontentloaded")
    for _ in range(20):
        page.wait_for_timeout(500)
        if token:
            break
    page.remove_listener("request", on_request)
    if not token:
        sys.exit("Could not capture an API token from the planning page.")
    return token["v"]


def fetch() -> None:
    combined = []
    try:
        with authenticated_page(headless=True) as page:
            token = _grab_api_token(page)
            req = page.context.request
            for start, end in week_ranges(config.WEEKS_AHEAD):
                resp = req.get(api_url(start, end), headers={"Authorization": token})
                if not resp.ok:
                    sys.exit(f"API error {resp.status} for {start}..{end}: {resp.text()[:300]}")
                data = resp.json()
                n = len(data) if isinstance(data, list) else "?"
                print(f"  {start} .. {end}: {n} items")
                combined.append({"startDate": str(start), "endDate": str(end), "data": data})
    except (SystemExit, OfflineError):
        raise
    except Exception as e:
        if _is_offline(e):
            raise OfflineError(str(e)) from e
        raise

    config.RAW_DUMP.write_text(json.dumps(combined, indent=2, ensure_ascii=False))
    print(f"\nWrote {config.RAW_DUMP.name} ({len(combined)} weeks).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="log in by hand in a real browser")
    args = ap.parse_args()
    if args.login:
        do_login()
    else:
        try:
            fetch()
        except OfflineError as e:
            # no connectivity -- not actionable, next scheduled run will catch up
            print(f"offline, skipping this run: {e}")
            sys.exit(0)
        except SystemExit as e:
            if e.code not in (0, None):
                notify("Auriga → Calendar: fetch failed", str(e.code))
            raise
        except BaseException as e:
            notify("Auriga → Calendar: fetch failed", f"{type(e).__name__}: {e}")
            raise
