import os
from Modules.Audio import Audio 
from Modules.utilities import get_audio_files, get_iteration, save_json
 
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
iteration_info: list[int, str] = get_iteration()
iteration: int = iteration_info[0]
iteration_dir: str = iteration_info[1]
just_one_file: bool = True 
audio_files: list[str] = get_audio_files(just_one_file)

class AudioToMidi(): 
    def __init__(self):
        """ Initialize the audio to midi process \n """
        # set title and subtitle  
        self.audio: list[Audio] = []
        self.audio_files: list[str] = audio_files
        self.chroma_threshold: float = chroma_threshold
        self.fft_sizes: list[float] = fft_sizes
        self.harmonic_threshold: float = harmonic_threshold
        self.min_duration: float = min_duration
        self.overtone_weights: list[float] = overtone_weights
        self.iteration: int = iteration
        self.iteration_dir: str = iteration_dir 
        self.add_audio_properties(iteration_dir) 
        save_json(self.iteration, self.iteration_dir, self.min_duration, self.fft_sizes, 
                  self.chroma_threshold, self.harmonic_threshold, self.overtone_weights,
                  self.audio_files, self.audio)
    
    def add_audio_properties(self, iteration_dir:str):
        """ Set up audio classes and directories. \n
            Parameters: \n
                iteration_dir: str, path of iteration folder. \n
        """
        # set up audio classes and directories
        for audio_file_path in self.audio_files:  
            name = audio_file_path.split('/')[-1].split('.')[0] 
            data_dir = f'{iteration_dir}{name}/'
            chroma_dir = f'{data_dir}Chroma/'
            midi_dir = f'{data_dir}MIDI/'  
            if not os.path.exists(data_dir):
                os.mkdir(data_dir)
            if not os.path.exists(chroma_dir):
                os.mkdir(chroma_dir)
            if not os.path.exists(midi_dir):
                os.mkdir(midi_dir)
            self.audio.append(Audio(name, audio_file_path, data_dir, chroma_dir, midi_dir,
                                    self.overtone_weights, self.chroma_threshold, self.min_duration,
                                    self.harmonic_threshold))
        
if __name__ == "__main__":
    AudioToMidi() 