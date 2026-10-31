"""Voice: speech analysis for a single audio source (transcription and mic capture).

Follows the same shape as Audio/Chroma/MIDI — a class wrapping one analysis
concern — so joe's speech-analysis path sits next to its music-analysis path
rather than beside it as a separate tool.
"""

import json
import os
import queue
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.io import wavfile


class NoMicrophoneError(RuntimeError):
    """No usable input device was found, or the audio backend could not be reached.

    Raised in place of whatever `sounddevice`/PortAudio throws natively
    (`PortAudioError`, or an unrelated `OSError` when no backend exists at
    all) so a caller — the CLI, the API, a demo script — sees one clear,
    catchable reason instead of a backend-specific traceback.
    """


def list_input_devices() -> list[dict]:
    """Every audio input device the local machine's backend can see.

    Each entry: {"index", "name", "channels", "default", "hostapi"}.
    Returns an empty list rather than raising when the audio backend itself
    is unreachable (e.g. no PortAudio host API on this machine) — that is a
    "no microphone" fact, not a crash.

    `hostapi` is in the entry because the name is not unique: one microphone
    can appear once per host API under a byte-identical name, and a list
    keyed on the name alone cannot be chosen from.
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        apis = sd.query_hostapis()
        default_input = sd.default.device[0] if sd.default.device is not None else None
    except Exception:
        return []

    def api_name(index) -> str:
        try:
            return apis[index]["name"]
        except (IndexError, KeyError, TypeError):
            return "?"

    return [
        {
            "index": i,
            "name": d["name"],
            "channels": d["max_input_channels"],
            "default": i == default_input,
            # `.get`, so one device missing a field costs that field rather
            # than the whole listing: a caller with no list cannot choose at
            # all, which is worse than a caller with an unlabelled row.
            "hostapi": api_name(d.get("hostapi")),
        }
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]


def resolve_input_device(wanted: int | str | None) -> int | None:
    """Turn what somebody typed into a device index, or raise saying why.

    Accepts an index, a name or a fragment of one, case-insensitively.
    `None` means the backend's default, which is what `sd.rec` uses when
    given nothing.

    A fragment matching several devices is an error rather than a guess:
    the duplicates are real hardware on different host APIs and they do not
    behave the same, so picking one silently would make a recording that
    works on Tuesday fail on Wednesday for no visible reason.
    """
    if wanted is None or wanted == "":
        return None

    devices = list_input_devices()
    if not devices:
        raise NoMicrophoneError(
            "No input devices at all. `joe voice devices` lists what this "
            "machine's audio backend can see."
        )

    if isinstance(wanted, int) or (isinstance(wanted, str) and wanted.lstrip("-").isdigit()):
        index = int(wanted)
        if any(d["index"] == index for d in devices):
            return index
        raise NoMicrophoneError(
            f"No input device with index {index}. `joe voice devices` lists them."
        )

    needle = str(wanted).casefold()
    matches = [d for d in devices if needle in d["name"].casefold()]
    if not matches:
        raise NoMicrophoneError(
            f"No input device whose name contains {wanted!r}. "
            "`joe voice devices` lists them."
        )
    if len(matches) > 1:
        shown = ", ".join(f"{d['index']} ({d['hostapi']})" for d in matches)
        raise NoMicrophoneError(
            f"{len(matches)} input devices match {wanted!r}: {shown}. "
            "Give an index, or a fragment that picks one."
        )
    return matches[0]["index"]


def _native_format(index: int | None) -> tuple[int, int]:
    """The rate and channel count a device will actually open at.

    Many devices refuse to open at 16 kHz mono (WASAPI answers "Invalid
    sample rate"), so the device is opened on its terms and the audio is
    converted afterwards: whisper wants 16 kHz mono, and that is a property
    of the file, not of the microphone.
    """
    import sounddevice as sd

    try:
        info = sd.query_devices(index if index is not None else sd.default.device[0])
        rate = int(info["default_samplerate"])
        channels = max(1, min(2, int(info["max_input_channels"])))
        return rate, channels
    except (KeyError, TypeError):
        # A device dict without the fields PortAudio always supplies. Fall
        # back rather than refuse: 44100 mono opens on more devices than
        # 16000 does.
        return 44100, 1
    except Exception:
        return 44100, 1


def _to_mono_16k(frames, source_rate: int, target_rate: int = 16000):
    """Downmix to one channel and resample, so whisper gets what it needs."""
    mono = frames.mean(axis=1) if frames.ndim > 1 else frames
    if source_rate == target_rate:
        return mono

    from math import gcd

    from scipy.signal import resample_poly

    factor = gcd(int(source_rate), int(target_rate))
    return resample_poly(mono, target_rate // factor, source_rate // factor)


def _capture(duration: float, device: int | str | None, target_rate: int = 16000):
    """Record from `device` and return mono float32 at `target_rate`.

    Returns `(samples, index)`. Raises NoMicrophoneError with the backend's
    own words, which name the format problem when there is one.
    """
    index = resolve_input_device(device)
    rate, channels = _native_format(index)

    import sounddevice as sd

    try:
        frames = sd.rec(
            int(duration * rate),
            samplerate=rate,
            channels=channels,
            dtype="float32",
            device=index,
        )
        sd.wait()
    except Exception as exc:
        raise NoMicrophoneError(
            f"Recording failed on device {index if index is not None else 'default'} "
            f"at {rate} Hz / {channels}ch: {exc}"
        ) from exc

    _reject_unusable(frames, index)

    return _to_mono_16k(frames, rate, target_rate), index


def _reject_unusable(frames, index: int | None) -> None:
    """Refuse samples no microphone produced.

    A device can open and still hand back nothing usable: float32 capture is
    in [-1, 1], and some inputs open without error and return values around
    -2e38, or NaN -- uninitialised memory, not sound. Refused here, such a
    device cannot read as the loudest on the machine to the level meter.
    """
    peak = float(np.abs(frames).max()) if frames.size else 0.0
    # `not (peak <= 1.5)` rather than `peak > 1.5`, because the same devices
    # also return NaN, and every comparison with NaN is False.
    if not (peak <= 1.5):
        raise NoMicrophoneError(
            f"Device {index if index is not None else 'default'} returned samples "
            f"outside [-1, 1] (peak {peak:.3g}). The host API opened it and did "
            f"not deliver audio; try the same microphone on another host API."
        )


def _tell(on_event, state: str, **detail) -> None:
    """Report a state to a watcher, if there is one. Never raises: visual
    feedback must not cost the recording or the transcript it describes."""
    if on_event is None:
        return
    try:
        on_event(state, **detail)
    except Exception:
        pass


# How long an open stream may go without delivering a block before the take
# is abandoned. Some devices open cleanly and never call back; without a bound
# the dialog above would wait on them forever.
STALL_SECONDS = 2.0
# Quiet inside a take that closes one segment of it, for the live transcript.
# Shorter than the pause that ends a take, so a sentence with a breath in it
# arrives in pieces while the person is still talking.
SEGMENT_PAUSE = 0.5


def _capture_until_silence(
    max_duration: float,
    device: int | str | None,
    target_rate: int = 16000,
    silence_after: float = 0.8,
    min_speech: float = 0.2,
    on_event=None,
    control=None,
    on_segment=None,
    segment_pause: float = SEGMENT_PAUSE,
    watch=None,
) -> tuple["np.ndarray", int | None, bool]:
    """Record until the speaker stops, or `max_duration`, whichever is first.

    Returns `(samples, index, speech_detected)`.

    `on_event(state, **detail)`, when given, hears the turn as it happens:
    `listening` once the stream is open, `hearing` when speech has been
    sustained, `pausing` when it stops, `hearing` again if it resumes, and
    `level` with each block's `rms` and the `threshold` it is judged against
    (None while the room is being measured). Only transitions are reported,
    so a watcher sees the protocol rather than the block rate.

    A fixed window is an impolite listener: it truncates a slow answer and
    keeps recording after a quick one. This reads ~100 ms blocks through a
    small state machine of the kind the field settled on:

    - **The floor is the room, and it moves.** It starts from the quietest
      calibration block and keeps tracking non-speech with the time constant
      SpeechRecognition's dynamic energy threshold uses, so a person who
      answers the instant a prompt ends does not raise the bar above their
      own voice.
    - **Speech must be sustained to count** (`min_speech`, as Pipecat's
      `start_secs` and SpeechRecognition's `phrase_threshold` do). A click
      or cough is a transient, not the start of an answer.
    - **`silence_after` of quiet after speech ends the take** — 0.8 s by
      default, SpeechRecognition's `pause_threshold`. Nobody speaking runs
      to the cap, because hanging up on a slow responder is the failure
      this exists to remove.

    Every block from the stream's start is kept, so the onset is never
    clipped and no separate pre-roll buffer is needed.

    **A person can end or hold the turn without speaking** (`control`, a
    `Modules.Control.Control`). An answer given by key raises `Answered` at
    the next block. While a key is held the take neither ends on a pause nor
    at `max_duration` -- it runs to `HOLD_SECONDS` -- and releasing the key
    ends it, as speech that was there: the person said they were speaking.

    **Each stretch of speech is handed on as it ends** (`on_segment(samples,
    start, end, stats)`): `segment_pause` of quiet closes one, held or not,
    and the take's end closes the last. `stats` are its levels against the
    threshold it was judged by. A watcher that raises costs the take nothing.

    **A take can be opened while a question is still being said** (`watch`,
    a `Modules.Watch.Watch`). Until someone begins it, it counts toward no
    cap, takes no answer by key -- that belongs to the take replacing it --
    and judges speech against the question's echo and the quiet room before
    it, not the moving floor: the loudest block of the question's opening
    `watch.learn_seconds`, held, times `watch.factor`, with nothing beginning
    while it is learned. Nothing after is learned, so a voice rising into its
    first word is not taken for more of the question. Speech
    sustained above that, or a held key, begins it: the blocks before the
    onset are dropped, `watch.began()` lets the question stop, and the take
    runs from there as any other. A watch closed at any point raises
    `Unwatched` at the next block.

    **Blocks arrive through a callback**, not `stream.read()`. PortAudio's
    WDM-KS host API does not implement blocking reads: `stream.read` fails
    there with "Blocking API not supported yet", while `sd.rec` -- itself
    callback-driven, and what the level sweep records with -- records from
    the same device. Reading the same way, this records from any device the
    sweep heard.
    """
    index = resolve_input_device(device)
    rate, channels = _native_format(index)

    import sounddevice as sd

    block_seconds = 0.1
    block_frames = max(1, int(rate * block_seconds))
    # round, not int: 0.3 / 0.1 is 2.999… in floats, and truncation would
    # shorten every wait by one block.
    max_blocks = max(1, round(max_duration / block_seconds))
    from Modules.Control import HOLD_SECONDS, Answered

    hold_blocks = max(max_blocks, round(HOLD_SECONDS / block_seconds))
    hold_seen = False
    from Modules.Watch import Unwatched

    watching = watch is not None
    watch_blocks = 0
    echo = room = 0.0
    learn_blocks = round(watch.learn_seconds / block_seconds) if watching else 0
    calibration_blocks = 2
    # Speech is judged against the room, not an absolute: devices and rooms
    # differ by orders of magnitude, and the absolute floor only guards a
    # dead-quiet room from making breath sound like speech.
    speech_factor = 3.0
    absolute_floor = 1e-3
    # SpeechRecognition's damping of 0.15 per second, per block.
    damping = 0.15 ** block_seconds

    taken: list = []
    levels: list[float] = []
    calibration: list[float] = []
    noise: float | None = None
    speech_started = False
    onset_blocks = 0
    quiet_blocks = 0
    needed_onset = max(1, round(min_speech / block_seconds))
    needed_quiet = max(1, round(silence_after / block_seconds))
    needed_segment_quiet = max(1, round(segment_pause / block_seconds))
    segment_from: int | None = None
    segment_quiet = 0
    threshold_now: float | None = None

    def close_segment(until: int) -> None:
        nonlocal segment_from
        start, segment_from = segment_from, None
        if on_segment is None or start is None or until <= start:
            return
        try:
            span = levels[start:until]
            samples = _to_mono_16k(np.concatenate(taken[start:until]), rate, target_rate)
            on_segment(samples, start * block_seconds, until * block_seconds,
                       {"peak_rms": round(max(span), 5), "mean_rms": round(sum(span) / len(span), 5),
                        "threshold": None if threshold_now is None else round(threshold_now, 5),
                        "noise_floor": None if noise is None else round(noise, 5)})
        except Exception:
            pass

    def report(state: str, **detail) -> None:
        _tell(on_event, state, **detail)

    def begin(keep: int) -> None:
        """Someone spoke over the question: the take is theirs from here,
        keeping only the last `keep` blocks before it."""
        nonlocal watching, blocks
        if not watch.began():
            raise Unwatched()
        cut = max(0, len(taken) - keep)
        del taken[:cut]
        del levels[:cut]
        watching = False
        blocks = 0

    arrived: queue.Queue = queue.Queue()

    def on_block(indata, frames, time_info, status):
        # PortAudio reuses `indata` once this returns, so the queue gets a copy.
        arrived.put(indata.copy())

    try:
        with sd.InputStream(
            samplerate=rate,
            channels=channels,
            dtype="float32",
            device=index,
            blocksize=block_frames,
            callback=on_block,
        ):
            report("listening")
            blocks = 0
            while blocks < (hold_blocks if hold_seen and control.held else max_blocks):
                if watch is not None and watch.closed():
                    raise Unwatched()
                if watching:
                    watch_blocks += 1
                    if watch_blocks > hold_blocks:
                        raise Unwatched()  # nobody began within the longest a take may run
                else:
                    blocks += 1
                if control is not None:
                    answer = None if watching else control.take_answer()
                    if answer is not None:
                        raise Answered(answer)
                    if control.held and not hold_seen:
                        hold_seen = True
                        if watching:
                            begin(keep=2)
                        report("holding")
                    elif hold_seen and not control.held:
                        # Released: the person has finished.
                        speech_started = True
                        break
                try:
                    block = arrived.get(timeout=STALL_SECONDS)
                except queue.Empty:
                    raise NoMicrophoneError(
                        f"Device {index if index is not None else 'default'} opened and "
                        f"delivered no audio for {STALL_SECONDS:g} s. Try the same "
                        f"microphone on another host API: `joe voice setup`."
                    ) from None
                block = np.asarray(block, dtype="float32")
                _reject_unusable(block, index)
                taken.append(block)
                rms = float(np.sqrt((block.astype("float64") ** 2).mean())) if block.size else 0.0
                levels.append(rms)
                if len(calibration) < calibration_blocks:
                    calibration.append(rms)
                    noise = room = min(calibration)
                    report("level", rms=rms, threshold=None)
                    continue
                threshold = max(noise * speech_factor, absolute_floor)
                if watching:
                    learning = watch_blocks <= learn_blocks
                    threshold = max(room * speech_factor, absolute_floor, echo * watch.factor)
                threshold_now = threshold
                report("level", rms=rms, threshold=threshold)
                loud = rms >= threshold
                if watching:
                    if learning:
                        echo = max(echo, rms)
                    if learning or not watch.voice:
                        loud = False
                # Segments for the live transcript, counted apart from the
                # take's own end so a held take still arrives in pieces.
                if loud:
                    segment_quiet = 0
                elif segment_from is not None:
                    segment_quiet += 1
                    if segment_quiet == needed_segment_quiet:
                        close_segment(len(taken) - segment_quiet + 1)
                if not speech_started:
                    if loud:
                        onset_blocks += 1
                        if onset_blocks >= needed_onset:
                            if watching:
                                begin(keep=needed_onset + 1)
                            speech_started = True
                            report("hearing")
                            segment_from = max(0, len(taken) - needed_onset - 1)
                    else:
                        onset_blocks = 0
                        noise = noise * damping + rms * (1 - damping)
                elif loud:
                    if quiet_blocks:
                        report("hearing")
                    quiet_blocks = 0
                    if segment_from is None:
                        segment_from = max(0, len(taken) - 2)
                elif hold_seen and control.held:
                    quiet_blocks = 0  # a held turn does not end on a pause
                else:
                    quiet_blocks += 1
                    if quiet_blocks == 1:
                        report("pausing")
                    if quiet_blocks >= needed_quiet:
                        break
    except (NoMicrophoneError, Answered, Unwatched):
        raise
    except Exception as exc:
        raise NoMicrophoneError(
            f"Recording failed on device {index if index is not None else 'default'} "
            f"at {rate} Hz / {channels}ch: {exc}"
        ) from exc

    if speech_started and segment_from is not None:
        close_segment(len(taken))
    frames = np.concatenate(taken) if taken else np.zeros((0, 1), dtype="float32")
    return _to_mono_16k(frames, rate, target_rate), index, speech_started


# Host APIs in the order a recording should prefer them, for one microphone
# listed under several. WDM-KS is last: inputs on it can open and return
# uninitialised memory, and it does not implement blocking reads.
# A host API not named here (ALSA, Core Audio, ...) is usually the only one
# its microphone appears under, so its place matters little.
HOSTAPI_PREFERENCE = ("Windows WASAPI", "MME", "Windows DirectSound")
_HOSTAPI_LAST = ("Windows WDM-KS",)


def rank_candidates(heard: list[tuple[float, dict]]) -> list[dict]:
    """Order the devices a sweep heard, best first.

    `heard` is `(rms, device)` for every input that was not silent.

    Loudness chooses the microphone; the host API chooses the entry. One
    microphone appears once per host API under a byte-identical name, and the
    entries differ in level only by gain staging -- WDM-KS bypasses the
    system mixer and reads loudest, and is the least reliable way to reach
    the microphone. So microphones are ranked by the loudest of their
    entries, and each one's entries by `HOSTAPI_PREFERENCE`; every heard
    entry stays in the list, so a caller that cannot record from one falls
    through to the next.
    """
    loudest: dict[str, float] = {}
    for rms, d in heard:
        loudest[d["name"]] = max(rms, loudest.get(d["name"], 0.0))

    def api_rank(d: dict) -> int:
        if d["hostapi"] in HOSTAPI_PREFERENCE:
            return HOSTAPI_PREFERENCE.index(d["hostapi"])
        if d["hostapi"] in _HOSTAPI_LAST:
            return len(HOSTAPI_PREFERENCE) + 1
        return len(HOSTAPI_PREFERENCE)

    ordered = sorted(heard, key=lambda pair: (-loudest[pair[1]["name"]], api_rank(pair[1])))
    return [d for _, d in ordered]


# Where `joe voice setup` keeps the chosen microphone. Under Data/, which is
# ignored, because the choice is a fact about one machine and not the project.
SAVED_DEVICE = Path(__file__).resolve().parents[1] / "Data" / "voice-device.json"


def save_input_device(device: dict) -> Path:
    """Remember `device` as this machine's microphone. Returns the file written.

    The name and host API are kept beside the index because PortAudio renumbers
    devices when one is plugged in or out; the index is a hint, the name and
    host API are the identity.
    """
    SAVED_DEVICE.parent.mkdir(parents=True, exist_ok=True)
    record = {k: device[k] for k in ("index", "name", "hostapi")}
    SAVED_DEVICE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return SAVED_DEVICE


def saved_input_device() -> int | None:
    """The index of the saved microphone as the devices stand now, or None.

    Read at record time, so a choice made while the backend runs takes
    effect on its next recording with no restart. A device that has moved
    is found by name and host API; one that is gone yields None and the
    backend's default, rather than a stale index naming another device.
    """
    try:
        saved = json.loads(SAVED_DEVICE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    identity = (saved.get("name"), saved.get("hostapi"))
    devices = list_input_devices()
    for d in devices:
        if d["index"] == saved.get("index") and (d["name"], d["hostapi"]) == identity:
            return d["index"]
    for d in devices:
        if (d["name"], d["hostapi"]) == identity:
            return d["index"]
    return None


def default_input_device() -> dict | None:
    """The device `record()` would actually use, or None if there isn't one."""
    devices = list_input_devices()
    for d in devices:
        if d["default"]:
            return d
    return devices[0] if devices else None


def microphone_available() -> bool:
    """Whether `record()` has any usable input device to record from."""
    return default_input_device() is not None


# A take this short or shorter is decoded with a beam: the extra search costs
# little on a word or two, and a one-word answer has no context to recover a
# greedy first guess from.
SHORT_SECONDS = 3.0
HINT_WORDS = 12
HINT_CHARS = 40


def hint_prompt(hint: str | None) -> str | None:
    """The words an answer is expected to be, as whisper's initial prompt.

    `hint` is comma-separated -- "approve, hold" -- and arrives from whoever
    asked the question. A prompt biases the decoder toward its vocabulary and
    never constrains it: what was heard is still what comes back. Blank
    entries are dropped and the list is bounded, so a caller cannot hand the
    decoder a paragraph."""
    if not hint:
        return None
    words = [w.strip() for w in hint.split(",") if w.strip()][:HINT_WORDS]
    words = [w[:HINT_CHARS] for w in words]
    return ", ".join(words) + "." if words else None


def take_confidence(segments) -> float | None:
    """How sure whisper was of a transcript: the lowest of its segments' mean
    token probabilities (`exp(avg_logprob)`), so one doubtful stretch decides.
    None when no segment carries one."""
    import math

    probs = [math.exp(s["avg_logprob"]) for s in segments or []
             if isinstance(s, dict) and isinstance(s.get("avg_logprob"), (int, float))]
    return round(min(probs), 3) if probs else None


def decode_options(hint: str | None, seconds: float, cuda: bool = False) -> dict:
    """How one take is decoded.

    - **English, unless `JOE_LANGUAGE` says otherwise** ("auto" detects). On a
      one-word clip whisper's language detection has almost nothing to go on,
      and a wrong guess transcribes "yes" in another language.
    - **One utterance, not a stream.** `condition_on_previous_text` carries a
      window's text into the next, which a take shorter than a window never
      needs and a hallucinated first window poisons.
    - **fp32 off the GPU**, which whisper otherwise falls back to with a
      warning on every call.
    - **The expected words as the prompt**, when the question said them.
    - **A beam on a short take.**
    """
    options: dict = {"condition_on_previous_text": False, "fp16": cuda}
    language = os.environ.get("JOE_LANGUAGE", "en")
    if language != "auto":
        options["language"] = language
    prompt = hint_prompt(hint)
    if prompt:
        options["initial_prompt"] = prompt
    if seconds <= SHORT_SECONDS:
        options.update(beam_size=5, best_of=5)
    return options


class Voice:
    """Speech-to-text and microphone capture, backed by whisper + sounddevice."""

    _model = None
    _model_size: str | None = None

    def __init__(self, model_size: str = "base", capture_dir: str | None = None):
        self.model_size = model_size
        self.capture_dir = capture_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "Voice"
        )

    @classmethod
    def _load_model(cls, model_size: str):
        """Load (and cache) the whisper model. Imported lazily — heavy and optional."""
        if cls._model is None or cls._model_size != model_size:
            import whisper

            cls._model = whisper.load_model(model_size)
            cls._model_size = model_size
        return cls._model

    def transcribe_samples(self, audio, hint: str | None = None, prompt: str | None = None) -> dict:
        """Transcribe 16 kHz mono samples. `prompt`, when given, is the decoder's
        initial prompt in place of the hint's (the live transcript passes the
        hint and the take's earlier words). Returns `{"text", "segments",
        "language", "info"}`, `info` carrying the decoding settings and
        whisper's own confidence: the mean `avg_logprob` and the largest
        `no_speech_prob` and `compression_ratio` over its segments."""
        model = self._load_model(self.model_size)
        cuda = getattr(getattr(model, "device", None), "type", None) == "cuda"
        options = decode_options(hint, len(audio) / 16000, cuda)
        if prompt:
            options["initial_prompt"] = prompt
        result = model.transcribe(audio, **options)
        parts = result.get("segments") or []

        def values(key):
            return [p[key] for p in parts if isinstance(p, dict) and isinstance(p.get(key), (int, float))]

        logprobs = values("avg_logprob")
        info = {
            "model": self.model_size,
            "language": options.get("language"),
            "beam_size": options.get("beam_size"),
            "avg_logprob": round(sum(logprobs) / len(logprobs), 4) if logprobs else None,
            "no_speech_prob": round(max(values("no_speech_prob")), 4) if values("no_speech_prob") else None,
            "compression_ratio": round(max(values("compression_ratio")), 4) if values("compression_ratio") else None,
        }
        return {"text": result.get("text", "").strip(), "segments": parts,
                "language": result.get("language"), "info": info}

    def transcribe(self, file_path: str, hint: str | None = None) -> dict:
        """Transcribe an existing audio file to text.

        Loads the audio with librosa (soundfile-backed) rather than handing
        whisper a path, so this does not depend on an `ffmpeg` binary being
        on PATH — whisper only shells out to ffmpeg when given a path.
        `hint` is the words the audio is expected to be (`decode_options`).

        Returns: {"text": str, "segments": list, "language": str}
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        import librosa

        audio, _ = librosa.load(file_path, sr=16000, mono=True)
        model = self._load_model(self.model_size)
        # The model's own device decides fp16, rather than importing torch to
        # ask whether a GPU exists that the model may not be on.
        cuda = getattr(getattr(model, "device", None), "type", None) == "cuda"
        result = model.transcribe(audio, **decode_options(hint, len(audio) / 16000, cuda))
        return {
            "text": result.get("text", "").strip(),
            "segments": result.get("segments", []),
            "language": result.get("language"),
        }

    def record(
        self,
        duration: float = 5.0,
        sample_rate: int = 16000,
        device: int | str | None = None,
        until_silence: bool = False,
        silence_after: float = 0.8,
    ) -> str:
        """Record `duration` seconds from an input device to a WAV file.

        Returns the path written to. With `until_silence`, `duration`
        becomes the cap and the recording ends `silence_after` seconds
        after the speaker stops — the polite listener, off by default here
        so library callers keep exact-length semantics.

        `device` is an index or a name fragment. With none, a recording
        takes `JOE_INPUT_DEVICE` if set, else the microphone `joe voice
        setup` saved, else the backend's default. The default is not always
        a microphone -- it can be a capture card -- and a loop recording
        silence from it looks exactly like a loop that mis-heard.

        Raises NoMicrophoneError, rather than a raw PortAudio/OSError, when
        there is no usable input device — checked before recording so the
        failure is the same whether the backend has zero devices or errors
        out entirely.
        """
        return self._take(duration, sample_rate, device, until_silence, silence_after)[0]

    def _take(
        self,
        duration: float,
        sample_rate: int,
        device: int | str | None,
        until_silence: bool,
        silence_after: float,
        on_event=None,
        control=None,
        on_segment=None,
        watch=None,
    ) -> tuple[str, bool | None]:
        """Record, write the WAV, and say whether speech was detected.

        `speech_detected` is None for a fixed window, which does not judge.
        """
        if device is None:
            # An explicit device wins, then the environment, then the choice
            # `joe voice setup` saved, then the backend's default.
            device = os.environ.get("JOE_INPUT_DEVICE") or saved_input_device()

        if resolve_input_device(device) is None and not microphone_available():
            raise NoMicrophoneError(
                "No microphone found. `joe voice devices` lists what this "
                "machine's audio backend can see."
            )

        speech_detected: bool | None = None
        if until_silence:
            frames, _, speech_detected = _capture_until_silence(
                max_duration=duration,
                device=device,
                target_rate=sample_rate,
                silence_after=silence_after,
                on_event=on_event,
                control=control,
                on_segment=on_segment,
                watch=watch,
            )
        else:
            _tell(on_event, "listening")
            frames, _ = _capture(duration, device, target_rate=sample_rate)

        os.makedirs(self.capture_dir, exist_ok=True)
        stamp = datetime.now().strftime("%m-%d-%y_%H-%M-%S")
        out_path = os.path.join(self.capture_dir, f"capture_{stamp}.wav")

        pcm16 = np.clip(frames, -1.0, 1.0)
        pcm16 = (pcm16 * np.iinfo(np.int16).max).astype(np.int16)
        wavfile.write(out_path, sample_rate, pcm16)
        return out_path, speech_detected

    def listen(
        self,
        duration: float = 5.0,
        sample_rate: int = 16000,
        device: int | str | None = None,
        until_silence: bool = False,
        silence_after: float = 0.8,
        on_event=None,
        hint: str | None = None,
        control=None,
        live=None,
        watch=None,
    ) -> dict:
        """Record from an input device and transcribe the result in one step.

        The result carries `speech_detected`: True or False for an endpointed
        take, None for a fixed window. When the endpointer heard no speech,
        the transcriber is not run and `text` is empty — no speech is a
        known answer, and a dialog above needs "heard nothing" as a fact
        distinct from "heard something it could not use".

        `on_event` hears the turn as `_capture_until_silence` describes,
        then `no_speech`, or `transcribing` and `heard` with the text.
        `hint` is the words the answer is expected to be, for the transcriber.

        With `control`, an answer given by key is returned as the transcript,
        `source: "key"`, without recording when it was waiting before the take
        and ending the take when it arrives during one.

        With `live` (a `Modules.Transcript.LiveTranscript`), an endpointed
        take is transcribed segment by segment while it is recorded, and its
        text is the live transcript's: the segments' words minus what was
        struck. A take with speech and no segment falls back to transcribing
        the whole recording.

        With `watch`, the take is opened while a question is still being
        said, as `_capture_until_silence` describes; an answer waiting by key
        is left for the take that replaces it.
        """
        from Modules.Control import Answered

        answer = control.take_answer() if control is not None and watch is None else None
        try:
            if answer is not None:
                raise Answered(answer)
            wav_path, speech_detected = self._take(
                duration, sample_rate, device, until_silence, silence_after, on_event, control,
                on_segment=live.add if live is not None else None, watch=watch,
            )
        except Answered as given:
            _tell(on_event, "heard", text=given.text, source="key")
            return {"text": given.text, "segments": [], "language": None, "audio_path": "",
                    "speech_detected": True, "source": "key", "confidence": 1.0}
        if speech_detected is False:
            if live is not None:
                live.finish()
            _tell(on_event, "no_speech")
            result = {"text": "", "segments": [], "language": None}
        elif live is not None and live.segments:
            _tell(on_event, "transcribing")
            text = live.finish()
            result = {"text": text, "segments": live.snapshot()["segments"], "language": None,
                      "take": live.take, "confidence": live.confidence()}
            _tell(on_event, "heard", text=text)
        else:
            _tell(on_event, "transcribing")
            result = self.transcribe(wav_path, hint=hint)
            result["confidence"] = take_confidence(result.get("segments"))
            _tell(on_event, "heard", text=result.get("text", ""))
        result["audio_path"] = wav_path
        result["speech_detected"] = speech_detected
        return result


def input_level(duration: float = 1.0, device: int | str | None = None,
                sample_rate: int = 16000) -> dict:
    """Record briefly and report how loud it was. Nothing is kept.

    For choosing an input: several can share a name, and no listing says
    which one a voice arrives on. Recording a second from a candidate and
    reading the level answers that in a way reading names cannot: speak, and
    the one that moves is the one to use.

    Returns `{"device", "name", "peak", "rms", "silent"}`, with levels in
    the 0..1 range `sd.rec` produces. `silent` says whether anything
    arrived: a device returning digital silence is either the wrong one or
    muted, and both look the same in a device list.
    """
    frames, index = _capture(duration, device, target_rate=sample_rate)

    samples = np.abs(frames)
    peak = float(samples.max()) if samples.size else 0.0
    rms = float(np.sqrt((samples**2).mean())) if samples.size else 0.0

    named = next((d for d in list_input_devices() if d["index"] == index), None)
    return {
        "device": index,
        "name": named["name"] if named else "default",
        "peak": round(peak, 5),
        "rms": round(rms, 5),
        # Below this, nothing arrived. Chosen as a floor under real room
        # noise rather than as a measure of speech: a live microphone in a
        # quiet room still reads well above digital silence.
        "silent": peak < 1e-4,
    }
