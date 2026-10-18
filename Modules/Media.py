"""Media: audio and video taken in for the video pipeline, kept privately for a while.

A video editor sends joe a clip or a mixed timeline; joe keeps its sound and
answers questions about it -- what is said in it, and when (`transcribe`), and
how it moves (`Modules.Analysis`). The routes are under `/api/media` in
`api.py`; this module is everything behind them.

**ONE DECODE, THREE COPIES.** ffmpeg decodes the upload's first audio stream
once and writes it three ways (`extract`): `sound.wav` at the source's own rate
and channel count, for levels and peaks; `speech.wav`, 16 kHz mono, for whisper;
and `rhythm.wav`, 22050 Hz mono, for librosa's beat tracker. Format, never
level: nothing is loudness-normalised. The upload itself is deleted once its
sound is out. A track that starts after the media does is padded with silence
to its start, so every time joe answers is in seconds of the uploaded media.

**ONLY MEDIA FORMATS ARE OPENED.** The content type must be one of `FORMATS`,
and ffmpeg may open the file only with the demuxers those formats need
(`DEMUXERS`) and only from a local file: a playlist or a concat script sent as
"audio" could otherwise make ffmpeg read other files on this machine into the
sound it returns.

**PRIVATE, AND KEPT FOR A WHILE.** Each upload is a directory under
`JOE_MEDIA_DIR` (`Data/Media/` by default) named by a random 128-bit id, which
is the only way to reach it. It is kept `JOE_MEDIA_TTL` seconds after it was
last used -- uploaded, transcribed or analysed -- and then swept; `DELETE`
removes it at once. A media in use is never swept, and one deleted while in use
goes when its last use ends.

**ITS OWN WHISPER.** Transcription loads whisper through `Voice._load_model`,
joe's one loader, but into a cache of its own (`MediaSpeech`): two decodes on
one whisper model at once corrupt each other -- each installs hooks on the
same attention layers -- and the voice loop's takes must not queue behind an
hour of captions. Media transcriptions take turns among themselves.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from Modules.Voice import Voice

# Content types joe takes, and the extension the upload is written with. Audio
# as V1 lists it -- wav, mp3, ogg, flac, m4a/aac, webm -- and video -- mp4, mov,
# webm, mkv -- under the names browsers, Python's `mimetypes` and the
# platforms' registries give them.
FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/x-aac": "aac",
    "audio/webm": "webm",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/matroska": "mkv",
}

# The only demuxers ffmpeg may open an upload with: these formats' own. The
# mov demuxer reads mp4, m4a and mov; matroska reads webm and mkv.
DEMUXERS = "wav,mp3,ogg,flac,mov,aac,matroska"

SPEECH_RATE = 16000
RHYTHM_RATE = 22050

DEFAULT_TTL = 3600.0
DEFAULT_MAX_BYTES = 1024**3
DEFAULT_MAX_SECONDS = 7200.0
# Long enough for ffmpeg to decode the longest sound joe takes, many times over.
FFMPEG_TIMEOUT = 600.0

_ID = re.compile(r"[0-9a-f]{32}")
_CHECKOUT = Path(__file__).resolve().parents[1]


class MediaError(Exception):
    """A request about media that cannot be answered as asked: an HTTP status
    and the one-sentence reason the API returns as its `detail`."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _setting(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (value > 0 and math.isfinite(value)):
        raise ValueError(f"{name} must be a positive number of {'bytes' if 'BYTES' in name else 'seconds'}, not {raw!r}")
    return value


def max_bytes() -> int:
    """The largest upload taken, `JOE_MEDIA_MAX_BYTES` (1 GiB by default)."""
    return int(_setting("JOE_MEDIA_MAX_BYTES", DEFAULT_MAX_BYTES))


def max_seconds() -> float:
    """The longest sound taken, `JOE_MEDIA_MAX_SECONDS` (two hours by default)."""
    return _setting("JOE_MEDIA_MAX_SECONDS", DEFAULT_MAX_SECONDS)


def ttl() -> float:
    """How long an upload is kept after its last use, `JOE_MEDIA_TTL` (an hour)."""
    return _setting("JOE_MEDIA_TTL", DEFAULT_TTL)


def media_dir() -> Path:
    """Where uploads are kept: `JOE_MEDIA_DIR`, or `Data/Media/` in the checkout."""
    raw = os.environ.get("JOE_MEDIA_DIR")
    return Path(raw) if raw else _CHECKOUT / "Data" / "Media"


def ffmpeg_path() -> str | None:
    """The ffmpeg joe runs: `JOE_FFMPEG` when set (None if nothing is there), else
    `ffmpeg` on PATH, else None."""
    named = os.environ.get("JOE_FFMPEG")
    if named:
        return named if Path(named).is_file() else None
    return shutil.which("ffmpeg")


def content_kind(content_type: str | None) -> str | None:
    """The bare, lower-cased media type of a Content-Type header, if joe takes it."""
    bare = (content_type or "").split(";")[0].strip().lower()
    return bare if bare in FORMATS else None


# ─── Extraction ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Sound:
    """What an upload's sound is, as the upload route answers it."""

    duration: float
    sample_rate: int
    channels: int


def extract(upload: Path, into: Path, ffmpeg: str, longest: float | None = None) -> Sound:
    """Decode the upload's first audio stream into `sound.wav`, `speech.wav` and
    `rhythm.wav` in `into`, and say what it is.

    Raises MediaError: 422 when the file has no audio stream or none ffmpeg can
    decode, 413 when the sound is longer than `longest` seconds (decoding stops
    just past it, so an over-long file costs little).
    """
    longest = max_seconds() if longest is None else longest
    sound, speech, rhythm = into / "sound.wav", into / "speech.wav", into / "rhythm.wav"
    # Pads a track that starts late with silence, so its first sample is at
    # the media's zero; trims one that starts early.
    align = "aresample=async=1:first_pts=0"
    limit = ["-t", f"{longest + 1:.3f}"]
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-format_whitelist", DEMUXERS, "-protocol_whitelist", "file",
        "-i", str(upload),
        "-map", "0:a:0", "-af", align, *limit, "-c:a", "pcm_s16le", "-rf64", "auto",
        "-f", "wav", str(sound),
        "-map", "0:a:0", "-af", align, *limit, "-ac", "1", "-ar", str(SPEECH_RATE),
        "-c:a", "pcm_s16le", "-f", "wav", str(speech),
        "-map", "0:a:0", "-af", align, *limit, "-ac", "1", "-ar", str(RHYTHM_RATE),
        "-c:a", "pcm_s16le", "-f", "wav", str(rhythm),
    ]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              timeout=FFMPEG_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise MediaError(422, f"ffmpeg did not finish decoding this media in {FFMPEG_TIMEOUT:g} s") from None
    except OSError as exc:
        raise MediaError(503, f"ffmpeg could not be run: {exc}") from None
    if done.returncode != 0:
        if "matches no streams" in done.stderr:
            raise MediaError(422, "this media has no audio stream")
        raise MediaError(422, f"this media has no audio ffmpeg can decode: {_reason(done.stderr, upload)}")
    try:
        info = sf.info(str(sound))
    except (RuntimeError, sf.LibsndfileError) as exc:  # pragma: no cover -- ffmpeg wrote it
        raise MediaError(422, f"this media has no audio ffmpeg can decode: {exc}") from None
    if info.frames == 0:
        raise MediaError(422, "this media's audio stream holds no samples")
    duration = info.frames / info.samplerate
    if duration > longest:
        raise MediaError(413, f"this media's sound is longer than {longest:g} seconds (JOE_MEDIA_MAX_SECONDS)")
    return Sound(duration=round(duration, 3), sample_rate=info.samplerate, channels=info.channels)


def _reason(stderr: str, upload: Path) -> str:
    """ffmpeg's last word on a failure, without the private path it names."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    said = lines[-1] if lines else "no reason given"
    for path in (str(upload), str(upload.parent)):
        said = said.replace(path, "the upload")
    return said[:300]


# ─── The store ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Media:
    """One upload, as a route sees it while using it."""

    media_id: str
    path: Path
    duration: float
    sample_rate: int
    channels: int

    @property
    def sound(self) -> Path:
        return self.path / "sound.wav"

    @property
    def speech(self) -> Path:
        return self.path / "speech.wav"

    @property
    def rhythm(self) -> Path:
        return self.path / "rhythm.wav"

    def answer(self) -> dict:
        """The upload route's answer. `has_audio` is always true here: a file with
        no audio is refused (422) rather than kept."""
        return {"media_id": self.media_id, "duration": self.duration,
                "sample_rate": self.sample_rate, "channels": self.channels, "has_audio": True}


NOT_FOUND = "no such media: it was never uploaded here, has expired, or was deleted"


class MediaStore:
    """Uploads on disk, each in `root/<id>/` with a `meta.json` written last.

    `meta.json` holds what the upload route answered and `last_used`, seconds
    since the epoch by `clock`. A directory without one is an upload still
    arriving -- or one a crash left, which is swept once it is `ttl` old.
    """

    def __init__(self, root: Path | None = None, ttl_seconds: float | None = None, clock=time.time):
        self.root = Path(root) if root is not None else media_dir()
        self.ttl = ttl() if ttl_seconds is None else ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._using: dict[str, int] = {}
        self._doomed: set[str] = set()

    # Paths ------------------------------------------------------------------

    def _dir(self, media_id: str) -> Path | None:
        """The directory for a well-formed id; None for anything else, so no
        client-supplied name ever reaches the filesystem."""
        return self.root / media_id if _ID.fullmatch(media_id or "") else None

    def _meta(self, media_id: str) -> dict | None:
        path = self._dir(media_id)
        try:
            return json.loads((path / "meta.json").read_text(encoding="utf-8")) if path else None
        except (OSError, ValueError):
            return None

    def _write_meta(self, path: Path, meta: dict) -> None:
        temporary = path / "meta.json.tmp"
        temporary.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(temporary, path / "meta.json")

    def _expired(self, meta: dict, now: float) -> bool:
        return now - float(meta.get("last_used", 0)) > self.ttl

    # Arrival ----------------------------------------------------------------

    @contextmanager
    def receiving(self):
        """A new, private directory for an upload on its way in, with a fresh id.

        Yields `(media_id, path)`. Held as in use until `commit` or the block
        ends; if the block ends without a commit -- a refusal, a failure, a
        client gone -- the directory is removed.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        media_id = secrets.token_hex(16)
        path = self.root / media_id
        path.mkdir(mode=0o700)
        with self._lock:
            self._using[media_id] = 1
        try:
            yield media_id, path
        finally:
            with self._lock:
                self._using.pop(media_id, None)
                committed = (path / "meta.json").exists() and media_id not in self._doomed
                self._doomed.discard(media_id)
            if not committed:
                shutil.rmtree(path, ignore_errors=True)

    def commit(self, media_id: str, sound: Sound) -> Media:
        """Record an arrived upload: from here it can be used, and it expires."""
        path = self.root / media_id
        meta = {"media_id": media_id, "duration": sound.duration, "sample_rate": sound.sample_rate,
                "channels": sound.channels, "created": self.clock(), "last_used": self.clock()}
        with self._lock:
            self._write_meta(path, meta)
        return Media(media_id, path, sound.duration, sound.sample_rate, sound.channels)

    # Use --------------------------------------------------------------------

    @contextmanager
    def use(self, media_id: str):
        """The media, held in use for the block: never swept while held, and its
        expiry counted from now. MediaError 404 for an id that is not here."""
        with self._lock:
            meta = self._meta(media_id)
            now = self.clock()
            if meta is None or media_id in self._doomed or (
                    self._expired(meta, now) and not self._using.get(media_id)):
                raise MediaError(404, NOT_FOUND)
            meta["last_used"] = now
            path = self._dir(media_id)
            self._write_meta(path, meta)
            self._using[media_id] = self._using.get(media_id, 0) + 1
        try:
            yield Media(media_id, path, meta["duration"], meta["sample_rate"], meta["channels"])
        finally:
            with self._lock:
                left = self._using[media_id] - 1
                if left:
                    self._using[media_id] = left
                else:
                    del self._using[media_id]
                gone = not left and media_id in self._doomed
                if gone:
                    self._doomed.discard(media_id)
            if gone:
                shutil.rmtree(path, ignore_errors=True)

    def delete(self, media_id: str) -> None:
        """Remove the media now, or when its last use ends. MediaError 404 if it
        is not here."""
        with self._lock:
            meta = self._meta(media_id)
            if meta is None or media_id in self._doomed:
                raise MediaError(404, NOT_FOUND)
            path = self._dir(media_id)
            # From here nothing can use it, whether or not the files remain.
            (path / "meta.json").unlink(missing_ok=True)
            if self._using.get(media_id):
                self._doomed.add(media_id)
                return
        shutil.rmtree(path, ignore_errors=True)

    def sweep(self) -> list[str]:
        """Remove every upload unused for `ttl` seconds, and every directory an
        interrupted upload left that long ago. Returns the ids removed."""
        if not self.root.is_dir():
            return []
        now = self.clock()
        removed = []
        for path in self.root.iterdir():
            media_id = path.name
            if not (path.is_dir() and _ID.fullmatch(media_id)):
                continue  # not an upload's: left alone
            with self._lock:
                if self._using.get(media_id):
                    continue
                meta = self._meta(media_id)
                if meta is not None:
                    stale = self._expired(meta, now)
                else:
                    try:
                        stale = time.time() - path.stat().st_mtime > self.ttl
                    except OSError:
                        continue
                if not stale:
                    continue
                (path / "meta.json").unlink(missing_ok=True)
            shutil.rmtree(path, ignore_errors=True)
            removed.append(media_id)
        return removed


# ─── Transcription ────────────────────────────────────────────────────────────


class MediaSpeech(Voice):
    """whisper for media: `Voice._load_model`, joe's one loader, caching into
    these class attributes rather than Voice's, so the voice loop and the
    media API never decode on one model at once."""

    _model = None
    _model_size: str | None = None


# One media transcription at a time: they share MediaSpeech's model.
_speaking = threading.Lock()


def speech_model_size() -> str:
    """The whisper model media is transcribed with: Voice's own default."""
    return Voice().model_size


def speech_model() -> str:
    """The model's name as the capabilities and every transcript give it."""
    return f"whisper-{speech_model_size()}"


def language_code(language: str | None) -> str | None:
    """whisper's code for a language given as a code or a name ("en",
    "English"); None for none given, which leaves whisper to detect it.
    MediaError 422 for one whisper does not know."""
    if language is None or not language.strip():
        return None
    from whisper.tokenizer import LANGUAGES, TO_LANGUAGE_CODE

    key = language.strip().lower()
    if key in LANGUAGES:
        return key
    if key in TO_LANGUAGE_CODE:
        return TO_LANGUAGE_CODE[key]
    raise MediaError(422, f"unknown language {language!r}; give a code such as 'en' or a name such as 'English'")


def transcribe(media: Media, language: str | None = None, words: bool = True) -> dict:
    """What is said in the media, with segment and word times in its seconds.

    `language` is a code or name, or None for whisper to detect it. `words`
    asks whisper for word timestamps; without them each segment's `words` is
    empty. Returns `{"text", "language", "segments": [{"start", "end", "text",
    "words": [{"start", "end", "word", "probability"}]}], "info"}`.

    A segment's `text` is trimmed; its words are whisper's own, leading space
    included, so they join back into the segment's text in any language.
    """
    code = language_code(language)
    audio, rate = sf.read(str(media.speech), dtype="float32")
    if rate != SPEECH_RATE or audio.ndim != 1:  # pragma: no cover -- extract wrote it
        raise MediaError(500, "this media's speech copy is not 16 kHz mono")
    size = speech_model_size()
    with _speaking:
        model = MediaSpeech._load_model(size)
        cuda = getattr(getattr(model, "device", None), "type", None) == "cuda"
        options: dict = {"word_timestamps": bool(words), "fp16": cuda, "verbose": None}
        if code:
            options["language"] = code
        result = model.transcribe(audio, **options)
    return _transcript(result, f"whisper-{size}", code, bool(words), media.duration)


def _seconds(value) -> float:
    return round(float(value), 3)


def _transcript(result: dict, model: str, language: str | None, words: bool, duration: float) -> dict:
    parts = [p for p in result.get("segments") or [] if isinstance(p, dict)]
    segments = []
    for part in parts:
        segments.append({
            "start": _seconds(part.get("start", 0.0)),
            "end": _seconds(part.get("end", 0.0)),
            "text": str(part.get("text", "")).strip(),
            "words": [
                {"start": _seconds(w.get("start", 0.0)), "end": _seconds(w.get("end", 0.0)),
                 "word": str(w.get("word", "")), "probability": round(float(w.get("probability", 0.0)), 4)}
                for w in (part.get("words") or []) if words and isinstance(w, dict)
            ],
        })

    def values(key):
        return [float(p[key]) for p in parts if isinstance(p.get(key), (int, float))]

    logprobs = values("avg_logprob")
    return {
        "text": str(result.get("text", "")).strip(),
        "language": result.get("language") or language,
        "segments": segments,
        "info": {
            "model": model,
            "language": language,
            "words": words,
            "duration": duration,
            "avg_logprob": round(sum(logprobs) / len(logprobs), 4) if logprobs else None,
            "no_speech_prob": round(max(values("no_speech_prob")), 4) if values("no_speech_prob") else None,
            "compression_ratio": round(max(values("compression_ratio")), 4) if values("compression_ratio") else None,
        },
    }
