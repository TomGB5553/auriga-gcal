#!/bin/bash
# Fired by launchd at several checkpoints a day (see the .plist). Each
# checkpoint is nearly free if a sync already succeeded recently -- the real
# fetch+sync only runs when staleness.py says it's actually due.
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
exec >> sync.log 2>&1

# keep the log from growing forever
[ -f sync.log ] && [ "$(wc -l < sync.log)" -gt 2000 ] && tail -n 500 sync.log > sync.log.tmp && mv sync.log.tmp sync.log

ts="$(date '+%Y-%m-%d %H:%M:%S')"
if ! ./.venv/bin/python staleness.py; then
  age="$(./.venv/bin/python -c 'import staleness; print(staleness.age_str())')"
  echo "=== $ts === up to date (last success $age), skipping"
  exit 0
fi

echo "=== $ts ==="
./.venv/bin/python fetch_timetable.py && ./.venv/bin/python sync_to_gcal.py
echo
