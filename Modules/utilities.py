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


def get_audio_files(audio_path: str, just_one_file: bool = False) -> list[str]:
    """Get the audio files.

    Args:
        audio_path (str): the Data/Audio directory.
        just_one_file (bool): If true, only get the first audio file.
    """
    audio_dir = Path(audio_path)
    if not audio_dir.exists():
        print("Audio directory does not exist, check directory.")
        sys.exit(0)
    audio_files: list[str] = []
    for item in os.listdir(audio_dir):
        candidate = audio_dir / item
        if candidate.is_file():
            audio_files.append(str(candidate))
            if just_one_file:
                break
    if not audio_files:
        print("No audio files found, check directory.")
        sys.exit(0)
    return audio_files


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
