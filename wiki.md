Welcome to the joe wiki!

Joe was inspired by Joseph Fourier, polymath who showed us the Fourier Transform, and integral (pun intended) part of this software.



## Overview

Joe is written to create sheet music based on the audio that it takes in. ("listens to"). At present, the visualization resembles sheet music to someone with worse than 2000/20 vision. But it has colors! Changeable colors!

Currently written in (sloppy) p5js. Next steps include rewriting in threejs, unity, and C.  

## Design Goals:
* Audio import (.mp3, .wav...)
* Microphone stream input
* Real(ish) time visualization
* Save and recall analysis
* Export data/analysis
* Export sheet music (.midi, .pdf)


## Design Logic:
## 
* Inputs
  * microphone stream
  * audio file (.wav)
* Logic
  * Calculate distribution of note based on desired tuning  
  * Visualize the staff  
  * Calculate desired fft windows  
  * For each fft  
    * Once every frame  
      * Calculate frequency values  
      * Calculate overtone series  
      * Calculate note probability field  
    * Combine note probabilites  
  * Analyze collection of note probabilites  
* Fit analysis into rules of sheet music  
* Outputs 
  * "Realtime" visualization  
  * MIDI file  
  * PDF  
  * Mathematical analysis  
