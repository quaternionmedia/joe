import librosa 
import numpy as np
import matplotlib.pyplot as plt
from Modules.utilities import apply_band_pass_filter 
from Modules.Chroma import Chroma
from Modules.MIDI import MIDI

class Audio():
    """ Audio class to store the audio properties. \n
        Properties: \n
            chroma_dir: str, chroma folder. \n
            chromas: dict, dictionary of chroma classes. \n
            data_dir: str, audio data folder. \n
            file_path: str, path of audio file. \n
            full_chroma_name: str, full chroma file name. \n
            midi_dir: str, midi folder. \n 
            name: str, name of audio file. \n 
            sr: float, sampling rate. \n
            y: np.ndarray, audio data. \n
    """
    def __init__(self, name:str, file_path:str, data_dir:str, chroma_dir:str, midi_dir:str,
                 overtone_weights:list[float], chroma_threshold:float, min_duration:float,
                 harmonic_threshold:float):
        self.name: str = name
        self.file_path: str = file_path
        self.data_dir:str = data_dir  
        self.midi_dir: str = midi_dir  
        self.chroma_dir: str = chroma_dir  
        self.overtone_weights: list[float] = overtone_weights
        self.chroma_threshold: float = chroma_threshold
        self.min_duration: float = min_duration
        self.harmonic_threshold: float = harmonic_threshold
        self.full_chroma_name: str = f'{self.chroma_dir}{self.name}'
        self.full_chroma_path: str = f'{self.full_chroma_name}_all.png'
        self.chromas: dict[str, Chroma] = {}
        self.sr: float = 0
        self.y: np.ndarray = np.array([])
        self.process_audio()

    def process_audio(self):
        """ Process audio file. \n """
        # load audio files 
        self.y, self.sr = librosa.load(self.file_path, sr=None, mono=True) 
        raw = librosa.stft(self.y)
        D_harmonic, D_percussive = librosa.decompose.hpss(raw, margin=8)   
        # transform   
        transforms:dict[str, np.ndarray] = {}
        transforms['Raw'] = raw
        transforms['Harmonic'] = D_harmonic
        transforms['Percussive'] = D_percussive
        chroma_file_name = f'{self.chroma_dir}{self.name}'
        for transform_type, stft in transforms.items():
            # filtered = stft
            unfiltered = stft
            filtered  = apply_band_pass_filter(stft) 
            # create chroma class 
            first_letter = transform_type[0].lower()
            file_path = f'{chroma_file_name}_{first_letter}.png'
            chroma:Chroma = Chroma(file_path, unfiltered, filtered, transform_type)  
            # create midi class
            midi_file_name = f'{self.midi_dir}{self.name}' 
            midi_file_path = f'{midi_file_name}_{first_letter}.mid'
            chroma.midi: MIDI = MIDI(midi_file_path, transform_type, unfiltered, filtered, 
                                     self.overtone_weights, self.chroma_threshold, self.min_duration, 
                                     self.harmonic_threshold) 
            self.chromas[transform_type] = chroma 
        # create combined chroma
        self.full_chroma_path = f'{chroma_file_name}_full.png'
        self.process_combined_chroma(self.chromas, self.full_chroma_path)

    def process_combined_chroma(self, chromas:dict[str,Chroma], full_path:str=None):
        """ Processes the combined chroma data. \n """ 
        # loop through each chroma and add to subplot 
        rp = np.max(np.abs(chromas['Raw'].unfiltered))
        fig, ax = plt.subplots(nrows=3, sharex=True, sharey=True) 
        fig.set_size_inches(8, 7)
        for i, (transform_type, chroma) in enumerate(chromas.items()):
            img = librosa.display.specshow(
                                    librosa.amplitude_to_db(
                                            np.abs(chroma.unfiltered), 
                                            ref=rp
                                            ),
                                    y_axis='log', 
                                    x_axis='time', 
                                    ax=ax[i]
                                    )
            ax[i].set(title=chroma.title)
            ax[i].label_outer()
        plt.tight_layout()
        plt.savefig(full_path)
        plt.close('all') 