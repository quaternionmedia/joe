import os
import sys
import json
from pathlib import Path
import numpy as np
from music21 import pitch

def make_directories(current_path: str) -> dict[str, str]:
    from datetime import datetime

    # create iteration number
    now: datetime = datetime.now()
    formatted_now: str = now.strftime("%m/%d/%y %H:%M:%S")
    iteration = formatted_now.replace("/", "-").replace(":", "-").replace(" ", "_")

    # Directory values keep a trailing separator: Modules/Audio.py composes
    # file names by concatenation, so the separator is part of the contract.
    base = Path(current_path)

    # create audio folder
    audio_dir: Path = base / "Data" / "Audio"
    if not audio_dir.exists():
        audio_dir.mkdir(parents=True)
        print("No audio files found, check directory.")
        sys.exit(0)
    # create iteration folder
    iteration_dir: Path = base / "Data" / "Output" / iteration
    iteration_dir.mkdir(parents=True, exist_ok=True)
    # create midi folder
    midi_dir: Path = iteration_dir / "MIDI"
    midi_dir.mkdir(exist_ok=True)
    # create chroma folder
    chroma_dir: Path = iteration_dir / "Chroma"
    chroma_dir.mkdir(exist_ok=True)
    return {
        "iter": iteration,
        "iter_dir": str(iteration_dir) + os.sep,
        "audio_dir": str(audio_dir) + os.sep,
        "midi_dir": str(midi_dir) + os.sep,
        "chroma_dir": str(chroma_dir) + os.sep,
    }


# What the pipeline reads; api.py's PIPELINE_EXTENSIONS is the same set.
PIPELINE_EXTENSIONS = (".wav", ".webm", ".mp3", ".ogg", ".flac")


def audio_files(audio_dir: str, names: list[str] = (), every: bool = False) -> list[str]:
    """The recordings a run of the pipeline analyses, as paths in `audio_dir`:
    those `names`, in the order named; with `every`, each one, by name; or else
    the newest, the one just recorded. A name that is no recording in the
    folder -- absent, not audio, or not a bare file name -- is refused with a
    ValueError, before anything is analysed.
    """
    folder = Path(audio_dir)

    def recording(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in PIPELINE_EXTENSIONS

    if names:
        chosen = []
        for name in names:
            if Path(name).name != name or not recording(folder / name):
                raise ValueError(f"no recording named {name!r} in {folder}")
            chosen.append(str(folder / name))
        return chosen
    found = sorted((p for p in folder.iterdir() if recording(p)), key=lambda p: p.name) if folder.is_dir() else []
    if every:
        return [str(p) for p in found]
    return [str(max(found, key=lambda p: (p.stat().st_mtime, p.name)))] if found else []


def save_json(
    iteration,
    iteration_dir,
    min_duration,
    fft_sizes,
    chroma_threshold,
    harmonic_threshold,
    overtone_weights,
    audio_files,
    audios,
):
    from Modules.Audio import Audio
    from Modules.Note import Note

    """ Save the process data to a json file \n"""
    # set up the data structure
    data = {}
    data["iteration"] = iteration
    data["min_duration"] = min_duration
    data["fft_sizes"] = fft_sizes
    data["chroma_threshold"] = chroma_threshold
    data["harmonic_threshold"] = harmonic_threshold
    data["overtone_weights"] = overtone_weights
    data["audio_files"] = audio_files
    data["audio"] = {}

    # loop through the audio files
    for aud in audios:
        audio: Audio = aud
        name = audio.name

        # audio data
        data["audio"][name] = {}
        data["audio"][name]["name"] = audio.name
        data["audio"][name]["file_path"] = audio.file_path
        data["audio"][name]["sr"] = audio.sr
        data["audio"][name]["full_chroma_path"] = audio.full_chroma_path

        # chroma data for each transform type
        data["audio"][name]["chroma"] = {}
        for transform_type, chroma in audio.chromas.items():
            data["audio"][name]["chroma"][transform_type] = {}
            data["audio"][name]["chroma"][transform_type][
                "file_path"
            ] = chroma.file_path
            data["audio"][name]["chroma"][transform_type]["midi"] = {}
            data["audio"][name]["chroma"][transform_type]["midi"][
                "file_path"
            ] = chroma.midi.file_path
            data["audio"][name]["chroma"][transform_type]["midi"]["notes"]: list = []
            for item in chroma.midi.notes:
                note: Note = item
                data_note: Note = {}
                data_note["note"]: str = note.note
                data_note["pitch"]: int = note.pitch
                data_note["start_dur"]: list = []
                for start_dur in note.start_dur:
                    stdr = {}
                    stdr["start_time"] = start_dur[0]
                    stdr["duration"] = start_dur[1]
                    data_note["start_dur"].append(stdr)
                data["audio"][name]["chroma"][transform_type]["midi"]["notes"].append(
                    data_note
                )

    with open(Path(iteration_dir) / f"Process_Data_{iteration}.json", "w") as outfile:
        json.dump(data, outfile, indent=4)
