# Joe.Modules

## utilities:

A simple file used to store any generic functions, used throughout code, that did not belong in a specific class.

## Audio:

Audio class takes in an audio file, gathers information from it, does processing on it (band pass filter and the like), and stores to class params.

Then creates multiple Chroma() classes for itself and sends the unfiltered and filtered audio file to them, as well as a transform type. Multiple Chroma classes to define different librosa transforms.

While each Chroma will handle the single chromagram plotting. Audio will handle the 'Combined Chromagram' plotting.

_The handling of Combined Chromagram could change later to be in a separate Chroma class._

## Chroma:

Chroma class takes the given audio file and transform type and creates a chromagram from audio file. It also stores processing information to class params to save later.

It then does post-processing on chromagrams, and plots the result. After plotting, the class saves chroma.png to \Output.

Then creates a MIDI object that it passes the resulting chroma to.

## MIDI:

MIDI class will take in a chroma type object to process. The class stores MIDI information to class params to save later.
After processing, the class saves the resulting .mid file to \Output.

MIDI also saves a series of Note classes to use for processing .mid file.

## Note:

A Note class is a simple storing class. It stores information about each note to be processed and saved later.

## Final Events:

After all the output files have been created and saved, the AudioToMidi class will pass children to utilities.save_json(). Function will take passed children and create a Process_Data.json file to save to \Output. Useful for seeing the data that was used for each run.
