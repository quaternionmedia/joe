"""What a joe lets whatever reaches it do: the capabilities it serves.

**joe HAS NO AUTHENTICATION.** Whatever can reach its port is answered, with
the rights of the account joe runs as. It is meant for one machine its owner
trusts, listening on loopback; listening wider hands everything that is on to
whatever can reach the port. docs/security.md is the threat model.

**A FRESH joe SERVES THE MEDIA API AND NOTHING THAT RECORDS OR HANDS DATA
OUT.** Each capability is a setting, `JOE_ALLOW_<NAME>`, `1` or `0`. `media` is
on until it is turned off: a video editor's uploads, transcribed and analysed
by an id only the uploader is given. The rest wait to be turned on: the
microphone, the transcripts of what was said and heard, and the audio library.
Each one on is announced with a warning when the server starts (`banner`); a
route of one that is off answers 403 naming its setting (`refusal`); and a
setting joe cannot read stops it starting (`problems`) rather than being
guessed at.

Every setting is read when it is asked about, so the banner and the routes
always agree with the environment the server runs in.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

PREFIX = "JOE_ALLOW_"
SECURITY_DOC = "docs/security.md"

_ON = ("1", "true", "yes", "on")
_OFF = ("0", "false", "no", "off", "")


@dataclass(frozen=True)
class Capability:
    """Something joe can be let do, and the setting that lets it."""

    name: str
    # How a sentence names it: "the microphone is off on this joe".
    title: str
    default: bool
    # What it serves, for the banner.
    does: str
    # What it exposes once on, for the warning: whatever can reach the port...
    exposes: str

    @property
    def setting(self) -> str:
        return f"{PREFIX}{self.name.upper()}"


CAPABILITIES = {
    capability.name: capability
    for capability in (
        Capability(
            "media", "the media API", True,
            "/api/media: audio and video uploaded, then transcribed and analysed by an id only "
            "the uploader is given -- a video editor's audio engine",
            "can upload media for this machine to decode, transcribe and analyse",
        ),
        Capability(
            "microphone", "the microphone", False,
            "records from this machine's microphone when asked, and takes answers by key -- "
            "a voice loop's, such as qmcp's",
            "can record from this machine's microphone, and answer a question being asked as if "
            "by key",
        ),
        Capability(
            "transcripts", "the transcripts", False,
            "serves what was said and heard: the conversation as it happens, the take being "
            "transcribed, and every take kept",
            "can read every conversation joe has heard, as it happens and from the start",
        ),
        Capability(
            "library", "the audio library", False,
            "Data/Audio/: lists, serves and takes recordings, transcribes them and Data/Voice/'s "
            "by name, and runs the pipeline on them",
            "can download every recording in Data/Audio/, transcribe any in Data/Voice/, add "
            "files, and run the pipeline",
        ),
    )
}


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _flag(raw: str | None, default: bool) -> bool | None:
    """`raw` as on or off; `default` when unset; None when it is neither."""
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    return None


def allowed(name: str, environ: Mapping[str, str] | None = None) -> bool:
    """Whether the capability is on. A setting joe cannot read is off: the
    server refuses to start on one (`problems`), and a route never guesses."""
    capability = CAPABILITIES[name]
    return _flag(_environ(environ).get(capability.setting), capability.default) is True


def allowed_map(environ: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Every capability, and whether it is on."""
    return {name: allowed(name, environ) for name in CAPABILITIES}


def refusal(name: str) -> str:
    """The `detail` of a route's 403 while its capability is off."""
    capability = CAPABILITIES[name]
    return (f"{capability.title} is off on this joe: {capability.setting}=1 turns it on, for "
            f"whatever can reach this port -- joe has no authentication ({SECURITY_DOC})")


def problems(environ: Mapping[str, str] | None = None) -> list[str]:
    """Each setting of joe's that cannot be read as it stands, in a sentence.
    Empty when every one can; the server will not start otherwise."""
    env = _environ(environ)
    settings = {capability.setting: capability for capability in CAPABILITIES.values()}
    found = []
    for key in sorted(env):
        if not key.startswith(PREFIX):
            continue
        capability = settings.get(key)
        if capability is None:
            found.append(f"{key} is no capability of joe's; there are {', '.join(settings)}")
        elif _flag(env[key], capability.default) is None:
            found.append(f"{key}={env[key]!r} is neither 1 nor 0")
    return found


def banner(environ: Mapping[str, str] | None = None) -> list[str]:
    """What the server says as it starts: that it has no authentication, what
    is on and off, and a warning for each capability turned on."""
    lines = [
        ("joe: NO AUTHENTICATION. Whatever can reach this port is answered, with this account's "
         "rights."),
        ("joe: Run it on one machine you trust, listening on loopback (127.0.0.1). Listening wider "
         f"opens what is on below to whatever reaches the port ({SECURITY_DOC})."),
    ]
    width = max(len(name) for name in CAPABILITIES)
    for capability in CAPABILITIES.values():
        on = allowed(capability.name, environ)
        switch = f"{capability.setting}={'0' if on else '1'} turns it {'off' if on else 'on'}"
        lines.append(f"joe: {'on ' if on else 'off'}  {capability.name:<{width}}  "
                     f"{capability.does} ({switch})")
    for capability in CAPABILITIES.values():
        if allowed(capability.name, environ) and not capability.default:
            lines.append(f"joe: !!! WARNING: {capability.setting}=1. Whatever can reach this port "
                         f"{capability.exposes}.")
    return lines
