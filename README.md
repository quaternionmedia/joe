# Joe
A visualizer designed to generate sheet music based on recorded audio.  

Currently written in (sloppy) p5js. Next steps include rewriting in threejs, unity, and C.  

## Design
### Input
Microphone or audio file (.wav)

### Logic

Calculate distribution of note based on desired tuning  
Visualize the staff  
Calculate desired fft windows  
For each fft  
 -Once every frame  
  +Calculate frequency values  
  +Calculate overtone series  
  +Calculate note probability field  
 -Combine note probabilites  
 -Analyze collection of note probabilites  
Fit analisis into rules of sheet music  

### Output
"Realtime" visualization  
MIDI file  
PDF  
Mathematical analysis  
