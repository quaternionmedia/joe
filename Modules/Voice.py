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

    **`hostapi` is in the entry because the name is not unique.** One machine
    here lists twenty inputs and the same microphone appears three times,
    once per host API, under a byte-identical name. A list keyed on the name
    alone cannot be chosen from.
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

    **RECORDING FORCED 16 kHz MONO AND MOST DEVICES REFUSE IT.** On one
    machine here every input is natively 44100 or 48000 Hz, and asking for
    16000 failed on all four host APIs with four different errors -- WASAPI
    said "Invalid sample rate", the others said less. Nothing could record,
    including the backend's own default.

    So the device is opened on its terms and the audio is converted
    afterwards, which is the only order that works: whisper wants 16 kHz
    mono, and that is a property of the file, not of the microphone.
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
        # 16000 does, which is the whole reason this function exists.
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

    **A DEVICE CAN OPEN AND STILL HAND BACK NOTHING USABLE.** float32
    capture is in [-1, 1]. One WDM-KS input here opens without error and
    returns values around -2e38 -- uninitialised memory, not sound. The
    level meter read that as the loudest device on the machine and
    reported it as the one to use, which is worse than the silence it was
    written to find: a confident wrong answer instead of no answer.
    """
    peak = float(np.abs(frames).max()) if frames.size else 0.0
    # `not (peak <= 1.5)` rather than `peak > 1.5`, because the same devices
    # also return NaN, and every comparison with NaN is False. The first
    # version of this guard used `>` and a NaN run walked straight through
    # it and reported `peak nan` as the loudest device on the machine.
    if not (peak <= 1.5):
        raise NoMicrophoneError(
            f"Device {index if index is not None else 'default'} returned samples "
            f"outside [-1, 1] (peak {peak:.3g}). The host API opened it and did "
            f"not deliver audio; try the same microphone on another host API."
        )


# How long an open stream may go without delivering a block before the take
# is abandoned. Some devices open cleanly and never call back; without a bound
# the dialog above would wait on them forever.
STALL_SECONDS = 2.0


def _capture_until_silence(
    max_duration: float,
    device: int | str | None,
    target_rate: int = 16000,
    silence_after: float = 0.8,
    min_speech: float = 0.2,
) -> tuple["np.ndarray", int | None, bool]:
    """Record until the speaker stops, or `max_duration`, whichever is first.

    Returns `(samples, index, speech_detected)`.

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

    **BLOCKS ARRIVE THROUGH A CALLBACK, NOT `stream.read()`.** PortAudio's
    WDM-KS host API does not implement blocking reads: `stream.read` fails
    there with "Blocking API not supported yet", while `sd.rec` -- itself
    callback-driven -- records from the same device. The level sweep used
    one path and this used the other, so `joe voice setup` chose a device by
    its sweep and then could not record from it.
    """
    index = resolve_input_device(device)
    rate, channels = _native_format(index)

    import sounddevice as sd

    block_seconds = 0.1
    block_frames = max(1, int(rate * block_seconds))
    # round, not int: 0.3 / 0.1 is 2.999… in floats, and truncation quietly
    # shortened every wait by one block.
    max_blocks = max(1, round(max_duration / block_seconds))
    calibration_blocks = 2
    # Speech is judged against the room, not an absolute: devices and rooms
    # differ by orders of magnitude, and the absolute floor only guards a
    # dead-quiet room from making breath sound like speech.
    speech_factor = 3.0
    absolute_floor = 1e-3
    # SpeechRecognition's damping of 0.15 per second, per block.
    damping = 0.15 ** block_seconds

    taken: list = []
    calibration: list[float] = []
    noise: float | None = None
    speech_started = False
    onset_blocks = 0
    quiet_blocks = 0
    needed_onset = max(1, round(min_speech / block_seconds))
    needed_quiet = max(1, round(silence_after / block_seconds))

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
            for _ in range(max_blocks):
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
                if len(calibration) < calibration_blocks:
                    calibration.append(rms)
                    noise = min(calibration)
                    continue
                threshold = max(noise * speech_factor, absolute_floor)
                loud = rms >= threshold
                if not speech_started:
                    if loud:
                        onset_blocks += 1
                        if onset_blocks >= needed_onset:
                            speech_started = True
                    else:
                        onset_blocks = 0
                        noise = noise * damping + rms * (1 - damping)
                elif loud:
                    quiet_blocks = 0
                else:
                    quiet_blocks += 1
                    if quiet_blocks >= needed_quiet:
                        break
    except NoMicrophoneError:
        raise
    except Exception as exc:
        raise NoMicrophoneError(
            f"Recording failed on device {index if index is not None else 'default'} "
            f"at {rate} Hz / {channels}ch: {exc}"
        ) from exc

    frames = np.concatenate(taken) if taken else np.zeros((0, 1), dtype="float32")
    return _to_mono_16k(frames, rate, target_rate), index, speech_started


# Host APIs in the order a recording should prefer them, for one microphone
# listed under several. WDM-KS is last: it is where devices here open and
# return uninitialised memory, and where blocking reads are not implemented.
# A host API not named here (ALSA, Core Audio, ...) is usually the only one
# its microphone appears under, so its place matters little.
HOSTAPI_PREFERENCE = ("Windows WASAPI", "MME", "Windows DirectSound")
_HOSTAPI_LAST = ("Windows WDM-KS",)


def rank_candidates(heard: list[tuple[float, dict]]) -> list[dict]:
    """Order the devices a sweep heard, best first.

    `heard` is `(rms, device)` for every input that was not silent.

    **LOUDNESS CHOOSES THE MICROPHONE; THE HOST API CHOOSES THE ENTRY.** One
    microphone appears once per host API under a byte-identical name, and the
    entries differ in level only by gain staging -- WDM-KS bypasses the
    system mixer and reads loudest. Taking the loudest entry outright chose
    the least reliable way to reach the right microphone. So microphones are
    ranked by the loudest of their entries, and each one's entries by
    `HOSTAPI_PREFERENCE`; every heard entry stays in the list, so a caller
    that cannot record from one falls through to the next.
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

    def transcribe(self, file_path: str) -> dict:
        """Transcribe an existing audio file to text.

        Loads the audio with librosa (soundfile-backed) rather than handing
        whisper a path, so this does not depend on an `ffmpeg` binary being
        on PATH — whisper only shells out to ffmpeg when given a path.

        Returns: {"text": str, "segments": list, "language": str}
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        import librosa

        audio, _ = librosa.load(file_path, sr=16000, mono=True)
        model = self._load_model(self.model_size)
        result = model.transcribe(audio)
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

        `device` is an index or a name fragment; `None` takes the backend's
        default, which is what this did unconditionally before. The default
        is frequently not a microphone — on one machine here it is a capture
        card — and a loop recording silence from it looks exactly like a
        loop that mis-heard.

        Falls back to `JOE_INPUT_DEVICE` when nothing is passed, so the
        choice is made once rather than on every call.

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
            )
        else:
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
    ) -> dict:
        """Record from an input device and transcribe the result in one step.

        The result carries `speech_detected`: True or False for an endpointed
        take, None for a fixed window. When the endpointer heard no speech,
        the transcriber is not run and `text` is empty — no speech is a
        known answer, and a dialog above needs "heard nothing" as a fact
        distinct from "heard something it could not use".
        """
        wav_path, speech_detected = self._take(
            duration, sample_rate, device, until_silence, silence_after
        )
        if speech_detected is False:
            result = {"text": "", "segments": [], "language": None}
        else:
            result = self.transcribe(wav_path)
        result["audio_path"] = wav_path
        result["speech_detected"] = speech_detected
        return result


def input_level(duration: float = 1.0, device: int | str | None = None,
                sample_rate: int = 16000) -> dict:
    """Record briefly and report how loud it was. Nothing is kept.

    **THE POINT OF THIS IS CHOOSING.** A machine here lists twenty inputs,
    several with identical names, and no listing says which one a voice
    actually arrives on. Recording a second from a candidate and reading the
    level answers that in a way reading names cannot: speak, and the one
    that moves is yours.

    Returns `{"device", "name", "peak", "rms", "silent"}`, with levels in
    the 0..1 range `sd.rec` produces. `silent` is the useful field — a
    device returning digital silence is either the wrong one or muted, and
    both look the same in a device list.
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
