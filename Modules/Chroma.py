import numpy as np
import librosa.display
import matplotlib.pyplot as plt
from Modules.MIDI import MIDI

class Chroma():
    """ Chroma class to store the chroma properties. \n
        Properties: \n
            file_path: str, path of chroma file. \n
            filtered: np.ndarray, filtered chroma data. \n
            midi: the chroma's midi class. \n
            plot_image: np.ndarray, image of chroma data. \n
            transform_type: str, type of transform. \n
            unfiltered: np.ndarray, unfiltered chroma data. \n
    """ 
    def __init__(self, file_path:str, unfiltered:np.ndarray, filtered:np.ndarray, transform_type:str):
        self.file_path: str = file_path
        self.filtered: np.ndarray = filtered
        self.transform_type: str = transform_type
        self.unfiltered: np.ndarray = unfiltered
        self.midi: MIDI = None
        self.plot_image: np.ndarray = None
        self.title = f'{transform_type} Spectogram'
        self.process_single_chroma(self.title, self.unfiltered, self.file_path) 

    def process_single_chroma(self, title:str, stft:np.ndarray, file_path:str):
        """ Processes the chroma data. \n """

        rp = np.max(np.abs(stft))
        fig, ax = plt.subplots(nrows=1, sharex=True, sharey=True) 
        img = librosa.display.specshow(librosa.amplitude_to_db(np.abs(stft), ref=rp),
                                y_axis='log', x_axis='time', ax=ax)
        ax.set(title=title)
        ax.label_outer()
        plt.tight_layout()
        plt.savefig(file_path)  
        plt.close('all') 
