# Privacy Policy — auriga-gcal

_Last updated: 2026-09-08_

**auriga-gcal** is a personal script that copies the author's own
ISAE-SUPAERO course timetable (from the Auriga scheduling system) into a
dedicated Google Calendar. It runs only on the author's own computer.

## What it accesses

- **Google Calendar** — via the Google Calendar API, using OAuth credentials
  belonging to the person running the script. It creates and updates events in
  a single calendar named "Auriga – Cours". It does not read or modify any
  other calendar.

## What it stores

- An OAuth token and a timetable cache, kept **only in local files on the
  machine that runs the script**. Login credentials for the school SSO are
  stored in the operating system keychain.

## What it shares

- **Nothing.** No data is transmitted anywhere except directly between the
  user's machine, ISAE-SUPAERO's Auriga service, and Google's own APIs. There
  is no server, no analytics, and no third party.

## Contact

Open an issue on the project's GitHub repository.
