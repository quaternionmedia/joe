# Joe.Modules

## Runtime Flow

`main.py` -> `Audio` -> `Chroma` -> `MIDI` -> `utilities.save_json()`

- `main.py` analyses recordings in `Data/Audio/` -- the newest, those named on its command
  line, or every one with `--all` (`Modules.utilities.audio_files`) -- into a timestamped
  output folder.
- `Audio` loads audio and orchestrates transform-specific chroma processing.
- `Chroma` computes and post-processes chromagrams, then emits image outputs.
- `MIDI` converts processed chroma data into MIDI note events and `.mid` files.
- `save_json()` writes run metadata and note details to a process JSON file.

## utilities

Generic helper functions used across modules (directory creation, file discovery, serialization helpers, and shared math utilities).

## Audio

`Audio` takes an audio file, gathers metadata, performs processing, and stores results on class fields.

It creates multiple `Chroma` instances for different transform types and handles combined chromagram plotting.

## Chroma

`Audio` does the analysis: the STFT of the recording, its split into harmonic and
percussive parts (HPSS), and a band-pass filter over each, giving three transform types
(Raw, Harmonic, Percussive). For each it builds a `Chroma` and a `MIDI`.

`Chroma` holds a transform's unfiltered and filtered spectra and plots its spectrogram,
writing the image to:
- `Data/Output/<timestamp>/Chroma/`

## MIDI

`MIDI` takes the same spectra, generates note events, and writes `.mid` output to:
- `Data/Output/<timestamp>/MIDI/`

It stores a series of `Note` objects for downstream save/export operations.

Note detection operates on the complex STFT spectrum. Energy at each frequency bin is measured
using `np.abs()` (magnitude), which gives correct results across all three transform types
(Raw, Harmonic, Percussive). Comparing the raw complex value directly would only examine the
real part — which can be negative — and silently suppresses note detection for HPSS-decomposed
signals where phase structure differs from the original STFT.

## Note

`Note` is a lightweight data container for note identity, pitch, and timing segments used during MIDI serialization.

## Voice

`Modules/Voice.py` records from an input device and transcribes with whisper;
the `/api/voice/*` routes and `joe voice` use it. Recording happens on the
machine `joe backend` runs on. The routes' behaviour is in [api.md](api.md);
this is how the module chooses, opens and reads a device.

- **A device is chosen by index or by a fragment of its name.** A fragment
  matching several devices is refused rather than guessed. The same
  microphone can be listed once per host API under a byte-identical name, so
  every listing carries the host API, and the saved choice
  (`Data/voice-device.json`) keeps the name and host API beside the index,
  because PortAudio renumbers devices when one is plugged in or out. With no
  device given, a recording takes `JOE_INPUT_DEVICE`, then the microphone
  `joe voice setup` saved, then the backend's default, which is not always a
  microphone.
- **`joe voice setup` chooses by listening.** It records briefly from every
  input while a person talks (`input_level`), ranks microphones by the
  loudest of their entries and each microphone's entries by host API
  (`HOSTAPI_PREFERENCE`; WDM-KS last, since it bypasses the system mixer and
  reads loudest), and saves the first that records a test sentence.
- **A device opens on its own terms.** It is opened at its native sample rate
  and channel count, and the audio is downmixed and resampled to 16 kHz mono
  afterwards: many devices refuse to open at 16 kHz.
- **Samples no microphone produced are refused.** Some inputs open without
  error and return uninitialised memory -- values far outside [-1, 1], or
  NaN -- which a level meter would read as the loudest device; those raise
  `NoMicrophoneError`. A stream that delivers no block for `STALL_SECONDS`
  is abandoned the same way.
- **Blocks arrive through a stream callback.** The WDM-KS host API does not
  implement blocking reads, and `sd.rec`, which the level sweep records
  with, is callback-driven; the endpointed recorder reads blocks the same
  way, so it records from any device the sweep heard.
- **An endpointed take ends on the speaker's pause.** Speech must be
  sustained to start a take, judged against a floor that tracks the room,
  and `silence_after` of quiet after it (the route's `silence_ms`) ends the
  take. A take opened over a question (`Modules.Watch`) judges speech
  against the question's own echo instead, learned once over the watch's
  first `ECHO_SECONDS` and then held, because a tracked level would climb
  ahead of a voice rising into its first word.

The other voice modules, each documented through the routes that use it in
[api.md](api.md):

| Module | Holds |
| --- | --- |
| `Transcript` | A take's segments, transcribed as they arrive and struck on request, and every segment kept as a datapoint |
| `Watch` | A take opened while a question is still being asked |
| `Control` | An answer given by key, and a held key |
| `Conversation` | The exchange's live states and the microphone's level |
| `History` | The whole transcript, read back from the datapoints |
| `Cue` | The tones that let a turn be followed by ear |
| `Vocabulary` | joe's own spoken phrases, declared in `vocabulary.toml` |

## Final Artifacts

After outputs are generated, `utilities.save_json()` writes process metadata and note details to:
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`

## Access (who may ask for what)

joe has no authentication; `Access` stands in for it ([security.md](security.md)):

- **Capabilities.** Every route of `api.py` but the health check and the
  vocabulary belongs to `media`, `microphone`, `transcripts` or `library`,
  turned on by `JOE_ALLOW_<NAME>`. A fresh joe has `media` alone; a route
  whose capability is off answers 403 naming its setting. `banner` is what
  the server prints as it starts, warning for each one on; `problems` stops
  it starting on a setting it cannot read.
- **The guard.** `Guard`, the API's outermost middleware, refuses a `Host`
  joe does not answer to (DNS rebinding), a state-changing request from
  another site's page (`Origin`), and anything a browser marks cross-site
  except a followed link. It announces each address beyond loopback it
  answers. `PageCORS` lets the pages joe takes requests from read the
  answers.

## Media and Analysis (the video pipeline's audio engine)

Beside the pipeline above, two modules answer a video editor over `/api/media`
([media.md](media.md)):

`api.py /api/media` -> `Media.extract` (ffmpeg) -> `MediaStore` -> `Media.transcribe` (whisper) | `Analysis.analyze` (librosa, ffmpeg)

- `Media` decodes an upload's first audio stream once with ffmpeg into three
  WAVs -- the sound at its own rate and channels, 16 kHz mono for whisper,
  22050 Hz mono for librosa -- and keeps them in a private directory under
  `Data/Media/` named by a random id (`MediaStore`), until `JOE_MEDIA_TTL`
  seconds after their last use. It transcribes with segment and word times on
  its own whisper model (`MediaSpeech`), loaded through `Voice._load_model`
  but never shared with the voice loop.
- `Analysis` measures tempo, beats and onsets (librosa's beat tracker and onset
  detector), RMS and peak level and integrated LUFS (ffmpeg's `ebur128`),
  silent spans and a waveform's peaks. It reads a block at a time, so an hour
  of sound is never held whole, and gives the results librosa gives on the
  whole signal.
