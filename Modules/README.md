# Joe.Modules

A place to store main class files.

## AudioToMidi:

Takes in input audio from Data/Audio and creates Audio() classes for each.

## Audio:

Audio class gathers information about the it's audio file and saves to class params. Then creates Chroma() classes for itself and sends the audio file to it.

## Chroma:

Chroma class takes the given audio file and converts to multiple chromas through librosa lib. Will gather information for each type of librosa filter as they're created. Does any post-processing to the chroma before plotting. After plotting, will save chroma.png to \Output. Saves Chroma information to class params. Also, creates a MIDI object that it passes each chroma to.

## MIDI:

MIDI class will take in a chroma type object, do any necessary processing on data, before turning into .mid. Saves MIDI information to class params. Saves .mid file to \Output.

## Post Conversion:

save_json(): AudioToMidi will pass children to save_json(). Function will take passed children and create a Process_Data.json file to save to \Output.
