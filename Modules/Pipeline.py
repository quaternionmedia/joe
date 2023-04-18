import os 
from Modules.Audio import Audio

class Pipeline():
    def __init__(self, audio_files:list[str], fft_sizes:float, chroma_threshold:float, 
                 min_duration:float, harmonic_threshold:float, overtone_weights:list[float], 
                 iteration:int, iteration_dir:str): 
        """ Pipeline class to store the audio properties and process properties. \n
            Properties: \n
                audio: list of audio classes. \n
                audio_files: list of audio file paths. \n
                chroma_threshold: float, threshold for chroma filtering. \n
                fft_sizes: list of fft sizes. \n
                harmonic_threshold: float, threshold for harmonic filtering. \n
                min_duration: float, minimum duration of note. \n
                overtone_weights: list of overtone weights. \n
                iteration: int, iteration of process. \n
        """ 
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
            os.mkdir(data_dir)
            os.mkdir(chroma_dir)
            os.mkdir(midi_dir)
            self.audio.append(Audio(name, audio_file_path, data_dir, chroma_dir, midi_dir))
    