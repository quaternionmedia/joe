import argparse
import os
import sys
from Modules.Audio import Audio
from Modules.utilities import audio_files, save_json, make_directories
 
n_chroma                        = 12    # number of chroma bins
bins_per_octave                 = 12    # number of bins per octave
min_duration: float             = 0.1   # minimum duration for midi note
chroma_threshold: float         = 0.3   # how much 'red' is in the area vs 'blue' to determine if a note is present
harmonic_threshold: float       = 0.3   # threshold for midi note
fft_sizes: list[int]            = [512, 1024, 2048] # fft sizes to use for chromagram
overtone_weights: list[float]   = [0.5, 0.4, 0.3, 0.2]  # looking for presence of harmonic overtone series 
                                                        # to determine if a note is a harmonic this is what 
                                                        # will change a lot for different instruments and 
                                                        # tempo and etc.
params:dict = {'chroma_threshold':chroma_threshold,
               'min_duration':min_duration,
               'harmonic_threshold':harmonic_threshold,
               'fft_sizes':fft_sizes,
               'overtone_weights':overtone_weights}

# get the directory AudioToMidi.py is in
current_path: str = os.path.dirname(os.path.abspath(__file__))
directories: list[str] = make_directories(current_path)
iteration: int = directories["iter"]
data_dir: str = directories["iter_dir"]
audio_dir: str = directories["audio_dir"]
chroma_dir: str = directories["chroma_dir"]
midi_dir: str = directories["midi_dir"]

class AudioToMidi():
    def __init__(self, audio_files: list[str]):
        """ Analyse `audio_files`, paths of recordings, into one iteration of Data/Output/. \n """
        self.audio: list[Audio] = []
        self.audio_files: list[str] = list(audio_files)
        self.chroma_threshold: float = chroma_threshold
        self.fft_sizes: list[float] = fft_sizes
        self.harmonic_threshold: float = harmonic_threshold
        self.min_duration: float = min_duration
        self.overtone_weights: list[float] = overtone_weights
        self.iteration: int = iteration
        self.iteration_dir: str = data_dir 
        self.add_audio_properties() 
        save_json(self.iteration, self.iteration_dir, self.min_duration, self.fft_sizes, 
                  self.chroma_threshold, self.harmonic_threshold, self.overtone_weights,
                  self.audio_files, self.audio)
    
    def add_audio_properties(self):
        """ Set up audio classes and directories. \n
            Parameters: \n
                iteration_dir: str, path of iteration folder. \n
        """ 
        for audio_file_path in self.audio_files:  
            name = os.path.splitext(os.path.basename(audio_file_path))[0]
            self.audio.append(Audio(name, audio_file_path, data_dir, chroma_dir, midi_dir,
                                    self.overtone_weights, self.chroma_threshold, self.min_duration,
                                    self.harmonic_threshold))
        
def chosen_files(argv: list[str] | None = None) -> list[str]:
    """The recordings this run analyses, from its command line: those named,
    every one with --all, or else the newest in Data/Audio/."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Analyse recordings in Data/Audio/: the newest, those named, or --all.")
    parser.add_argument("names", nargs="*", help="recordings in Data/Audio/, by file name")
    parser.add_argument("--all", action="store_true", help="every recording in Data/Audio/")
    args = parser.parse_args(argv)
    if args.all and args.names:
        parser.error("name recordings or ask for --all, not both")
    try:
        files = audio_files(audio_dir, names=args.names, every=args.all)
    except ValueError as err:
        parser.error(str(err))
    if not files:
        print("No audio files found, check directory.")
        sys.exit(0)
    return files


if __name__ == "__main__":
    AudioToMidi(chosen_files())
