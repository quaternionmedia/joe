import os
import numpy as np
from music21 import stream, note, midi, pitch 
from Modules.Note import Note 

class MIDI():
    """ Midi class to store the midi properties. \n
        Properties: \n
            file_path: str, path of midi file. \n
            transform_type: str, type of transform. \n
            notes: list of note classes. \n
            file: midi.MidiFile, midi file. \n
    """
    def __init__(self, file_path:str, transform_type:str, unfiltered:np.ndarray, 
                 filtered:np.ndarray, overtone_weights:list[float], chroma_threshold:float, 
                 min_duration:float, harmonic_threshold:float): 
        self.file_path: str = file_path
        self.transform_type: str = transform_type
        #self.transforms: list[Transform] = []
        self.notes: list[Note] = []
        self.file: midi.MidiFile = None
        self.unfiltered: np.ndarray = unfiltered
        self.filtered: np.ndarray = filtered
        self.overtone_weights: list[float] = overtone_weights
        self.chroma_threshold: float = chroma_threshold
        self.min_duration: float = min_duration
        self.harmonic_threshold: float = harmonic_threshold
        self.process_midi()

    def process_midi(self):
        """ Process midi file. \n """ 
        # create notes from chroma
        notes:dict = self.chroma_to_midi()
        for pitch, start_dur in notes.items(): 
            note = Note()
            note.note = self.midi_to_note_name_music21(pitch)
            note.pitch = pitch
            note.start_dur = start_dur
            self.notes.append(note)

    def chroma_to_midi(self):
        """ Convert chromagram to midi and save to file. \n """
        # Initialize the MIDI stream
        # # Calculate the key signature
        # key_signature = self.calculate_key_signature()

        # # Add the key signature to the MIDI file
        # midi_stream.insert(0, key_signature)

        # Calculate the duration of each note 
        midi_stream:stream.Stream = stream.Stream() 
        note_durations:dict[int,list] = self.calculate_note() 

        # Add notes to the MIDI stream
        for pitch, durations in note_durations.items():
            for start, duration in durations:
                new_note = note.Note(pitch)
                new_note.quarterLength = duration/100
                new_note.offset = start
                midi_stream.insert(new_note) 

        # Make sure the output file exists 
        if not os.path.exists(os.path.dirname(self.file_path)):
            os.makedirs(os.path.dirname(self.file_path))

        # Save the MIDI stream to file 
        midi_stream.write('midi', fp=self.file_path)

        return note_durations 

    def calculate_note(self) -> dict[int,list]:
        """ Calculate the duration of each note. \n 
            Returns:\n
                note_durations (dict): Dictionary of note durations {key: pitch ,value: tuple(start, duration)}.
        """   
        note_durations:dict[int,list] = {}
        # takes the first chromagram length as the time step
        time_steps = len(self.filtered[0]) 
        for pitch, chroma_data in enumerate(self.filtered):
            note_active = False
            start_time = 0 
            for time_step in range(time_steps):
                if (not note_active and chroma_data[time_step] > self.chroma_threshold 
                    and self.has_sufficient_harmonics(pitch, time_step)):
                    note_active = True
                    start_time = time_step
                elif note_active and chroma_data[time_step] < self.chroma_threshold:
                    note_active = False
                    duration = time_step - start_time
                    if duration > self.min_duration:
                        if pitch not in note_durations:
                            note_durations[pitch] = []
                        note_durations[pitch].append((start_time, duration)) 
        return note_durations

    def has_sufficient_harmonics(self, pitch:int, time_step:int) -> bool:
        """ Check if a note has sufficient harmonics. \n
            Args:\n 
                pitch (int): Pitch of the note.\n
                time_step (int): Time step.\n 
            Returns:\n
                bool: True if the note has sufficient harmonics, False otherwise.
        """
        harmonics_present = 0
        total_weight = 0 

        # Check the 2nd to 5th harmonics in the Klang overtone series
        for idx, harmonic in enumerate(range(1, len(self.overtone_weights))): 
            harmonic_pitch = pitch * harmonic 
            if harmonic_pitch >= len(self.filtered):
                break 
            weight = self.overtone_weights[idx]
            total_weight += weight
            if self.unfiltered[harmonic_pitch][time_step] > self.harmonic_threshold:
                harmonics_present += weight 
        # Require the weighted sum of the harmonics to be at least half of the total possible weighted sum
        return (harmonics_present >= total_weight / 2)

    def midi_to_note_name_music21(self, midi_number):
        note = pitch.Pitch(midi=midi_number)
        return f"{note.nameWithOctave}"
