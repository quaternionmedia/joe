import os
import json
import numpy as np
from music21 import pitch


def get_iteration() -> list[int, str]:
    """Get the iteration of run \n
    Returns:\n
        list: [iteration, iteration_dir] \n
            iteration (int): iteration number.\n
            iteration_dir (str): iteration directory.
    """
    from datetime import datetime

    # get the iteration number
    now: datetime = datetime.now()
    formatted_now: str = now.strftime("%m/%d/%y %H:%M:%S")
    iteration = formatted_now.replace("/", "-").replace(":", "-").replace(" ", "_")
    iteration_dir: str = f"./Data/Output/{iteration}/"
    # create folder for iteration
    if not os.path.exists(iteration_dir):
        os.makedirs(iteration_dir)
    return [iteration, iteration_dir]


def get_audio_files(just_one_file: bool = False) -> list[str]:
    """Get the audio files \n
    Args:\n
        just_one_file (bool): If true, only get the first audio file. \n
    """
    # get audio files
    audio_files: list[str] = []
    if os.path.exists("./Data/Audio/"):
        items = os.listdir("./Data/Audio/")
        for item in items:
            if os.path.isfile("./Data/Audio/" + item):
                audio_files.append(f"./Data/Audio/{item}")
                if just_one_file:
                    break
    else:
        print("No audio folder found, check directory.")
    return audio_files


def midi_to_note_name_music21(midi_number):
    note = pitch.Pitch(midi=midi_number)
    return f"{note.nameWithOctave}"


def apply_band_pass_filter(
    chroma: np.ndarray, lower_bound_pitch: int = 40, upper_bound_pitch: int = 88
) -> np.ndarray:
    """Filter out pitches outside the range of a piano \n
    Args:\n
        chroma (np.ndarray): Chromagram.\n
        lower_bound_pitch (int): Lower bound pitch.\n
        upper_bound_pitch (int): Upper bound pitch.\n
    Returns:\n
        filtered_chroma (np.ndarray): Filtered chromagram.
    """
    filtered_chroma = np.zeros_like(chroma)
    filtered_chroma[lower_bound_pitch:upper_bound_pitch] = chroma[
        lower_bound_pitch:upper_bound_pitch
    ]
    return filtered_chroma


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

    with open(f"{iteration_dir}Process_Data_{iteration}.json", "w") as outfile:
        json.dump(data, outfile, indent=4)
