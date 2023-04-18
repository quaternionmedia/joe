import os
import sys
import json
import numpy as np
from music21 import pitch

def make_directories(current_path: str) -> list[str]:
    from datetime import datetime

    # create iteration number
    now: datetime = datetime.now()
    formatted_now: str = now.strftime("%m/%d/%y %H:%M:%S")
    iteration = formatted_now.replace("/", "-").replace(":", "-").replace(" ", "_")

    # create audio folder
    audio_path: str  = f"{current_path}\Data\Audio\\" 
    if not os.path.exists(audio_path):
        os.makedirs(audio_path)
        print("No audio files found, check directory.")
        sys.exit(0)
    # create iteration folder
    iteration_dir: str = f"{current_path}\Data\Output\{iteration}\\" 
    if not os.path.exists(iteration_dir):
        os.makedirs(iteration_dir)
    # create midi folder
    midi_path: str  = f"{current_path}\Data\Output\{iteration}\MIDI\\"
    if not os.path.exists(midi_path):
        os.makedirs(midi_path)
    # create chroma folder
    chroma_path: str  = f"{current_path}\Data\Output\{iteration}\Chroma\\"
    if not os.path.exists(chroma_path):
        os.makedirs(chroma_path)
    return {"iter":iteration, "iter_dir":iteration_dir, "audio_dir":audio_path, "midi_dir":midi_path, "chroma_dir":chroma_path}


def get_audio_files(audio_path: str, just_one_file: bool = False, ) -> list[str]:
    """Get the audio files \n
    Args:\n
        audio_path (str): path of \Audio \n
        just_one_file (bool): If true, only get the first audio file. \n
    """ 
    # get audio files
    audio_files: list[str] = [] 
    if not os.path.exists(audio_path):
        print("Audio directory does not exist, check directory.")
        sys.exit(0)
    else:
        items = os.listdir(audio_path)
        if len(items) > 0:
            for item in items:
                if os.path.isfile(f"{audio_path}{item}"):
                    audio_files.append(f"{audio_path}{item}")
                    if just_one_file:
                        break  
        else: 
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

    with open(f"{iteration_dir}Process_Data_{iteration}.json", "w") as outfile:
        json.dump(data, outfile, indent=4)
