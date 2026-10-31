# joe's security

> **joe has no authentication.** Whatever reaches its port is answered with
> the rights of the account joe runs as. It is meant for **one machine its
> owner trusts, listening on loopback** (`127.0.0.1`). On any other address,
> every capability that is on is open to whatever reaches that address: other
> machines on the network, and the internet if a router forwards the port.
>
> **A fresh joe serves the media API alone.** Everything that records from
> the microphone or hands data back out -- recordings, transcripts, the audio
> library -- is off until a setting turns it on, and the server warns at
> startup for each one on. `joe dev`, for working on joe on this machine,
> turns every one on, on loopback alone.

This page is joe's threat model, and the findings of a security review of its
API, page, dependencies and CI. `Modules/Access.py` enforces what it describes.

- [The capabilities and their settings](#the-capabilities-and-their-settings)
- [Which settings each consumer needs](#which-settings-each-consumer-needs)
- [Threat model](#threat-model)
- [Every route](#every-route)
- [Requests from a browser](#requests-from-a-browser)
- [Files, uploads and subprocesses](#files-uploads-and-subprocesses)
- [Dependencies and the supply chain](#dependencies-and-the-supply-chain)
- [The deploy workflow](#the-deploy-workflow)
- [Findings](#findings)

---

## The capabilities and their settings

Every route but the health check, the vocabulary and FastAPI's own
`/openapi.json`, `/docs` and `/redoc` belongs to one capability: a setting, `1`
or `0`, in the API's environment. A route whose capability is off answers `403`
naming the setting, before judging anything it was asked.

| Capability | Setting | Fresh joe | What it serves | Turned on, whatever reaches the port... |
| --- | --- | --- | --- | --- |
| `media` | `JOE_ALLOW_MEDIA` | **on** | `/api/media`: audio and video uploaded, then transcribed and analysed by an id only the uploader is given -- a video editor's audio engine ([media.md](media.md)) | can upload media for this machine to decode, transcribe and analyse |
| `microphone` | `JOE_ALLOW_MICROPHONE` | off | Recording from this machine's microphone (`/api/capture/*`, listen, watch, level, devices) and the controls of a take (answer, hold, strike, control, unwatch, and the state a dialog posts) | can record from this machine's microphone, and answer a question being asked as if by key |
| `transcripts` | `JOE_ALLOW_TRANSCRIPTS` | off | What was said and heard: the conversation as it happens, the take being transcribed, every take kept | can read every conversation joe has heard, as it happens and from the start |
| `library` | `JOE_ALLOW_LIBRARY` | off | `Data/Audio/`: listing, serving and taking recordings, transcribing them and `Data/Voice/`'s by name, and running the pipeline on them | can download every recording in `Data/Audio/`, transcribe any in `Data/Voice/`, add files, and run the pipeline |

`1`, `true`, `yes` and `on` turn one on; `0`, `false`, `no`, `off` and empty
turn it off. A `JOE_ALLOW_` setting joe cannot read, or one naming no
capability (`JOE_ALLOW_MICROPONE=1`), is printed and **the server does not
start**: a misspelt setting is never quietly off. `GET /api/health` says
which capabilities are on.

Two more settings widen what joe answers to
([Requests from a browser](#requests-from-a-browser)):

| Setting | Default | What it adds |
| --- | --- | --- |
| `JOE_ALLOWED_HOSTS` | none | Host names joe answers to besides loopback names, IP addresses and `host.docker.internal`, comma-separated, without a port: a name it is reached by on a network, or a container's service name |
| `JOE_ALLOWED_ORIGINS` | none | Pages, as `scheme://host[:port]`, that may send state-changing requests and read the answers, besides joe's own |

**Turning one on.** Under uvicorn, set it in the environment:

```powershell
$env:JOE_ALLOW_MICROPHONE = "1"
uv run uvicorn api:app --port 8010
```

```sh
JOE_ALLOW_MICROPHONE=1 uv run uvicorn api:app --port 8010
```

Under the CLI, name it: `uv run joe backend --allow microphone`; `--allow
all` turns every one on. `uv run joe dev` turns every one on unasked, on
loopback, keeping any setting already in the environment; given `--allow`, it
serves what `backend` would, and `--allow media` the media API alone. The CLI
sets the same variables, for the API process alone.

**What the server prints as it starts**, before it takes a request (a fresh
joe under `uvicorn api:app`):

```text
joe: NO AUTHENTICATION. Whatever can reach this port is answered, with this account's rights.
joe: Run it on one machine you trust, listening on loopback (127.0.0.1). Listening wider opens what is on below to whatever reaches the port (docs/security.md).
joe: on   media        /api/media: audio and video uploaded, then transcribed and analysed by an id only the uploader is given -- a video editor's audio engine (JOE_ALLOW_MEDIA=0 turns it off)
joe: off  microphone   records from this machine's microphone when asked, and takes answers by key -- a voice loop's, such as qmcp's (JOE_ALLOW_MICROPHONE=1 turns it on)
joe: off  transcripts  serves what was said and heard: the conversation as it happens, the take being transcribed, and every take kept (JOE_ALLOW_TRANSCRIPTS=1 turns it on)
joe: off  library      Data/Audio/: lists, serves and takes recordings, transcribes them and Data/Voice/'s by name, and runs the pipeline on them (JOE_ALLOW_LIBRARY=1 turns it on)
```

and, for each capability on, a line such as

```text
joe: !!! WARNING: JOE_ALLOW_TRANSCRIPTS=1. Whatever can reach this port can read every conversation joe has heard, as it happens and from the start.
```

The first request from each address other than this machine's loopback is
announced too, once:

```text
joe: !!! WARNING: answering 192.168.1.20, which is not this machine's loopback. Everything that is on is reachable from there (docs/security.md).
```

---

## Which settings each consumer needs

| Consumer | What it asks joe | Set on joe |
| --- | --- | --- |
| **alfred**, through `vox.media` (`alfred/core/utils/audio_engine.py`) | `GET /api/media/capabilities`, `POST /api/media`, `POST /api/media/{id}/transcribe`, `POST /api/media/{id}/analyze`, `DELETE /api/media/{id}` | **Nothing**: `media` is on in a fresh joe. alfred's containers reach joe as `host.docker.internal` on Docker Desktop and as docker0's address on Linux; joe answers to both. On Linux, listening on docker0's address is a separate choice ([media.md](media.md)) |
| **qmcp's voice loop**: `qmcp human voice`, `qmcp serve --converse`, and joe's page's **Answer by voice** and **Instruct by voice**, which start it | `GET /api/health`, `POST /api/voice/listen`, `POST /api/voice/watch`, `POST /api/voice/unwatch`, `GET /api/voice/control`, `POST /api/voice/conversation` | `JOE_ALLOW_MICROPHONE=1` |
| ...and joe's page showing that conversation (the voice panel, the transcript pane) | `GET /api/voice/conversation` (events), `GET /api/voice/history`, `GET /api/voice/vocabulary`, and `GET /api/voice/takes/{take}/audio` for a take shown on the visualiser; the page's keys and buttons post `answer`, `hold` and `strike` | `JOE_ALLOW_TRANSCRIPTS=1` as well |
| **vox's voice loop**, against a running joe: `vox doctor`, `vox self-report` (live) | `GET /api/health`, `GET /api/voice/devices`, `POST /api/voice/listen` | `JOE_ALLOW_MICROPHONE=1` |
| `vox loop`, `vox self-report FILE` | `POST /api/voice/transcribe?filename=`, on a file it writes where joe resolves names (`--echo-dir`, joe's `Data/Voice/` or `Data/Audio/`) | `JOE_ALLOW_LIBRARY=1` |
| **The family hub**: the performing family's demo, which starts joe with `joe serve` and checks it with `joe check` (joe's `feat/family-control`, not on this branch) | joe's page through Vite: the library, the pipeline and its results; and the hub's `POST /family/cue` and `GET /family/state`, which that branch adds | `JOE_ALLOW_LIBRARY=1`. The `/family` routes write into the library and run the pipeline, and have no capability yet: when that branch lands they belong to `library` or to one of their own |
| **joe's own page** (`joe dev`) | **Library**, **Process**, **Results → Fetch Latest**, playing a recording: `library`. **joe's mic** capture: `microphone` (and `library` to play it back). The voice panel and the transcript pane: `transcripts`. Answering by key or button, holding the talk key, striking a word: `microphone` | `uv run joe dev`, which turns every one on; `--allow` names fewer. With one off, its button is greyed, its tooltip naming the setting; the Library, the transcript pane and Results say it is off and link this page; the first-run hint keeps the steps that work |

Without its setting, a consumer meets the 403 at its first request; alfred
never does. Two report it vaguely ([F18](#findings)), for their own
repositories to change: `vox doctor` reads the 403 from `/api/voice/devices`
as "none found on the engine's machine", and qmcp's voice preflight asks
only `/api/health`, so it speaks its question before the listen is refused.
Either can check `/api/health`'s `allowed.microphone` first.

---

## Threat model

### What is worth protecting

- **The microphone** of joe's machine: whatever the room says.
- **What was said and heard**: every take's WAV segments and transcript under
  `Data/Voice/` (kept until deleted, unless `JOE_DATAPOINTS=0`), the
  conversation as it happens, and the questions asked, qmcp's
  human-in-the-loop questions and their answers among them.
- **Decisions made by voice.** qmcp acts on the answer joe takes, spoken or
  posted as if by key: "approve" to a request waiting on a person.
- **The audio library** (`Data/Audio/`) and the pipeline's output
  (`Data/Output/`).
- **Uploaded media**: alfred's clips and timeline mixes, kept privately under
  `Data/Media/` for an hour after their last use.
- **This machine's files** beyond joe's folders, and its CPU, memory and disk.
- **The repository and the published page**, through CI.

### Who can reach joe

| Who | Reaches joe | Stopped by |
| --- | --- | --- |
| Programs on this machine, under any account | Always, on any binding: every user of the machine shares loopback | Nothing in joe. On a machine shared with people you do not trust, turn nothing on |
| Pages open in a browser on this machine | By making the browser send requests to loopback, and by DNS rebinding | The guard ([Requests from a browser](#requests-from-a-browser)) |
| Containers on this machine | Docker Desktop hands their connections to loopback; on Linux, only when joe listens on docker0's address | The binding |
| Other machines on the network | Only when joe listens beyond loopback | The binding; a host firewall |
| The internet | Only when joe listens on every address and a router forwards the port | The binding; the router |
| Whoever publishes code joe runs or loads | Python and npm packages, the whisper model, CDN scripts, GitHub Actions | Lockfiles with hashes, the model's checksum, integrity attributes, tag pins ([below](#dependencies-and-the-supply-chain)) |
| Contributors | Pull requests run CI | Read-only tokens; nothing published from a PR ([below](#the-deploy-workflow)) |

### Who reaches each binding

| joe listens on | Who reaches the port |
| --- | --- |
| `127.0.0.1` -- the default of uvicorn, `joe backend` and `joe dev` | This machine: its programs, its browsers' pages (refused unless joe's own), and Docker Desktop's containers, which arrive as `127.0.0.1` |
| docker0's address, `172.17.0.1` by default -- for alfred on a Linux Docker host | This machine and its containers -- and a neighbour that routes that address through this machine, unless a firewall says otherwise |
| `0.0.0.0` | Everything that can reach this machine on that port: every device on its network, and the internet if a router forwards the port. A firewall rule admitting the Docker subnets alone narrows it to this machine and its containers |

Every route of a capability that is on is open to everyone in the binding's
row; a route of one that is off, to no one. joe cannot tell those callers
apart: the binding and the capabilities are its whole access control.

**Out of scope:** someone with this account on this machine. They can read
`Data/`, the model cache and joe's code directly, and run joe themselves.

---

## Every route

| Route | Capability | What it does or exposes |
| --- | --- | --- |
| `GET /api/health` | always | `{"status": "ok", "allowed": {...}}`: that joe is up, and which capabilities are on |
| `GET /api/voice/vocabulary` | always | joe's own spoken commands (`Modules/vocabulary.toml`), the same for every joe |
| `GET /openapi.json`, `/docs`, `/redoc` | always | FastAPI's description of every route, and its two explorers ([F13](#findings)) |
| `GET /api/media/capabilities` | `media` | The formats, features, speech model and limits |
| `POST /api/media` | `media` | Takes up to `JOE_MEDIA_MAX_BYTES` (1 GiB) of audio or video, decodes it with ffmpeg on this machine, keeps its sound an hour after its last use; answers its id |
| `POST /api/media/{id}/transcribe` | `media` | Runs whisper on an upload; answers what is said in it. Needs the upload's 128-bit random id |
| `POST /api/media/{id}/analyze` | `media` | Measures an upload's tempo, beats, loudness, silences, peaks |
| `DELETE /api/media/{id}` | `media` | Removes an upload |
| `POST /api/capture/start`, `/stop` | `microphone` | Records from the default input into `Data/Audio/` until stopped |
| `GET /api/voice/devices` | `microphone` | The machine's audio inputs, by name |
| `POST /api/voice/listen` | `microphone` | Records up to 60 s from any input, transcribes it, answers the text and the WAV's path, keeps the take in `Data/Voice/` |
| `POST /api/voice/watch`, `/unwatch` | `microphone` | Opens a take over the question being asked, or closes it |
| `POST /api/voice/level` | `microphone` | Records up to 10 s from an input and answers how loud it was; keeps nothing |
| `POST /api/voice/answer` | `microphone` | An answer taken as if said: ends the take in progress with it, or hands it to the next |
| `POST /api/voice/hold` | `microphone` | Holds the take open, or releases it |
| `POST /api/voice/strike` | `microphone` | Strikes or restores a word of the take being transcribed |
| `GET /api/voice/control` | `microphone` | Whether a key is held, an answer waits, the question is interrupted |
| `POST /api/voice/conversation` | `microphone` | A dialog's state, shown on the page; a `speaking` state is kept as what was said |
| `GET /api/voice/conversation` | `transcripts` | Every state as it happens, as server-sent events -- each take's words among them |
| `GET /api/voice/conversation/state` | `transcripts` | The current state and recent events |
| `GET /api/voice/history` | `transcripts` | Every take and every sentence said, from the start |
| `GET /api/voice/transcript` | `transcripts` | The take being transcribed, or the last |
| `GET /api/voice/takes/{take}/audio` | `transcripts` | One take's recording, by its id, from joe's voice folder alone |
| `GET /api/audio/files` | `library` | The names, sizes and times of `Data/Audio/`'s recordings |
| `GET /api/audio/{filename}` | `library` | One recording, whole |
| `POST /api/audio/upload` | `library` | Writes up to 100 MB into `Data/Audio/` |
| `POST /api/voice/transcribe?filename=` | `library` | Transcribes a file in `Data/Audio/` or `Data/Voice/` by name |
| `POST /api/run`, `/api/run/{filename}` | `library` | Runs the pipeline (`main.py`, up to 120 s) on the newest recording, those named, every one, or the one in the path; answers its output |
| `GET /api/results/latest` | `library` | The latest pipeline output: every note found |

`tests/test_access.py` holds every route to this table: a route added
without a capability fails it.

---

## Requests from a browser

A page on any site, open in a browser on this machine, can make the browser
send requests to `127.0.0.1`. joe answers loopback, so the browser is the
one way in that the binding does not close.

**CORS stops a page reading answers, not sending requests.** A form's POST,
or a `fetch` with a body of type `text/plain`, `application/x-www-form-urlencoded`
or `multipart/form-data` and no custom header, is sent without asking the
server first. Unless joe refuses it, such a request can answer a question
qmcp is asking -- a `text/plain` body holding `{"text": "approve"}`, posted
to `/api/voice/answer` -- post the dialog's state, open a take, start a
recording, or run the pipeline ([F2](#findings)).

**DNS rebinding reads the answers too.** A page loaded from a name its owner
controls can re-point that name at `127.0.0.1`. Its requests are then
same-origin to the browser, so every answer -- every transcript, every
recording -- is the page's to read. They still carry the page's name in
`Host`.

**What joe refuses before any route sees the request** (`Access.Guard`), as
`{"detail": str}`:

| Request | Answer | Why it is safe |
| --- | --- | --- |
| A `Host` that is not `localhost` (or `*.localhost`), an IP address, `host.docker.internal`, or a name in `JOE_ALLOWED_HOSTS` | `400` | A rebinding page arrives under a name of its own. A page loaded from an IP address cannot be re-pointed, so any address is answered -- which is what keeps docker0's address and a LAN address working |
| A POST or DELETE whose `Origin` is not the page joe served at the Host the request was sent to, joe's dev page (`http://localhost:3000`, `http://127.0.0.1:3000`), or one in `JOE_ALLOWED_ORIGINS` -- `null` included | `403` | Every browser sends `Origin` on a cross-origin POST. Through Vite's proxy, joe's page keeps its own Host, and its Origin matches it |
| Anything the browser marks `Sec-Fetch-Site: cross-site`, except following a link | `403` | Catches a form whose Origin was stripped, and another site's `<audio src>` pointing at a recording |
| A JSON route's body -- `answer`, `hold`, `strike`, the dialog's state -- not sent as `application/json` (or a `+json` type) | `415` | What a form or an unpreflighted `fetch` can send is never taken as JSON |

Programs that are not browsers -- alfred through vox, qmcp, curl -- send no
`Origin` and no `Sec-Fetch-Site`. Only the Host rule applies to them, and
the Hosts they use are answered.

**Reading answers.** CORS lets only the pages joe takes requests from read
its answers: its dev page and `JOE_ALLOWED_ORIGINS`, with `GET` and `POST`,
without credentials (`Access.PageCORS`, read on each request). A page from
anywhere else gets a GET's answer without the header that would let it read
it.

**Private Network Access.** Recent Chromium versions ask before a public
page reaches a private or loopback address: a preflight carrying
`Access-Control-Request-Private-Network`, and, newer, a permission prompt.
joe refuses every such preflight, even from a page it takes requests from.
It relies on neither: other browsers do not ask, and a person can click
*Allow*.

**joe's own page.** The page `joe dev` serves is joe's own origin to the
API, so what runs on it can use every capability that is on. It shows what
the API returns as text, never markup ([F4](#findings)); its two CDN scripts
are held to the bytes the lockfile installs ([F7](#findings)). Vite, serving
it on port 3000, refuses Hosts it does not know by itself; its own
advisories are [F8](#findings).

---

## Files, uploads and subprocesses

**Names from a caller never become paths.** A filename (`/api/audio/{filename}`,
`/api/run/{filename}`, `/api/voice/transcribe`) must be a bare name: no
separator, no `..`, no NUL, and no trailing dot or space, which Windows
strips, opening a file under a name no listing shows. It must resolve,
symlinks included, to a file inside `Data/Audio/` (or `Data/Voice/`);
anything else is a 404, like a missing file. A media id must be 32
hexadecimal digits before it reaches the filesystem, and a take's id 6 to 32;
a take's recording is served only from under `Data/Voice/`, whatever its
record names. joe makes every name it writes.

**Where files go.** Some of joe's folders under `Data/` resolve against the
directory the API runs in, some against the checkout. Run the API from the
checkout, as every command here does, and they are one `Data/`.

**Uploads are capped, and judged before they are read.**

| Upload | Cap | How |
| --- | --- | --- |
| `POST /api/media` | `JOE_MEDIA_MAX_BYTES` (1 GiB), and `JOE_MEDIA_MAX_SECONDS` (two hours) of sound | Type (`415`) and declared length (`413`) before a byte is read; written to its private directory as it arrives, refused the moment it passes the cap; decoding stops just past the longest sound |
| `POST /api/audio/upload` | 100 MB | The same: type, then declared length, then written under `Data/Audio/.incoming/` -- served by no route, skipped by the pipeline -- and moved into the library only when whole ([F6](#findings)) |

Nothing caps how many uploads are kept: a caller can keep a gigabyte an hour
per request ([F11](#findings)).

**Temporary files.** Each media upload is a directory named by its random
id, made with mode `0700` (on Windows it takes `Data/`'s permissions). The
upload itself is deleted once ffmpeg has decoded its sound, and the rest
when it expires or is deleted. A refused library upload's partial file is
removed. The voice datapoints -- every segment's WAV and a line of
`segments.jsonl` for each -- are kept until someone deletes them;
`JOE_DATAPOINTS=0` writes none.

**Subprocesses take no shell and no caller's words.**

- **ffmpeg** decodes every media upload and measures loudness: an argument
  list, no shell, `-nostdin`, its input a path joe made, opened only with
  the demuxers of the formats joe takes (`-format_whitelist`) and only as a
  local file (`-protocol_whitelist file`), so a playlist or concat script
  sent as audio cannot read other files into the answer; stopped after 600
  s. It is the largest parser of untrusted input here: keep the one
  `JOE_FFMPEG` names, or the one on `PATH`, current.
- **The pipeline** is `python main.py` at a fixed path, given the file as a
  resolved path in `JOE_AUDIO_FILE`, stopped after 120 s. Nothing limits how
  many run at once ([F11](#findings)).
- **The CLI** starts npm, uvicorn and, on Windows, `taskkill`, with fixed
  arguments.

**What an error says.** A media route's unforeseen failure answers `500`
with the exception's message, and `/api/run` answers the pipeline's output;
either can name paths on this machine ([F12](#findings)).

---

## Dependencies and the supply chain

**Python.** `uv.lock` pins 113 packages, each with its hashes; `uv sync
--frozen` installs exactly those, in CI as here. Among them at this review:
FastAPI 0.135.1, Starlette 0.52.1, uvicorn 0.41.0 (h11 0.16.0),
openai-whisper 20250625, torch 2.14.0, librosa 0.11.0. Dependabot does not
watch them, and this review ran no vulnerability audit of them
([F15](#findings)). The server's dependencies include pytest, pytest-sugar
and nox.

**The whisper model** is downloaded on first use from
`openaipublic.azureedge.net` into `~/.cache/whisper/`, checked by whisper
against the SHA-256 in its URL, and loaded with torch's `weights_only=True`,
which unpickles tensors and nothing that runs code.

**npm.** `package-lock.json` pins every package with its integrity hash, and
CI installs with `npm ci`. `npm audit` on 2026-10-19 reported five high
advisories, all in Vite's dev server and its build-time dependencies
(postcss, picomatch, nanoid, source-map-js), none in what the published page
runs ([F8](#findings)).

**Scripts from a CDN.** The page loads p5 and p5.sound from
`cdn.jsdelivr.net` with `integrity` hashes of the files the lockfile
installs ([F7](#findings)). FastAPI's `/docs` and `/redoc` load Swagger UI
and ReDoc from the same CDN by major version, without integrity, into joe's
own origin ([F13](#findings)).

**GitHub Actions** are pinned by major tag (`actions/checkout@v4`,
`astral-sh/setup-uv@v5`, `JamesIves/github-pages-deploy-action@v4`, ...),
not by commit; Dependabot proposes their updates every week
([F16](#findings)).

---

## The deploy workflow

`deploy.yml` builds the page and publishes it to the `gh-pages` branch, in
two jobs:

| Job | Runs | Token | Does |
| --- | --- | --- | --- |
| `build` | On every PR into `main`, every push to `main`, and by hand | Read-only, and a checkout that keeps no credentials | `npm ci` and the build, so a PR still shows whether the page builds |
| `deploy` | Only when the ref is `refs/heads/main` and the event is a push or a run by hand | `contents: write`, the only job that can write | Publishes the build `build` kept; runs no project code |

A PR from a fork gets a read-only token whatever the workflow says.
`tests.yml` and `e2e.yml` declare read-only tokens too.
`tests/test_workflows.py` holds all of it.

[F5](#findings) was one unguarded job: a PR from a branch of this repository
put its build on GitHub Pages before it was merged, and the whole job --
`npm ci`, every dependency's install scripts, the project's build -- ran
with `contents: write`.

---

## Findings

Severity is for joe as it is meant to run: one trusted machine, on loopback.
Each fixed finding has its test.

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| F1 | High | **Everything on, for whatever reaches the port.** A fresh joe served the microphone, every transcript, the library and the pipeline to any caller, with no authentication | **Fixed in part.** Off by default, each behind a `JOE_ALLOW_` setting with a warning at startup and a 403 naming it; a malformed setting stops the server. `joe dev` turns them on, on loopback, for working on joe. joe stays unauthenticated by design: one trusted machine |
| F2 | High | **Cross-site requests to loopback.** A page on any site could answer a question qmcp was asking (`/api/voice/answer`, a `text/plain` body read as JSON), post the dialog's state, open a take, start a recording or run the pipeline | **Fixed.** `Origin` and `Sec-Fetch-Site` refused from other sites; JSON routes take only JSON |
| F3 | High | **DNS rebinding.** A page re-pointed at `127.0.0.1` read every answer: transcripts, recordings, the library | **Fixed.** Hosts joe does not answer to are refused |
| F4 | Medium | **Markup from file names.** The Library list and the Results summary put file and track names into the page as HTML; a recording named `<img src=x onerror=...>.wav` would run script on the page that drives the API | **Fixed.** Shown as text |
| F5 | Medium | **`deploy.yml` published PRs,** with a writing token held while npm scripts ran | **Fixed.** Published only from `main`; only the publish writes |
| F6 | Medium | **The library's upload was read whole into memory** before its 100 MB cap was checked | **Fixed.** Judged first, written as it arrives |
| F7 | Medium | **CDN scripts without integrity** on the page that drives the API | **Fixed.** `integrity` from the lockfile's p5, held by a spec |
| F8 | Medium | **Vite's dev server**, 6.4.1 here, is within advisories `npm audit` lists as high: a file read through its WebSocket (GHSA-p9ff-h696-f583), a `server.fs.deny` bypass on Windows (GHSA-fx2h-pf6j-xcff), and others in its dependencies. They concern `joe dev`'s port 3000 and the build, not the API or the published page | **Open.** `npm audit fix` resolves them within the declared ranges; not applied here, where dependencies are not changed |
| F9 | Low | **Listening beyond loopback was silent** | **Fixed.** The first request from each such address is announced |
| F10 | Low | **Other accounts on this machine** reach loopback too | **Accepted**, and said above: on a shared machine, turn nothing on |
| F11 | Low | **No quotas.** Media uploads (1 GiB each, kept an hour, any number), pipeline runs and event streams are unbounded: whatever reaches the port can fill the disk or the CPU | **Open** |
| F12 | Low | **Errors name local paths:** a media `500`'s detail and the pipeline's output | **Accepted** for a one-machine tool |
| F13 | Low | **`/docs` and `/redoc`** load Swagger UI and ReDoc from `cdn.jsdelivr.net` by major version, without integrity, into joe's origin: opening them trusts that CDN with every capability that is on | **Open.** Turn them off, or serve pinned copies |
| F14 | Low | **Voice datapoints are kept forever:** every segment's WAV and transcript | **Documented**; `JOE_DATAPOINTS=0` keeps none. No retention period |
| F15 | Low | **Python dependencies are neither watched nor audited,** and the server installs test tools (pytest, pytest-sugar, nox) | **Open** |
| F16 | Low | **Actions pinned by tag,** not commit | **Open**; Dependabot updates them weekly |
| F17 | Info | `tests.yml` and `e2e.yml` ran with the repository's default token | **Fixed.** Read-only |
| F18 | Info | **Consumers report a 403 vaguely:** `vox doctor` reads the microphone's 403 as "none found", and qmcp speaks its question before its listen is refused | **Open**, in vox and qmcp: check `/api/health`'s `allowed` first |
