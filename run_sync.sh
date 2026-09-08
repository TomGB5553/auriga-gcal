#!/bin/bash
# Fetch the timetable and push it to Google Calendar. Run by launchd on a schedule.
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
exec >> sync.log 2>&1

# keep the log from growing forever
[ -f sync.log ] && [ "$(wc -l < sync.log)" -gt 2000 ] && tail -n 500 sync.log > sync.log.tmp && mv sync.log.tmp sync.log
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
./.venv/bin/python fetch_timetable.py && ./.venv/bin/python sync_to_gcal.py
echo
