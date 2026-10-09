"""The whole transcript, read back from the datapoints.

`Data/Voice/segments.jsonl` already holds every take joe heard -- its segments,
the text it came to, what was struck, how it was labelled and what the dialog
asking made of it -- and, with the `said` records the conversation route writes,
every sentence the program asking said. Read in order, that is the whole
transcript: `read` returns its last entries, oldest first, for the page's
transcript pane to show in full and to keep across a reload.

A take whose recording never ended -- a watch closed before anyone spoke over the
question -- has segments and no `take` record, and is not an entry. A line cut
short is skipped, so one bad write never empties the transcript.
"""

from __future__ import annotations

import json
from pathlib import Path


def read(manifest: Path, limit: int = 200) -> list[dict]:
    """The last `limit` entries -- `said`, and `take` with its segments -- oldest first."""
    if not manifest.is_file():
        return []
    entries: list[dict] = []
    takes: dict[str, dict] = {}
    segments: dict[str, list[dict]] = {}
    with manifest.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = record.get("kind")
            if kind == "said":
                entries.append({"kind": "said", "text": record.get("text", ""),
                                "reason": record.get("reason"), "at": record.get("at")})
            elif kind == "segment":
                segments.setdefault(record.get("take"), []).append(record)
            elif kind == "take":
                entry = _take(record, segments.pop(record.get("take"), []))
                takes[entry["take"]] = entry
                entries.append(entry)
            elif kind == "label" and record.get("take") in takes:
                takes[record["take"]]["label"] = record.get("label")
            elif kind == "outcome" and record.get("take") in takes:
                takes[record["take"]]["outcome"] = record.get("state")
    return entries[-limit:]


def take(manifest: Path, take_id: str) -> dict | None:
    """One take's entry, by its id, or None."""
    return next((e for e in read(manifest, limit=10**9)
                 if e["kind"] == "take" and e["take"] == take_id), None)


def _take(record: dict, parts: list[dict]) -> dict:
    struck = {int(index): set(words) for index, words in (record.get("struck") or {}).items()}
    shown = []
    for part in sorted(parts, key=lambda p: p.get("index", 0)):
        index = part.get("index", 0)
        shown.append({"index": index, "words": (part.get("text") or "").split(),
                      "struck": sorted(struck.get(index, ())),
                      "start": part.get("start_s"), "end": part.get("end_s")})
    return {"kind": "take", "take": record.get("take"), "text": record.get("text", ""),
            "source": record.get("source", "voice"), "confidence": record.get("confidence"),
            "audio": record.get("audio"), "over_question": bool(record.get("over_question")),
            "at": record.get("at"), "segments": shown}
