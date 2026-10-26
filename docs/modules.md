# Joe.Modules

## Runtime Flow

`main.py` -> `Audio` -> `Chroma` -> `MIDI` -> `utilities.save_json()`

- `main.py` discovers audio in `Data/Audio/` and creates timestamped output folders.
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

`Chroma` takes audio data and transform type, computes a chromagram, performs post-processing, and writes images to:
- `Data/Output/<timestamp>/Chroma/`

It then creates a `MIDI` object using the resulting chroma representation.

## MIDI

`MIDI` takes a `Chroma` object, generates note events, and writes `.mid` output to:
- `Data/Output/<timestamp>/MIDI/`

It stores a series of `Note` objects for downstream save/export operations.

Note detection operates on the complex STFT spectrum. Energy at each frequency bin is measured
using `np.abs()` (magnitude), which gives correct results across all three transform types
(Raw, Harmonic, Percussive). Comparing the raw complex value directly would only examine the
real part — which can be negative — and silently suppresses note detection for HPSS-decomposed
signals where phase structure differs from the original STFT.

## Note

`Note` is a lightweight data container for note identity, pitch, and timing segments used during MIDI serialization.

## Final Artifacts

After outputs are generated, `utilities.save_json()` writes process metadata and note details to:
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`

## Media and Analysis (the video pipeline's audio engine)

Beside the pipeline above, two modules answer a video editor over `/api/media`
([media.md](media.md)):

`api.py /api/media` -> `Media.extract` (ffmpeg) -> `MediaStore` -> `Media.transcribe` (whisper) | `Analysis.analyze` (librosa, ffmpeg)

- `Media` takes an upload in, decodes its first audio stream once with ffmpeg
  into three WAVs -- the sound at its own rate and channels, 16 kHz mono for
  whisper, 22050 Hz mono for librosa -- and keeps them in a private directory
  under `Data/Media/` named by a random id (`MediaStore`), until `JOE_MEDIA_TTL`
  seconds after their last use. It transcribes with segment and word times on
  a whisper model of its own (`MediaSpeech`), loaded through
  `Voice._load_model` but never shared with the voice loop.
- `Analysis` measures tempo, beats and onsets (librosa's beat tracker and onset
  detector), the RMS and peak level and the integrated LUFS (ffmpeg's
  `ebur128`), silent spans and a waveform's peaks -- a block at a time, so an
  hour of sound is never held whole, with the results librosa gives on the
  whole signal.
