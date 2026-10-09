"""What joe does itself with a spoken segment, declared once.

Every phrase joe acts on inside a take -- striking what was said, marking the
last take for tuning, showing the voice's level -- is declared in
`vocabulary.toml` beside this module, under a dotted key with a `says` line for
a person. `Modules.Transcript` reads its lists from here, and
`GET /api/voice/vocabulary` serves the same for the page, so what the page
shows as joe's own words is what joe acts on.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("vocabulary.toml")


@cache
def load() -> dict[str, Any]:
    """The declared vocabulary, read once."""
    return tomllib.loads(FILE.read_text(encoding="utf-8"))


def phrases(key: str) -> tuple[str, ...]:
    """An entry's phrases, in the order declared, at a dotted key such as `take.scratch`."""
    node: Any = load()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"no vocabulary entry {key!r}")
        node = node[part]
    return tuple(node.get("phrases", ()))


def entries() -> list[dict[str, Any]]:
    """Every entry with its key, what it does, and what to say."""
    return [{"key": f"{group}.{name}", "says": body.get("says", ""),
             "phrases": list(body.get("phrases", ()))}
            for group, members in load().items() for name, body in members.items()
            if isinstance(body, dict) and "phrases" in body]
