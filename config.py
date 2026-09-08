"""Shared settings for the Auriga -> Google Calendar sync."""
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- Auriga ---
AURIGA_BASE = "https://auriga.isae-supaero.fr"
PLANNING_API = AURIGA_BASE + "/api/plannings/me"
# A page that requires you to be logged in; used to detect a dead session
# and as the landing page for the manual login.
LOGIN_LANDING = AURIGA_BASE + "/"

# How many weeks ahead to sync (this week + the next N-1). 13 weeks ~= 90 days.
WEEKS_AHEAD = 13

# --- files (all git-ignored) ---
STORAGE_STATE = HERE / "storage_state.json"   # saved browser session for Auriga
RAW_DUMP = HERE / "raw_timetable.json"        # last raw API response, for debugging

# --- Google ---
GOOGLE_CREDENTIALS = HERE / "credentials.json"  # OAuth client, downloaded from Google
GOOGLE_TOKEN = HERE / "token.json"              # saved after first sign-in
CALENDAR_ID_FILE = HERE / "calendar_id.txt"     # id of the dedicated calendar
CALENDAR_NAME = "Auriga – Cours"
TIMEZONE = "Europe/Paris"

# Language for the course name in the event title: "en" or "fr"
# (falls back to the other one when a course has only one).
COURSE_LANG = "en"

# Google Calendar colour per class category. Colour ids are 1-11:
#   1 Lavender  2 Sage  3 Grape  4 Flamingo  5 Banana  6 Tangerine
#   7 Peacock   8 Graphite  9 Blueberry  10 Basil  11 Tomato
COLOR_BY_CATEGORY = {
    "lecture": "9",       # Blueberry
    "tutorial": "10",     # Basil
    "project": "6",       # Tangerine
    "exam": "11",         # Tomato
    "lab": "7",           # Peacock
    "presentation": "8",  # Graphite
    # "other" -> calendar default colour
}
