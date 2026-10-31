"""Who may ask a joe for what: the capabilities it serves, and the requests it
refuses before any route sees them.

**joe has no authentication.** Whatever can reach its port is answered, with
the rights of the account joe runs as. It is meant for one machine its owner
trusts, listening on loopback; listening wider hands everything that is on to
whatever can reach the port. docs/security.md is the threat model.

**A fresh joe serves the media API and nothing that records or hands data
out.** Each capability is a setting, `JOE_ALLOW_<NAME>`, `1` or `0`. `media` is
on until it is turned off: a video editor's uploads, transcribed and analysed
by an id only the uploader is given. The rest wait to be turned on: the
microphone, the transcripts of what was said and heard, and the audio library.
Each one on is announced with a warning when the server starts (`banner`); a
route of one that is off answers 403 naming its setting (`refusal`); and a
setting joe cannot read stops it starting (`problems`) rather than being
guessed at.

**A browser is not let in from another site.** A page open in a browser on this
machine can make the browser send requests to loopback, and a page whose name
is re-pointed at 127.0.0.1 -- DNS rebinding -- can read the answers too.
`Guard` refuses, before routing:

- a `Host` joe does not answer to (`host_allowed`): loopback names, IP
  addresses, `host.docker.internal` and `JOE_ALLOWED_HOSTS`. A rebinding page
  can only arrive under a name of its own;
- a state-changing request whose `Origin` is a page joe does not take requests
  from (`origin_allowed`): its own, at the Host the request was sent to, its
  dev page on port 3000, and `JOE_ALLOWED_ORIGINS`;
- any request the browser marks `Sec-Fetch-Site: cross-site`, except
  following a link.

Clients that are not browsers -- alfred through vox, qmcp, curl -- send no
Origin and no Sec-Fetch-Site, so only the Host rule applies to them.

**A request from beyond loopback is announced.** The first request from each
address that is not this machine's loopback prints a warning (`notice`): the
port is reachable from there, with everything that is on.

Every setting is read when it is asked about, so the banner, the routes and
the guard always agree with the environment the server runs in.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

PREFIX = "JOE_ALLOW_"
HOSTS_SETTING = "JOE_ALLOWED_HOSTS"
ORIGINS_SETTING = "JOE_ALLOWED_ORIGINS"
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

    @property
    def plural(self) -> bool:
        """Whether its title takes "are": "the transcripts are off"."""
        return self.title.endswith("s")


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
    are, them = ("are", "them") if capability.plural else ("is", "it")
    return (f"{capability.title} {are} off on this joe: {capability.setting}=1 turns {them} on, "
            f"for whatever can reach this port -- joe has no authentication ({SECURITY_DOC})")


def _listed(setting: str, environ: Mapping[str, str] | None) -> list[str]:
    raw = _environ(environ).get(setting) or ""
    return [item.strip().lower().rstrip("/") for item in raw.split(",") if item.strip()]


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
    for host in _listed(HOSTS_SETTING, env):
        if any(c in host for c in "/:@ ") and not _is_ip(host):
            found.append(f"{HOSTS_SETTING} lists {host!r}, which is not a host name: give names "
                         f"without a scheme or a port")
    for origin in _listed(ORIGINS_SETTING, env):
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
            found.append(f"{ORIGINS_SETTING} lists {origin!r}, which is not an origin: give "
                         f"scheme://host[:port], as a browser sends it")
    return found


def banner(environ: Mapping[str, str] | None = None) -> list[str]:
    """What the server says as it starts: that it has no authentication, what
    is on and off, a warning for each capability turned on, and what else it
    answers to."""
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
    hosts = _listed(HOSTS_SETTING, environ)
    if hosts:
        lines.append(f"joe: also answers to the host names {', '.join(hosts)} ({HOSTS_SETTING})")
    origins = _listed(ORIGINS_SETTING, environ)
    if origins:
        lines.append(f"joe: also takes requests from pages at {', '.join(origins)} "
                     f"({ORIGINS_SETTING})")
    return lines


# ─── Where a request comes from ───────────────────────────────────────────────

# joe's own dev page, as `joe dev` serves it. Its requests reach the API through
# Vite's proxy, under the page's own Host, or straight to the API.
DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
# Docker Desktop's name for the host, which alfred's containers reach joe by.
DOCKER_HOST = "host.docker.internal"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def host_name(host: str) -> str:
    """The name in a `Host` header: lower-cased, without its port, brackets or
    trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        name = host[1:end] if end > 0 else host[1:]
    else:
        name, colon, port = host.rpartition(":")
        if not colon or not port.isdigit():
            name = host
    return name.rstrip(".")


def host_allowed(host: str, environ: Mapping[str, str] | None = None) -> bool:
    """Whether joe answers a request sent to `host`: a loopback name, an IP
    address, Docker's name for the host, or a name in `JOE_ALLOWED_HOSTS`.

    A page rebound to 127.0.0.1 arrives under the name it was loaded from,
    which is none of these. A page loaded from an IP address cannot be
    re-pointed, so any address is safe to answer."""
    name = host_name(host)
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost") or name == DOCKER_HOST or _is_ip(name):
        return True
    return name in _listed(HOSTS_SETTING, environ)


def page_origins(environ: Mapping[str, str] | None = None) -> list[str]:
    """The pages joe takes requests from wherever they are sent: its dev page,
    and `JOE_ALLOWED_ORIGINS`."""
    return [*DEV_ORIGINS, *_listed(ORIGINS_SETTING, environ)]


def origin_allowed(origin: str, host: str | None, environ: Mapping[str, str] | None = None) -> bool:
    """Whether a page at `origin` may ask: one of `page_origins`, or a page
    joe itself served, at the Host the request was sent to. Never `null`, the
    origin of a sandboxed frame or a local file."""
    origin = origin.strip().lower().rstrip("/")
    if not origin or origin == "null":
        return False
    if origin in page_origins(environ):
        return True
    parts = urlsplit(origin)
    return (host is not None and parts.scheme in ("http", "https")
            and parts.netloc == host.strip().lower())


def judge(method: str, headers: Headers,
          environ: Mapping[str, str] | None = None) -> tuple[int, str] | None:
    """Why a request is refused before routing, as `(status, detail)`, or None
    when it is not. See the module's docstring."""
    host = headers.get("host")
    if host is not None and not host_allowed(host, environ):
        return 400, (f"joe does not answer to the host {host_name(host)[:100]!r}: only to "
                     f"loopback, IP addresses, {DOCKER_HOST} and the names in {HOSTS_SETTING}. A "
                     f"name it does not know is how a DNS rebinding page reaches it ({SECURITY_DOC})")
    origin = headers.get("origin")
    if origin is not None and origin_allowed(origin, host, environ):
        return None
    safe = method.upper() in SAFE_METHODS
    if origin is not None and not safe:
        return 403, (f"joe takes no request from a page at {origin[:100]!r}: only from its own, "
                     f"and from those in {ORIGINS_SETTING} ({SECURITY_DOC})")
    if headers.get("sec-fetch-site") == "cross-site" and not (
            safe and headers.get("sec-fetch-mode") == "navigate"):
        return 403, ("joe takes no request a browser marks as from another site "
                     f"(Sec-Fetch-Site: cross-site), other than following a link ({SECURITY_DOC})")
    return None


class Guard:
    """ASGI middleware refusing what `judge` refuses, as `{"detail": str}`,
    before any route -- or CORS -- sees the request; and announcing each
    address beyond loopback it answers (`notice`)."""

    def __init__(self, app, environ: Mapping[str, str] | None = None):
        self.app = app
        self.environ = environ

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            refused = judge(scope["method"], Headers(scope=scope), self.environ)
            if refused is not None:
                status, detail = refused
                await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
                return
            notice(scope.get("client"))
        await self.app(scope, receive, send)


class PageCORS(CORSMiddleware):
    """CORS for `page_origins`, read on each request as `Guard` reads them, so
    a page joe takes requests from can read the answers too. A Private Network
    Access preflight is refused, as Starlette refuses one by default."""

    def is_allowed_origin(self, origin: str) -> bool:
        return origin.strip().lower().rstrip("/") in page_origins()


# ─── Who is asking ────────────────────────────────────────────────────────────

# Addresses beyond loopback already announced, and how many are announced at
# most, so a busy network cannot grow the set without bound.
NOTICE_LIMIT = 64
_noticed: set[str] = set()
_noticed_lock = threading.Lock()


def beyond_loopback(address: str) -> bool:
    """Whether a client's address is another machine's, or a container's. Not
    an address at all -- a test client, a Unix socket -- is not."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return not (ip.is_loopback or (mapped is not None and mapped.is_loopback))


def notice(client, stream=None) -> bool:
    """Announce, once per address, a request from beyond this machine's
    loopback: the port is reachable from there, with everything that is on.
    Returns whether this call announced one."""
    if not client:
        return False
    address = str(client[0])
    if not beyond_loopback(address):
        return False
    with _noticed_lock:
        if address in _noticed or len(_noticed) >= NOTICE_LIMIT:
            return False
        _noticed.add(address)
    print(f"joe: !!! WARNING: answering {address}, which is not this machine's loopback. "
          f"Everything that is on is reachable from there ({SECURITY_DOC}).",
          file=stream or sys.stderr, flush=True)
    return True
