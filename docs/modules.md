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

## Final Artifacts

After outputs are generated, `utilities.save_json()` writes process metadata and note details to:
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`
