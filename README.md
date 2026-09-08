# auriga-gcal

Pulls my ISAE-SUPAERO timetable out of Auriga and mirrors it into a dedicated
Google Calendar. Runs automatically on my Mac via `launchd`.

## How it works

1. `fetch_timetable.py` — a headless browser reuses a saved SSO session to call
   `auriga.isae-supaero.fr/api/plannings/me` for the next few weeks and dumps the
   raw JSON to `raw_timetable.json`.
2. `sync_to_gcal.py` — converts that JSON to events and pushes them into a
   calendar called "Auriga – Cours", wiping and recreating future events each run.
3. `com.tom.auriga-gcal.plist` — `launchd` job that runs both on a schedule.

## One-time setup

```bash
cd ~/Documents/Apps/auriga-gcal
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium

# log in to Auriga once (opens a real browser)
./.venv/bin/python fetch_timetable.py --login
```

## Regular use

```bash
./.venv/bin/python fetch_timetable.py   # refresh raw_timetable.json
./.venv/bin/python sync_to_gcal.py      # push to Google Calendar
```

## Files that are NOT committed (secrets / local state)

`storage_state.json`, `credentials.json`, `token.json`, `calendar_id.txt`,
`raw_timetable.json` — see `.gitignore`.
