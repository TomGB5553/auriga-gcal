"""Turn raw_timetable.json into a clean list of calendar events."""
from __future__ import annotations

import json
from dataclasses import dataclass

import config

# Auriga status codes we treat as "not happening" -> not put on the calendar.
CANCELLED_CODES = {"ANNULEE", "SUPPRIMEE"}

# activityType.code -> our coarse category (drives colour + title tag)
CATEGORY_BY_CODE = {
    "CM": "lecture", "CM_ET": "lecture", "COURS": "lecture", "CONF": "lecture",
    "PC": "tutorial", "TD": "tutorial",
    "BE": "project", "PROJET": "project",
    "EX": "exam", "EXAM": "exam", "DS": "exam",
    "TP": "lab",
    "PRE": "presentation",
}

# short tag appended after the course name, e.g. "Applied Mathematics · PC"
TAG_BY_CATEGORY = {
    "lecture": "CM",
    "tutorial": "PC",
    "project": "BE",
    "exam": "Examen",
    "lab": "TP",
}


def _cap(caption: dict | None, lang: str = "fr") -> str:
    if not caption:
        return ""
    return caption.get(lang) or caption.get("en") or caption.get("fr") or ""


@dataclass
class Event:
    auriga_id: int
    start: str          # ISO 8601, e.g. "2026-08-31T07:00:00Z"
    end: str
    summary: str
    location: str
    description: str
    category: str = "other"
    color_id: str | None = None

    @property
    def gcal_id(self) -> str:
        # Google event ids must match [a-v0-9]{5,1024}; "auriga" + digits is safe.
        return f"auriga{self.auriga_id}"

    def to_gcal_body(self) -> dict:
        body = {
            "id": self.gcal_id,
            "summary": self.summary,
            "location": self.location,
            "description": self.description,
            "start": {"dateTime": self.start, "timeZone": config.TIMEZONE},
            "end": {"dateTime": self.end, "timeZone": config.TIMEZONE},
            "reminders": {"useDefault": False},
            "transparency": "opaque",
            "extendedProperties": {"private": {"auriga": "1"}},
        }
        if self.color_id:
            body["colorId"] = self.color_id
        return body


def _courses(intervention: dict) -> list[str]:
    names: list[str] = []
    for u in intervention.get("interventionPedagogicalUnits") or []:
        name = _cap((u.get("pedagogicalUnit") or {}).get("caption"), config.COURSE_LANG)
        if name and name not in names:
            names.append(name)
    return names


def _one(intervention: dict) -> Event | None:
    status = (intervention.get("interventionStatus") or {}).get("code")
    if status in CANCELLED_CODES:
        return None

    start = intervention.get("startDateTime")
    end = intervention.get("endDateTime")
    if not start or not end:
        return None

    atype = intervention.get("activityType") or {}
    activity = _cap(atype.get("caption"))
    category = CATEGORY_BY_CODE.get(atype.get("code"), "other")
    desc = (intervention.get("description") or "").strip()
    is_exam = bool(intervention.get("isExam")) or category == "exam"

    courses = _courses(intervention)
    if courses:
        title = " / ".join(courses)
        tag = "Examen" if is_exam else TAG_BY_CATEGORY.get(category)
        if tag:
            title = f"{title} · {tag}"
    else:
        # admin events (presentations, etc.) have no course -> keep their label
        title = desc or activity or "Cours"
        if is_exam:
            title = f"[Examen] {title}"

    rooms = []
    for r in intervention.get("interventionResources") or []:
        res = r.get("resource") or {}
        if not res.get("isRoom"):
            continue
        name = _cap(res.get("caption"))
        ident = (res.get("customAttributes") or {}).get("RoomIdentity")
        rooms.append(f"{name} ({ident})" if ident and ident not in name else name)

    teachers = []
    for t in intervention.get("interventionInstructors") or []:
        p = t.get("person") or {}
        full = f"{(p.get('currentFirstName') or '').title()} {p.get('currentLastName') or ''}".strip()
        if full:
            teachers.append(full)

    groups = []
    for pop in intervention.get("interventionPopulations") or []:
        g = _cap((pop.get("population") or {}).get("caption"))
        if g:
            groups.append(g)

    body_lines = []
    if courses:
        body_lines.append("Cours : " + " / ".join(courses))
    if activity:
        body_lines.append("Type : " + activity)
    if desc:
        body_lines.append("Séance : " + desc)
    if teachers:
        body_lines.append("Intervenant·e·s : " + ", ".join(teachers))
    if groups:
        body_lines.append("Groupe : " + ", ".join(sorted(set(groups))))
    if status and status != "PUBLIEE":
        body_lines.append("Statut Auriga : " + status)
    body_lines.append(f"(auriga #{intervention.get('id')})")

    return Event(
        auriga_id=int(intervention["id"]),
        start=start,
        end=end,
        summary=title,
        location=" / ".join(rooms),
        description="\n".join(body_lines),
        category=category,
        color_id=config.COLOR_BY_CATEGORY.get(category),
    )


def load_events(path=None) -> list[Event]:
    raw = json.loads((path or config.RAW_DUMP).read_text())
    by_id: dict[int, Event] = {}
    for week in raw:
        for intervention in (week.get("data") or {}).get("interventions") or []:
            ev = _one(intervention)
            if ev:
                by_id[ev.auriga_id] = ev  # dedupe across overlapping weeks
    return sorted(by_id.values(), key=lambda e: e.start)


if __name__ == "__main__":
    for e in load_events():
        print(f"{e.start[:16]}  {e.category:12}  {e.summary:42.42}  {e.location}")
