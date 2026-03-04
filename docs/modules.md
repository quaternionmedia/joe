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

## Note

`Note` is a lightweight data container for note identity, pitch, and timing segments used during MIDI serialization.

## Final Artifacts

After outputs are generated, `utilities.save_json()` writes process metadata and note details to:
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`
