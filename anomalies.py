"""Spot timetable oddities worth a human look.

Currently one check: the same course shown as two consecutive blocks of
*different* class types in a shared room (e.g. a CM straight followed by a PC),
which usually means Auriga split or mislabelled a single session -- and it
makes the colour-by-type look wrong on the calendar.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import config
from events import TAG_BY_CATEGORY, Event

_LOCAL = ZoneInfo(config.TIMEZONE)


def _t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _rooms(e: Event) -> set[str]:
    return {r.strip() for r in e.location.split(" / ") if r.strip()}


def find_split_blocks(events: list[Event]) -> list[tuple[Event, Event]]:
    """Pairs (earlier, later) of the same course, sharing a room, with different
    categories, where the later one starts at most ODD_BLOCK_MAX_GAP_MIN minutes
    after the earlier one ends (or overlaps it)."""
    evs = sorted(events, key=lambda e: _t(e.start))
    max_gap = dt.timedelta(minutes=config.ODD_BLOCK_MAX_GAP_MIN)
    pairs: list[tuple[Event, Event]] = []
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            if _t(b.start) - _t(a.end) > max_gap:
                break  # sorted by start: every later block is even further away
            if a.course and a.course == b.course and a.category != b.category \
                    and _rooms(a) & _rooms(b):
                pairs.append((a, b))
    return pairs


def _label(e: Event) -> str:
    return TAG_BY_CATEGORY.get(e.category, e.category)


def describe(a: Event, b: Event) -> str:
    s1, e1, s2, e2 = (_t(x).astimezone(_LOCAL) for x in (a.start, a.end, b.start, b.end))
    room = sorted(_rooms(a) & _rooms(b))[0]
    return (f"{s1.strftime('%a %d %b')} {a.course}: {_label(a)} {s1:%H:%M}-{e1:%H:%M} "
            f"then {_label(b)} {s2:%H:%M}-{e2:%H:%M} ({room})")


def key(a: Event, b: Event) -> str:
    return f"{a.auriga_id}-{b.auriga_id}"


def _load_seen() -> dict[str, str]:
    try:
        return json.loads(config.ANOMALY_SEEN_FILE.read_text())
    except (OSError, ValueError):
        return {}


def new_since_last_alert(pairs: list[tuple[Event, Event]]) -> list[tuple[Event, Event]]:
    seen = _load_seen()
    return [(a, b) for a, b in pairs if key(a, b) not in seen]


def mark_alerted(pairs: list[tuple[Event, Event]]) -> None:
    seen = _load_seen()
    for a, b in pairs:
        seen[key(a, b)] = a.start
    # forget pairs that are long past so the file doesn't grow forever
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    seen = {k: v for k, v in seen.items() if _t(v) >= cutoff}
    config.ANOMALY_SEEN_FILE.write_text(json.dumps(seen, indent=2))


if __name__ == "__main__":
    from events import load_events
    found = find_split_blocks(load_events())
    print(f"{len(found)} odd pair(s)")
    for a, b in found:
        print(" -", describe(a, b))
